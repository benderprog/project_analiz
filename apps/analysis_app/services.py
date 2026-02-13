from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from functools import lru_cache
from uuid import UUID

from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from apps.classifier.models import EventTypePattern
from apps.analysis_app.utils.dt_display import format_dt_dmy_hm, to_local_naive
from apps.analysis_app.utils.json_safe import date_to_str, offender_to_json
from apps.analysis_app.utils.offender_format import portal_offender_fullname, svodka_offender_fullname
from apps.portaldb.gateway.dtos import EventDTO, OffenderDTO
from apps.portaldb.gateway.factory import get_portal_gateway

from .offender_extractor import extract_offenders
from .offenders.matching import (
    match_offenders_with_details,
    mention_to_dict,
    portal_to_dict,
    split_mentions_by_employee_context,
)
from .offenders.types import OffenderMention, PortalOffender
from .semantic import get_sentence_model
from .subdivision_matcher import (
    SUBDIVISION_MATCH_THRESHOLD,
    match_subdivision,
)

logger = logging.getLogger(__name__)
DEFAULT_DOB = date(1900, 1, 1)
MATCH_TIME_DELTA_MINUTES = 30
MATCH_STAGE_SUBDIVISION_LIMIT = 500
MATCH_STAGE_TIME_LIMIT = 500
MATCH_STAGE4_OFFENDER_EVENT_LIMIT = 200
MATCH_STAGE_WINDOWS = [
    ("stage1", timedelta(minutes=MATCH_TIME_DELTA_MINUTES)),
    ("stage2", timedelta(days=1)),
    ("stage3", timedelta(days=7)),
]


@dataclass
class ExtractedAttributes:
    date_time: datetime | None
    time_found: bool
    subdivision_id: str | None
    offenders: list[dict]
    subdivision_name: str | None
    subdivision_candidates: list[dict] = field(default_factory=list)
    subdivision_span: list[int] | None = None
    selected_pu_id: uuid.UUID | None = None
    subdivision_candidates_total: int = 0
    subdivision_candidates_after_pu_filter: int = 0
    pu_filter_fallback_used: bool = False


@dataclass(frozen=True)
class HydratedEvent:
    event: EventDTO
    offenders: list[OffenderDTO]


def parse_docx(file_path: str) -> list[str]:
    """Split docx content into non-empty paragraphs."""
    from docx import Document

    document = Document(file_path)
    paragraphs = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            paragraphs.append(text)
    return paragraphs


@lru_cache(maxsize=1)
def _get_morph():
    """Provide a shared MorphVocab for Natasha extractors (required in 1.6+)."""
    from natasha import MorphVocab

    return MorphVocab()


def _fact_to_datetime(fact) -> datetime | None:
    if fact is None:
        return None
    if isinstance(fact, datetime):
        return fact
    if isinstance(fact, date):
        return datetime.combine(fact, time(0, 0))

    if hasattr(fact, "as_datetime"):
        try:
            dt = fact.as_datetime()
        except Exception:
            dt = None
        if dt is not None:
            return dt

    if hasattr(fact, "year") and hasattr(fact, "month") and hasattr(fact, "day"):
        try:
            year = int(getattr(fact, "year"))
            month = int(getattr(fact, "month"))
            day = int(getattr(fact, "day"))
            hour = int(getattr(fact, "hour", 0) or 0)
            minute = int(getattr(fact, "minute", 0) or 0)
            second = int(getattr(fact, "second", 0) or 0)
            return datetime(year, month, day, hour, minute, second)
        except (TypeError, ValueError):
            return None

    return None


_DATETIME_REGEXES = [
    re.compile(
        r"(?:\bв\b\s*)?(?P<time>\d{1,2}[.:]\d{2})\s*(?P<date>\d{2}\.\d{2}\.\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<date>\d{2}\.\d{2}\.\d{4})\s*(?:,|;|—|-)?\s*(?:\bв\b\s*)?"
        r"(?P<time>\d{1,2}[.:]\d{2})",
        re.IGNORECASE,
    ),
]


def _find_datetime_regex_match(text: str) -> re.Match[str] | None:
    for regex in _DATETIME_REGEXES:
        match = regex.search(text)
        if match:
            return match
    return None


def _parse_time_value(time_str: str) -> tuple[int, int] | None:
    normalized = time_str.replace(".", ":")
    parts = normalized.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _extract_datetime_regex(text: str) -> tuple[datetime | None, bool]:
    match = _find_datetime_regex_match(text)
    if not match:
        return None, False

    date_str = match.group("date")
    time_str = match.group("time")
    parsed_time = _parse_time_value(time_str)
    if not parsed_time:
        return None, False

    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        return None, False

    hour, minute = parsed_time
    return datetime.combine(date_obj, time(hour, minute)), True


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(dt_timezone.utc)


def _extract_datetime(text: str) -> tuple[datetime | None, bool]:
    """Extract date/time using regex first, then Natasha; return timezone-aware datetime."""
    from natasha import DatesExtractor

    dt, time_found = _extract_datetime_regex(text)
    if dt is not None:
        aware_dt = _to_utc(dt)
        return aware_dt, time_found

    extractor = DatesExtractor(_get_morph())
    matches = list(extractor(text))
    if not matches:
        return None, False
    dt = _fact_to_datetime(matches[0].fact)
    if dt is None:
        return None, False
    time_found = dt.time() != time(0, 0)
    aware_dt = _to_utc(dt)
    return aware_dt, time_found


def _match_end_index(match) -> int | None:
    span_attr = getattr(match, "span", None)
    if span_attr is not None:
        sp = span_attr() if callable(span_attr) else span_attr
        if isinstance(sp, (tuple, list)) and len(sp) == 2:
            return int(sp[1])
        if hasattr(sp, "stop"):
            return int(sp.stop)
        if hasattr(sp, "end"):
            return int(sp.end)
    if hasattr(match, "stop"):
        return int(match.stop)
    if hasattr(match, "end"):
        return int(match.end)
    if hasattr(match, "start") and hasattr(match, "stop"):
        return int(match.stop)
    return None


def _match_start_index(match) -> int | None:
    span_attr = getattr(match, "span", None)
    if span_attr is not None:
        sp = span_attr() if callable(span_attr) else span_attr
        if isinstance(sp, (tuple, list)) and len(sp) == 2:
            return int(sp[0])
        if hasattr(sp, "start"):
            return int(sp.start)
        if hasattr(sp, "begin"):
            return int(sp.begin)
    if hasattr(match, "start"):
        return int(match.start)
    if hasattr(match, "begin"):
        return int(match.begin)
    return None


def _find_datetime_span(text: str) -> tuple[int, int] | None:
    regex_match = _find_datetime_regex_match(text)
    if regex_match:
        return regex_match.start(), regex_match.end()

    from natasha import DatesExtractor

    extractor = DatesExtractor(_get_morph())
    matches = list(extractor(text))
    if not matches:
        return None
    match = matches[0]
    start = _match_start_index(match)
    end = _match_end_index(match)
    if start is None or end is None:
        return None
    return start, end


def _find_case_insensitive_span(text: str, needle: str) -> tuple[int, int] | None:
    if not needle:
        return None
    match = re.search(re.escape(needle), text, re.IGNORECASE)
    if not match:
        return None
    return match.start(), match.end()


def highlight_text(text: str, spans: list[tuple[int, int, str]]) -> SafeString:
    """Escape text and wrap spans in highlight classes."""
    if not text:
        return mark_safe("")

    filtered: list[tuple[int, int, str]] = []
    sorted_spans = sorted(spans, key=lambda item: (item[0], -(item[1] - item[0])))
    last_end = -1
    for start, end, css_class in sorted_spans:
        if start < 0 or end <= start:
            continue
        if start < last_end:
            continue
        filtered.append((start, end, css_class))
        last_end = end

    if not filtered:
        return mark_safe(escape(text))

    parts: list[str] = []
    cursor = len(text)
    for start, end, css_class in reversed(filtered):
        parts.append(escape(text[end:cursor]))
        span_text = escape(text[start:end])
        parts.append(f'<span class="hl {css_class}">{span_text}</span>')
        cursor = start
    parts.append(escape(text[:cursor]))
    parts.reverse()
    return mark_safe("".join(parts))


def extract_attributes(
    text: str, selected_pu_id: uuid.UUID | None = None
) -> ExtractedAttributes:
    """Extract event attributes from a paragraph."""
    date_time, time_found = _extract_datetime(text)
    offenders = extract_offenders(text)
    subdivision_candidates, candidate_meta = match_subdivision(
        text,
        top_k=5,
        selected_pu_id=selected_pu_id,
    )
    best_candidate = subdivision_candidates[0] if subdivision_candidates else None
    if best_candidate and best_candidate["score"] >= SUBDIVISION_MATCH_THRESHOLD:
        subdivision_id = best_candidate["portal_subdivision_id"]
        subdivision_name = best_candidate["name"]
    else:
        subdivision_id = None
        subdivision_name = None
    subdivision_span = None
    if best_candidate and best_candidate.get("query_span"):
        subdivision_span = list(best_candidate["query_span"])
    return ExtractedAttributes(
        date_time=date_time,
        time_found=time_found,
        subdivision_id=subdivision_id,
        offenders=offenders,
        subdivision_name=subdivision_name,
        subdivision_candidates=subdivision_candidates,
        subdivision_span=subdivision_span,
        selected_pu_id=selected_pu_id,
        subdivision_candidates_total=candidate_meta.get("subdivision_candidates_total", 0),
        subdivision_candidates_after_pu_filter=candidate_meta.get(
            "subdivision_candidates_after_pu_filter", 0
        ),
        pu_filter_fallback_used=candidate_meta.get("pu_filter_fallback_used", False),
    )




def dob_matches(date_a: date | None, date_b: date | None) -> bool:
    if not date_a or not date_b:
        return False
    if date_a == DEFAULT_DOB or date_b == DEFAULT_DOB:
        return False
    if date_a == date_b:
        return True
    if date_a.month == 1 and date_a.day == 1 and date_b.year == date_a.year:
        return True
    if date_b.month == 1 and date_b.day == 1 and date_a.year == date_b.year:
        return True
    return False


def _candidate_birth_date(candidate: dict) -> date | None:
    birth_date = candidate.get("birth_date")
    if isinstance(birth_date, datetime):
        birth_date = birth_date.date()
    if isinstance(birth_date, date):
        return birth_date
    birth_year = candidate.get("birth_year")
    if birth_year:
        try:
            return date(int(birth_year), 1, 1)
        except (TypeError, ValueError):
            return None
    return None


def _portal_offenders(event: HydratedEvent) -> list[OffenderDTO]:
    return list(event.offenders)


def _mention_from_dict(candidate: dict) -> OffenderMention:
    birth_date = _candidate_birth_date(candidate)
    span = candidate.get("span")
    if isinstance(span, list):
        span = tuple(span)
    if not isinstance(span, tuple) or len(span) != 2:
        span = None
    return OffenderMention(
        full_name=candidate.get("full_name") or svodka_offender_fullname(candidate),
        second_name=candidate.get("second_name") or "",
        first_name=candidate.get("first_name") or "",
        patronymic_name=candidate.get("patronymic_name") or "",
        birth_date=birth_date,
        birth_year=(birth_date.year if birth_date else candidate.get("birth_year")),
        span=span,
        source=candidate.get("source") or "unknown",
        surface_text=candidate.get("surface_text") or candidate.get("full_name") or "",
    )


def _portal_offender_to_model(offender: OffenderDTO) -> PortalOffender:
    birth_date = offender.date_of_birth
    if birth_date == DEFAULT_DOB:
        birth_date = None
    return PortalOffender(
        full_name=portal_offender_fullname(offender),
        second_name=offender.second_name or "",
        first_name=offender.first_name or "",
        patronymic_name=offender.patronymic_name or "",
        birth_date=birth_date,
    )


def _portal_offender_payload(offender: OffenderDTO) -> dict:
    model = _portal_offender_to_model(offender)
    return portal_to_dict(model)


def match_offenders(
    extracted: list[dict], portal_offenders: list[OffenderDTO], text: str = ""
) -> tuple[float, dict, dict]:
    mentions = [_mention_from_dict(item) for item in extracted]
    eligible, excluded = split_mentions_by_employee_context(text, mentions)
    portal_models = [_portal_offender_to_model(item) for item in portal_offenders]
    result = match_offenders_with_details(eligible, excluded, portal_models)

    counts = {
        "matched": len(result.matched_pairs),
        "portal_total": len(portal_models),
        "svodka_total": len(extracted),
        "dob_mismatch": len(result.possible_matches),
        "missing_in_portal": len(result.missing_in_portal),
        "missing_in_svodka": len(result.missing_in_summary),
        "ambiguous": len(result.ambiguous_mentions),
    }
    score = counts["matched"] / counts["portal_total"] if counts["portal_total"] else 0.0

    matches = {
        "matched_pairs": [
            {
                "svodka_offender": mention_to_dict(pair.mention),
                "portal_offender": portal_to_dict(pair.portal),
                "match_type": pair.match_type,
                "discrepancy": pair.discrepancy,
            }
            for pair in result.matched_pairs
        ],
        "dob_mismatch_pairs": [
            {
                "svodka_offender": mention_to_dict(item.mention),
                "portal_offender": portal_to_dict(item.portal),
                "reason": item.reason,
            }
            for item in result.possible_matches
        ],
        "missing_in_portal": [mention_to_dict(item) for item in result.missing_in_portal],
        "missing_in_svodka": [portal_to_dict(item) for item in result.missing_in_summary],
        "ambiguous": [
            {
                "svodka_offender": mention_to_dict(item.mention),
                "reason": item.reason,
            }
            for item in result.ambiguous_mentions
        ],
        "excluded_employee_context": [mention_to_dict(item) for item in excluded],
    }
    return score, counts, matches




def _hydrate_events_with_offenders(events: list[EventDTO]) -> list[HydratedEvent]:
    if not events:
        return []

    gateway = get_portal_gateway()
    event_ids = [e.event_id for e in events]

    offenders = gateway.get_offenders_by_event_ids(event_ids)
    by_event: dict[UUID, list[OffenderDTO]] = defaultdict(list)
    for off in offenders:
        by_event[off.event_id].append(off)

    return [HydratedEvent(event=e, offenders=by_event.get(e.event_id, [])) for e in events]

def _looks_like_regex(pattern: str) -> bool:
    return any(char in pattern for char in ".^$*+?{}[]\\|()")


def _classify_event_type(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    best_match = None
    best_length = -1
    patterns = EventTypePattern.objects.select_related("event_type")

    for row in patterns:
        pattern = row.pattern.strip()
        if not pattern:
            continue

        matched = False
        if _looks_like_regex(pattern):
            try:
                matched = re.search(pattern, lowered, re.IGNORECASE) is not None
            except re.error:
                logger.warning("Invalid regex pattern skipped: %s", pattern)
                matched = False
        else:
            matched = pattern.lower() in lowered

        if matched:
            match_length = len(pattern)
            if match_length > best_length:
                best_match = row
                best_length = match_length

    if not best_match:
        return None, None

    return best_match.event_type.event_type, best_match.article_of_law


def _select_event_by_subdivision_time(
    subdivision_id: str, target_dt: datetime
) -> tuple[HydratedEvent | None, int | None]:
    target_utc = _to_utc(target_dt)
    if target_utc is None:
        return None, None
    date_from = target_utc - timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    date_to = target_utc + timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    gateway = get_portal_gateway()
    events = gateway.search_events_by_subdivision_time(subdivision_id, date_from, date_to, MATCH_STAGE_SUBDIVISION_LIMIT)
    candidates = [
        EventDTO(
            event_id=e.event_id,
            date_detection=e.date_detection,
            subdivision_id=e.subdivision_id,
            event_type=e.event_type,
            article_of_law=e.article_of_law,
        )
        for e in events
    ]
    if not candidates:
        return None, None
    closest = min(
        candidates,
        key=lambda event: abs(_to_utc(event.date_detection) - target_utc),
    )
    delta_minutes = int(
        abs(
            _to_utc(closest.date_detection) - target_utc
        ).total_seconds()
        / 60
    )
    if delta_minutes > MATCH_TIME_DELTA_MINUTES:
        return None, None
    hydrated = _hydrate_events_with_offenders([closest])
    return (hydrated[0] if hydrated else None), delta_minutes


def _get_events_for_window(
    *,
    target_dt: datetime,
    minutes_window: int | None = None,
    days_window: int | None = None,
    subdivision_id: str | None = None,
    limit: int = MATCH_STAGE_TIME_LIMIT,
) -> list[EventDTO]:
    target_utc = _to_utc(target_dt)
    if target_utc is None:
        return []
    if minutes_window is not None:
        date_from = target_utc - timedelta(minutes=minutes_window)
        date_to = target_utc + timedelta(minutes=minutes_window)
    elif days_window is not None:
        date_from = target_utc - timedelta(days=days_window)
        date_to = target_utc + timedelta(days=days_window)
    else:
        return []

    gateway = get_portal_gateway()
    if subdivision_id:
        events = gateway.search_events_by_subdivision_time(subdivision_id, date_from, date_to, limit)
    else:
        events = gateway.search_events_by_time(date_from, date_to, limit)
    return [
        EventDTO(
            event_id=e.event_id,
            date_detection=e.date_detection,
            subdivision_id=e.subdivision_id,
            event_type=e.event_type,
            article_of_law=e.article_of_law,
        )
        for e in events
    ]


def _build_subdivision_time_candidates(
    subdivision_id: str, target_dt: datetime, stage_window: timedelta
) -> tuple[list[dict], dict]:
    target_local = to_local_naive(target_dt)
    if target_local is None:
        return [], {"target_local": None}
    date_from = target_local - stage_window
    date_to = target_local + stage_window
    gateway = get_portal_gateway()
    events_subdivision = gateway.search_events_by_subdivision_time(
        subdivision_id,
        date_from,
        date_to,
        MATCH_STAGE_SUBDIVISION_LIMIT,
    )
    events_time = gateway.search_events_by_time(date_from, date_to, MATCH_STAGE_TIME_LIMIT)
    seen_ids: set[UUID] = set()
    combined: list[EventDTO] = []
    for event in [*events_subdivision, *events_time]:
        if event.event_id in seen_ids:
            continue
        seen_ids.add(event.event_id)
        combined.append(
            EventDTO(
                event_id=event.event_id,
                date_detection=event.date_detection,
                subdivision_id=event.subdivision_id,
                event_type=event.event_type,
                article_of_law=event.article_of_law,
            )
        )

    scored_candidates = []
    for event in combined:
        event_local = to_local_naive(event.date_detection)
        if not event_local:
            continue
        delta_minutes = int(abs(event_local - target_local).total_seconds() / 60)
        scored_candidates.append({"event": event, "delta_minutes": delta_minutes})
    return scored_candidates, {
        "target_local": target_local,
        "from": date_from,
        "to": date_to,
        "subdivision_id": str(subdivision_id),
        "subdivision_rows": len(events_subdivision),
        "time_rows": len(events_time),
        "combined_rows": len(scored_candidates),
        "sql": ["search_by_subdivision_time", "search_by_time"],
    }


def _build_stage4_offender_candidates(
    attributes: ExtractedAttributes,
    subdivision_high_conf: bool,
) -> tuple[list[dict], dict]:
    if not attributes.offenders:
        return [], {"triggered": False, "reason": "no_offenders"}

    gateway = get_portal_gateway()
    event_ids: set[UUID] = set()
    searched_names: list[str] = []
    offender_queries: list[dict] = []
    for offender in attributes.offenders:
        full_name = str(offender.get("full_name") or "").strip()
        if not full_name:
            continue
        surname = normalize_name_part(full_name.split()[0])
        if not surname:
            continue
        searched_names.append(surname)
        birth_date = _candidate_birth_date(offender)
        birth_year = offender.get("birth_year")
        if birth_year is None and birth_date is not None:
            birth_year = birth_date.year
        by_offender = gateway.search_event_ids_by_offender(
            second_name=surname,
            birth_year=birth_year,
            birth_date=birth_date,
            subdivision_id=attributes.subdivision_id if subdivision_high_conf else None,
            limit=MATCH_STAGE4_OFFENDER_EVENT_LIMIT,
        )
        offender_queries.append(
            {
                "surname": surname,
                "birth_year": birth_year,
                "birth_date": date_to_str(birth_date),
                "subdivision_id": str(attributes.subdivision_id)
                if (subdivision_high_conf and attributes.subdivision_id)
                else None,
                "rows": len(by_offender),
                "sql": (
                    "search_by_offender_subdivision"
                    if (subdivision_high_conf and attributes.subdivision_id)
                    else "search_by_offender"
                ),
            }
        )
        event_ids.update(by_offender)

    loaded_events: list[HydratedEvent] = []
    for event_id in event_ids:
        event = gateway.get_event_by_id(event_id)
        if event is None:
            continue
        hydrated = _hydrate_events_with_offenders([event])
        if hydrated:
            loaded_events.append(hydrated[0])

    candidates = []
    target_local = to_local_naive(attributes.date_time) if attributes.date_time else None
    for hydrated in loaded_events:
        _, counts, _ = match_offenders(attributes.offenders, _portal_offenders(hydrated))
        overlap = counts.get("matched", 0)
        if overlap < 1:
            continue
        subdivision_ok = attributes.subdivision_id and str(hydrated.event.subdivision_id) == str(attributes.subdivision_id)
        if not subdivision_ok:
            continue
        event_local = to_local_naive(hydrated.event.date_detection)
        delta_minutes = None
        if target_local and event_local:
            delta_minutes = int(abs(event_local - target_local).total_seconds() / 60)
        candidates.append({"event": hydrated, "overlap": overlap, "delta_minutes": delta_minutes})

    return candidates, {
        "triggered": True,
        "searched_names": searched_names,
        "event_ids_found": len(event_ids),
        "hydrated_events": len(loaded_events),
        "scored_candidates": len(candidates),
        "offender_queries": offender_queries,
        "subdivision_limited": bool(subdivision_high_conf and attributes.subdivision_id),
        "sql": ["search_by_offender", "search_by_offender_subdivision", "event_snapshot", "event_offenders"],
    }


def _build_time_offender_candidates(target_dt: datetime, offenders: list[dict]) -> list[dict]:
    if not target_dt:
        return []
    events = _get_events_for_window(target_dt=target_dt, minutes_window=MATCH_TIME_DELTA_MINUTES)
    if not offenders:
        return []
    hydrated_events = _hydrate_events_with_offenders(events)
    target_local = to_local_naive(target_dt)
    candidates: list[dict] = []
    for hydrated in hydrated_events:
        _, counts, _ = match_offenders(offenders, _portal_offenders(hydrated))
        overlap = counts.get("matched", 0)
        if overlap < 1:
            continue
        event_local = to_local_naive(hydrated.event.date_detection)
        delta_minutes = None
        if target_local and event_local:
            delta_minutes = int(abs(event_local - target_local).total_seconds() / 60)
        candidates.append({"event": hydrated, "overlap": overlap, "delta_minutes": delta_minutes})
    return candidates


def _build_subdivision_offender_candidates(
    subdivision_id: str,
    offenders: list[dict],
    target_dt: datetime | None,
) -> list[dict]:
    if not subdivision_id or not offenders or not target_dt:
        return []
    events = _get_events_for_window(target_dt=target_dt, days_window=7, subdivision_id=subdivision_id)
    hydrated_events = _hydrate_events_with_offenders(events)
    target_local = to_local_naive(target_dt)
    candidates: list[dict] = []
    for hydrated in hydrated_events:
        _, counts, _ = match_offenders(offenders, _portal_offenders(hydrated))
        overlap = counts.get("matched", 0)
        if overlap < 1:
            continue
        event_local = to_local_naive(hydrated.event.date_detection)
        delta_minutes = None
        if target_local and event_local:
            delta_minutes = int(abs(event_local - target_local).total_seconds() / 60)
        candidates.append({"event": hydrated, "overlap": overlap, "delta_minutes": delta_minutes})
    return candidates


def _best_by_overlap(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.get("overlap", 0),
            -(item.get("delta_minutes") if item.get("delta_minutes") is not None else 10**9),
        ),
    )


def match_event(attributes: ExtractedAttributes, text: str) -> dict:
    """Match extracted attributes to portal events and build comparison result."""
    subdivision_confidence_percent = 0.0
    subdivision_candidate = (
        attributes.subdivision_candidates[0] if attributes.subdivision_candidates else None
    )
    if attributes.subdivision_candidates:
        subdivision_confidence_percent = round(
            attributes.subdivision_candidates[0]["score"] * 100, 2
        )
    predicted_type, predicted_article = _classify_event_type(text)

    candidates_a = []
    candidates_b = []
    candidates_c = []
    stage_debug = {}

    if attributes.date_time and attributes.subdivision_id:
        for stage_name, stage_window in MATCH_STAGE_WINDOWS:
            staged_candidates, stage_meta = _build_subdivision_time_candidates(
                attributes.subdivision_id,
                attributes.date_time,
                stage_window,
            )
            stage_debug[stage_name] = stage_meta
            logger.debug(
                "Match %s: extracted_dt=%s from=%s to=%s subdivision_id=%s sql=%s rows(subdivision=%s,time=%s,combined=%s)",
                stage_name,
                attributes.date_time,
                stage_meta.get("from"),
                stage_meta.get("to"),
                stage_meta.get("subdivision_id"),
                stage_meta.get("sql"),
                stage_meta.get("subdivision_rows"),
                stage_meta.get("time_rows"),
                stage_meta.get("combined_rows"),
            )
            candidates_a = [
                candidate
                for candidate in staged_candidates
                if candidate.get("delta_minutes") is not None
                and candidate["delta_minutes"] <= MATCH_TIME_DELTA_MINUTES
            ]
            if candidates_a:
                break
    if attributes.date_time:
        candidates_c = _build_time_offender_candidates(
            attributes.date_time,
            attributes.offenders,
        )
    if attributes.subdivision_id:
        candidates_b = _build_subdivision_offender_candidates(
            attributes.subdivision_id,
            attributes.offenders,
            attributes.date_time,
        )

    match_method = None
    best_flags: dict = {}
    best_candidate = None
    best_delta = None
    best_score = -1
    time_mismatch = False
    subdivision_mismatch = False

    scored_candidates = []
    by_event: dict[str, dict] = {}

    def _register(candidate: dict, *, date_ok: bool, subdivision_ok: bool, offenders_ok: bool) -> None:
        event = candidate.get("event")
        if event is None:
            return
        event_id = str(event.event.event_id if isinstance(event, HydratedEvent) else event.event_id)
        item = by_event.setdefault(
            event_id,
            {
                "event": event,
                "date_ok": False,
                "subdivision_ok": False,
                "offenders_ok": False,
                "delta_minutes": candidate.get("delta_minutes"),
            },
        )
        item["date_ok"] = item["date_ok"] or date_ok
        item["subdivision_ok"] = item["subdivision_ok"] or subdivision_ok
        item["offenders_ok"] = item["offenders_ok"] or offenders_ok
        if item.get("delta_minutes") is None and candidate.get("delta_minutes") is not None:
            item["delta_minutes"] = candidate.get("delta_minutes")

    for candidate in candidates_a:
        _register(candidate, date_ok=True, subdivision_ok=True, offenders_ok=False)
    for candidate in candidates_b:
        _register(candidate, date_ok=False, subdivision_ok=True, offenders_ok=True)
    for candidate in candidates_c:
        _register(candidate, date_ok=True, subdivision_ok=False, offenders_ok=True)

    for item in by_event.values():
        item["flags_true"] = int(item["date_ok"]) + int(item["subdivision_ok"]) + int(item["offenders_ok"])
        score = item["flags_true"]
        if score > best_score:
            best_score = score
            best_candidate = item
        scored_candidates.append(item)

    if best_candidate is not None and best_candidate["flags_true"] >= 2:
        if best_candidate["date_ok"] and best_candidate["subdivision_ok"]:
            match_method = "subdivision+time"
        elif best_candidate["date_ok"] and best_candidate["offenders_ok"]:
            match_method = "time+offenders"
            subdivision_mismatch = True
        elif best_candidate["subdivision_ok"] and best_candidate["offenders_ok"]:
            match_method = "subdivision+offenders"
            time_mismatch = True

        best_flags = {
            "date_ok": best_candidate["date_ok"],
            "subdivision_ok": best_candidate["subdivision_ok"],
            "offenders_ok": best_candidate["offenders_ok"],
        }
    else:
        best_event = None

    should_run_stage4 = (
        attributes.offenders
        and (
            len(scored_candidates) == 0
            or best_candidate is None
            or best_candidate.get("flags_true", 0) < 2
        )
    )
    if should_run_stage4:
        stage4_candidates, stage4_meta = _build_stage4_offender_candidates(
            attributes,
            subdivision_confidence_percent >= SUBDIVISION_MATCH_THRESHOLD * 100,
        )
        stage_debug["stage4_offenders"] = stage4_meta
        logger.debug(
            "Match stage4_offenders: extracted_dt=%s subdivision_id=%s sql=%s event_ids=%s candidates=%s",
            attributes.date_time,
            attributes.subdivision_id,
            stage4_meta.get("sql"),
            stage4_meta.get("event_ids_found"),
            stage4_meta.get("scored_candidates"),
        )
        if stage4_candidates:
            best_candidate = _best_by_overlap(stage4_candidates)
            if best_candidate is not None:
                match_method = "subdivision+offenders"
                time_mismatch = True
                best_flags = {
                    "date_ok": False,
                    "subdivision_ok": True,
                    "offenders_ok": True,
                }

    best_event = None
    if best_candidate is not None:
        best_event = best_candidate["event"]
        best_delta = best_candidate.get("delta_minutes")
        if match_method == "subdivision+time":
            hydrated = _hydrate_events_with_offenders([best_event])
            best_event = hydrated[0] if hydrated else None

    top_overlap_c = max((item["overlap"] for item in candidates_c), default=0)
    top_overlap_b = max((item["overlap"] for item in candidates_b), default=0)
    debug_meta = {
        "candidates_total": len(scored_candidates),
        "stage1_subdivision_time": stage_debug.get("stage1", {}).get("subdivision_rows", 0),
        "stage1_time": stage_debug.get("stage1", {}).get("time_rows", 0),
        "stage2_subdivision_time": stage_debug.get("stage2", {}).get("subdivision_rows", 0),
        "stage2_time": stage_debug.get("stage2", {}).get("time_rows", 0),
        "stage3_subdivision_time": stage_debug.get("stage3", {}).get("subdivision_rows", 0),
        "stage3_time": stage_debug.get("stage3", {}).get("time_rows", 0),
        "subdivision_candidates_total": attributes.subdivision_candidates_total,
        "subdivision_candidates_after_pu_filter": (
            attributes.subdivision_candidates_after_pu_filter
        ),
        "pu_filter_fallback_used": attributes.pu_filter_fallback_used,
        "selected_pu_id": str(attributes.selected_pu_id)
        if attributes.selected_pu_id
        else None,
        "chosen_method": match_method,
        "stages": stage_debug,
        "candidate_stages": [
            {"stage": "subdivision+time", "count": len(candidates_a)},
            {"stage": "subdivision+offenders", "count": len(candidates_b)},
            {"stage": "time+offenders", "count": len(candidates_c)},
        ],
        "stage1_best_score": max(best_score, 0),
        "score_threshold": 2,
        "subdivision_confidence_high": subdivision_confidence_percent
        >= SUBDIVISION_MATCH_THRESHOLD * 100,
    }

    if not best_event:
        unit_type_conflict = bool(
            subdivision_candidate.get("flags", {}).get("unit_type_conflict")
            if subdivision_candidate
            else False
        )
        return {
            "matched": False,
            "score_percent": 0,
            "time_delta_minutes": None,
            "offenders_score_percent": 0,
            "offenders_counts": {
                "svodka_total": len(attributes.offenders),
                "portal_total": 0,
                "matched": 0,
                "dob_mismatch": 0,
                "missing_in_portal": len(attributes.offenders),
                "missing_in_svodka": 0,
            },
            "subdivision_match_percent": subdivision_confidence_percent,
            "time_found": attributes.time_found,
            "date_time_present": bool(attributes.date_time),
            "subdivision_locality_query": subdivision_candidate.get("query_locality")
            if subdivision_candidate
            else None,
            "subdivision_locality_candidate": subdivision_candidate.get("candidate_locality")
            if subdivision_candidate
            else None,
            "subdivision_locality_mismatch": bool(
                subdivision_candidate.get("locality_mismatch") if subdivision_candidate else False
            ),
            "subdivision_unit_type_conflict": unit_type_conflict,
            "extracted_subdivision_name": attributes.subdivision_name,
            "portal": None,
            "predicted": {
                "event_type": predicted_type,
                "article_of_law": predicted_article,
            },
            "match_method": None,
            "time_mismatch": False,
            "subdivision_mismatch": False,
            "diffs": {"message": "Событие не найдено по правилу 2 из 3."},
            "debug": debug_meta,
        }

    portal_subdivision_name = None
    if subdivision_candidate:
        portal_subdivision_name = subdivision_candidate.get("candidate_name")
    if not portal_subdivision_name:
        portal_subdivision_name = attributes.subdivision_name

    portal_offenders = _portal_offenders(best_event)
    offenders_score, offenders_counts, offender_matches = match_offenders(
        attributes.offenders, portal_offenders, text
    )
    offenders_ok = (
        offenders_counts.get("matched", 0) == offenders_counts.get("portal_total", 0)
        and offenders_counts.get("dob_mismatch", 0) == 0
        and offenders_counts.get("missing_in_portal", 0) == 0
        and offenders_counts.get("missing_in_svodka", 0) == 0
    )
    type_ok = predicted_type and predicted_type == best_event.event.event_type
    article_ok = predicted_article and predicted_article == best_event.event.article_of_law
    if not best_flags:
        best_flags = {
            "date_ok": True,
            "subdivision_ok": True,
            "offenders_ok": offenders_ok,
        }
    best_flags = {
        **best_flags,
        "type_match": type_ok,
        "article_match": article_ok,
        "predicted_type": predicted_type,
        "predicted_article": predicted_article,
        "offenders_score": round(offenders_score * 100, 2),
        "offenders_counts": offenders_counts,
    }
    diffs = {}
    if not best_flags.get("type_match"):
        diffs["event_type"] = {
            "expected": best_flags.get("predicted_type"),
            "actual": best_event.event.event_type,
        }
    if not best_flags.get("article_match"):
        diffs["article_of_law"] = {
            "expected": best_flags.get("predicted_article"),
            "actual": best_event.event.article_of_law,
        }
    if not best_flags.get("subdivision_ok"):
        diffs["subdivision"] = {
            "expected": attributes.subdivision_name,
            "actual": portal_subdivision_name,
        }
    if not best_flags.get("offenders_ok"):
        diffs["offenders"] = {
            "expected": [offender_to_json(offender) for offender in attributes.offenders],
            "actual": [
                {
                    "full_name": portal_offender_fullname(offender),
                    "birth_year": offender.date_of_birth.year,
                    "birth_date": date_to_str(offender.date_of_birth),
                }
                for offender in portal_offenders
            ],
        }
    if not best_flags.get("date_ok"):
        diffs["date_time"] = {
            "expected": format_dt_dmy_hm(attributes.date_time),
            "actual": format_dt_dmy_hm(best_event.event.date_detection),
            "extracted": format_dt_dmy_hm(attributes.date_time),
            "portal": format_dt_dmy_hm(best_event.event.date_detection),
            "message": "Событие найдено по подразделению и нарушителям; дата/время отличаются",
            "delta_minutes": best_delta,
        }

    portal_offenders_payload = [
        _portal_offender_payload(offender) for offender in portal_offenders
    ]
    subdivision_match_percent = subdivision_confidence_percent
    unit_type_conflict = bool(
        subdivision_candidate.get("flags", {}).get("unit_type_conflict")
        if subdivision_candidate
        else False
    )

    return {
        "matched": True,
        "matched_event_id": str(best_event.event.event_id),
        "score_percent": round(offenders_score * 100, 2),
        "extracted_timestamp_display": format_dt_dmy_hm(attributes.date_time),
        "portal_timestamp_display": format_dt_dmy_hm(best_event.event.date_detection),
        "time_delta_minutes": best_delta,
        "offenders_score_percent": best_flags.get("offenders_score", 0),
        "offenders_counts": best_flags.get("offenders_counts")
        or {
            "svodka_total": len(attributes.offenders),
            "portal_total": len(portal_offenders_payload),
            "matched": offenders_counts.get("matched", 0),
            "dob_mismatch": offenders_counts.get("dob_mismatch", 0),
            "missing_in_portal": offenders_counts.get("missing_in_portal", 0),
            "missing_in_svodka": offenders_counts.get("missing_in_svodka", 0),
        },
        "subdivision_match_percent": round(subdivision_match_percent, 2),
        "time_found": attributes.time_found,
        "date_time_present": bool(attributes.date_time),
        "subdivision_locality_query": subdivision_candidate.get("query_locality")
        if subdivision_candidate
        else None,
        "subdivision_locality_candidate": subdivision_candidate.get("candidate_locality")
        if subdivision_candidate
        else None,
        "subdivision_locality_mismatch": bool(
            subdivision_candidate.get("locality_mismatch") if subdivision_candidate else False
        ),
        "subdivision_unit_type_conflict": unit_type_conflict,
        "extracted_subdivision_name": attributes.subdivision_name,
        "portal": {
            "timestamp": format_dt_dmy_hm(best_event.event.date_detection),
            "subdivision_name": portal_subdivision_name,
            "offenders": portal_offenders_payload,
            "event_type": best_event.event.event_type,
            "article_of_law": best_event.event.article_of_law,
        },
        "predicted": {
            "event_type": best_flags.get("predicted_type"),
            "article_of_law": best_flags.get("predicted_article"),
        },
        "offender_matches": offender_matches,
        "match_method": match_method,
        "time_mismatch": time_mismatch,
        "subdivision_mismatch": subdivision_mismatch,
        "diffs": diffs,
        "debug": debug_meta,
    }
