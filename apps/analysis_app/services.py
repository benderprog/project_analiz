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
MATCH_STAGE_FALLBACK_LIMIT = 500
MATCH_STAGE_FALLBACK_DAYS = 7
MATCH_STAGE_MIN_SCORE_THRESHOLD = 2

def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


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
    debug_stage_log: list[dict] | None = None,
    stage_name: str | None = None,
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
    method_name = "search_events_by_subdivision_time" if subdivision_id else "search_events_by_time"
    if subdivision_id:
        events = gateway.search_events_by_subdivision_time(subdivision_id, date_from, date_to, limit)
    else:
        events = gateway.search_events_by_time(date_from, date_to, limit)

    if debug_stage_log is not None:
        debug_stage_log.append(
            {
                "stage": stage_name,
                "method": method_name,
                "extracted_dt": format_dt_dmy_hm(target_utc),
                "time_from": date_from.isoformat(),
                "time_to": date_to.isoformat(),
                "subdivision_ids": [str(subdivision_id)] if subdivision_id else [],
                "rows": len(events),
            }
        )

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


def _score_event_candidate(event: HydratedEvent, attributes: ExtractedAttributes) -> dict:
    target_utc = _to_utc(attributes.date_time) if attributes.date_time else None
    event_utc = _to_utc(event.event.date_detection)
    delta_minutes = None
    if target_utc and event_utc:
        delta_minutes = int(abs(event_utc - target_utc).total_seconds() / 60)

    date_ok = bool(delta_minutes is not None and delta_minutes <= MATCH_TIME_DELTA_MINUTES)
    subdivision_ok = bool(
        attributes.subdivision_id and str(event.event.subdivision_id) == str(attributes.subdivision_id)
    )

    overlap = 0
    if attributes.offenders:
        _, counts, _ = match_offenders(attributes.offenders, _portal_offenders(event), text="")
        overlap = counts.get("matched", 0)
    offenders_ok = overlap >= 1

    true_flags = int(date_ok) + int(subdivision_ok) + int(offenders_ok)
    return {
        "event": event,
        "delta_minutes": delta_minutes,
        "overlap": overlap,
        "date_ok": date_ok,
        "subdivision_ok": subdivision_ok,
        "offenders_ok": offenders_ok,
        "flags_true": true_flags,
    }


def _stage4_candidates_by_offenders(
    attributes: ExtractedAttributes,
    text: str,
    subdivision_confidence_high: bool,
    limit: int = 200,
) -> tuple[list[EventDTO], list[dict]]:
    gateway = get_portal_gateway()
    stage4_events: dict[str, EventDTO] = {}
    debug_queries: list[dict] = []

    mentions = [_mention_from_dict(item) for item in attributes.offenders]
    eligible_mentions, _ = split_mentions_by_employee_context(text, mentions)
    offenders = [
        {
            "second_name": mention.second_name,
            "full_name": mention.full_name,
            "birth_date": mention.birth_date,
            "birth_year": mention.birth_year,
        }
        for mention in eligible_mentions
    ]

    for offender in offenders:
        surname = (offender.get("second_name") or "").strip()
        if not surname:
            full_name = (offender.get("full_name") or "").strip()
            if full_name:
                surname = full_name.split()[0]
        if not surname:
            continue

        birth_date = offender.get("birth_date") or _candidate_birth_date(offender)
        birth_year = offender.get("birth_year")
        subdivision_id = attributes.subdivision_id if subdivision_confidence_high else None
        method_name = (
            "search_events_by_offender_subdivision"
            if subdivision_id
            else "search_events_by_offender"
        )
        events = gateway.search_events_by_offender(
            second_name=surname,
            birth_date=birth_date,
            birth_year=birth_year,
            subdivision_id=subdivision_id,
            limit=limit,
        )
        debug_queries.append(
            {
                "stage": "stage4_offenders",
                "method": method_name,
                "surname": surname,
                "birth_date": date_to_str(birth_date) if birth_date else None,
                "birth_year": birth_year,
                "subdivision_ids": [str(subdivision_id)] if subdivision_id else [],
                "rows": len(events),
            }
        )
        for event in events:
            stage4_events[str(event.event_id)] = event

    return list(stage4_events.values()), debug_queries


def get_event_candidates(attributes: ExtractedAttributes, text: str = "", config: dict | None = None) -> tuple[list[dict], dict]:
    config = config or {}
    stage_delta_minutes = int(config.get("delta_minutes", MATCH_TIME_DELTA_MINUTES))
    stage_two_days = int(config.get("stage_two_days", 1))
    stage_three_days = int(config.get("stage_three_days", MATCH_STAGE_FALLBACK_DAYS))
    score_threshold = int(config.get("min_score_threshold", MATCH_STAGE_MIN_SCORE_THRESHOLD))

    subdivision_candidate = attributes.subdivision_candidates[0] if attributes.subdivision_candidates else {}
    subdivision_confidence_high = bool(
        subdivision_candidate.get("lexical_strength") == "strong" or attributes.selected_pu_id
    )

    if not attributes.date_time:
        return [], {
            "stages": [],
            "stage_queries": [],
            "subdivision_confidence_high": subdivision_confidence_high,
            "stage1_best_score": 0,
            "score_threshold": score_threshold,
        }

    stage_events: dict[str, EventDTO] = {}
    stages: list[dict] = []
    stage_queries: list[dict] = []

    def _collect(stage_name: str, events: list[EventDTO]) -> None:
        stages.append({"stage": stage_name, "count": len(events)})
        for event in events:
            stage_events[str(event.event_id)] = event

    stage1_subdivision = []
    if attributes.subdivision_id:
        stage1_subdivision = _get_events_for_window(
            target_dt=attributes.date_time,
            minutes_window=stage_delta_minutes,
            subdivision_id=attributes.subdivision_id,
            limit=MATCH_STAGE_SUBDIVISION_LIMIT,
            debug_stage_log=stage_queries,
            stage_name="stage1_subdivision_time",
        )
        _collect("stage1_subdivision_time", stage1_subdivision)

    stage1_time = _get_events_for_window(
        target_dt=attributes.date_time,
        minutes_window=stage_delta_minutes,
        limit=MATCH_STAGE_TIME_LIMIT,
        debug_stage_log=stage_queries,
        stage_name="stage1_time",
    )
    _collect("stage1_time", stage1_time)

    hydrated_stage1 = _hydrate_events_with_offenders(list(stage_events.values()))
    stage1_scores = [_score_event_candidate(event, attributes) for event in hydrated_stage1]
    stage1_best_score = max((item["flags_true"] for item in stage1_scores), default=0)

    if not stage_events or stage1_best_score < score_threshold:
        if subdivision_confidence_high and attributes.subdivision_id:
            stage2_subdivision = _get_events_for_window(
                target_dt=attributes.date_time,
                days_window=stage_two_days,
                subdivision_id=attributes.subdivision_id,
                limit=MATCH_STAGE_FALLBACK_LIMIT,
                debug_stage_log=stage_queries,
                stage_name="stage2_subdivision_time",
            )
            _collect("stage2_subdivision_time", stage2_subdivision)

        stage2_time = _get_events_for_window(
            target_dt=attributes.date_time,
            days_window=stage_two_days,
            limit=MATCH_STAGE_FALLBACK_LIMIT,
            debug_stage_log=stage_queries,
            stage_name="stage2_time",
        )
        _collect("stage2_time", stage2_time)

        if subdivision_confidence_high and attributes.subdivision_id:
            stage3_subdivision = _get_events_for_window(
                target_dt=attributes.date_time,
                days_window=stage_three_days,
                subdivision_id=attributes.subdivision_id,
                limit=MATCH_STAGE_FALLBACK_LIMIT,
                debug_stage_log=stage_queries,
                stage_name="stage3_subdivision_time",
            )
            _collect("stage3_subdivision_time", stage3_subdivision)

        stage3_time = _get_events_for_window(
            target_dt=attributes.date_time,
            days_window=stage_three_days,
            limit=MATCH_STAGE_FALLBACK_LIMIT,
            debug_stage_log=stage_queries,
            stage_name="stage3_time",
        )
        _collect("stage3_time", stage3_time)

    hydrated = _hydrate_events_with_offenders(list(stage_events.values()))
    scored = [_score_event_candidate(event, attributes) for event in hydrated]
    scored.sort(
        key=lambda item: (
            -item["flags_true"],
            -(1 if item["subdivision_ok"] else 0),
            -(1 if item["offenders_ok"] else 0),
            item["delta_minutes"] if item["delta_minutes"] is not None else 10**9,
            -item["overlap"],
        )
    )

    stage4_used = False
    best_score = scored[0]["flags_true"] if scored else 0
    if attributes.offenders and (not scored or best_score < score_threshold):
        stage4_events, stage4_queries = _stage4_candidates_by_offenders(
            attributes, text=text, subdivision_confidence_high=subdivision_confidence_high
        )
        stage_queries.extend(stage4_queries)
        stages.append({"stage": "stage4_offenders", "count": len(stage4_events)})
        if stage4_events:
            stage4_used = True
            hydrated_stage4 = _hydrate_events_with_offenders(stage4_events)
            scored = [_score_event_candidate(event, attributes) for event in hydrated_stage4]
            scored.sort(
                key=lambda item: (
                    -item["flags_true"],
                    -(1 if item["subdivision_ok"] else 0),
                    -(1 if item["offenders_ok"] else 0),
                    item["delta_minutes"] if item["delta_minutes"] is not None else 10**9,
                    -item["overlap"],
                )
            )

    return scored, {
        "stages": stages,
        "stage_queries": stage_queries,
        "subdivision_confidence_high": subdivision_confidence_high,
        "stage1_best_score": stage1_best_score,
        "score_threshold": score_threshold,
        "stage4_used": stage4_used,
    }


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

    scored_candidates, candidate_meta = get_event_candidates(attributes, text=text)

    best_candidate = scored_candidates[0] if scored_candidates else None
    best_event = best_candidate["event"] if best_candidate else None
    best_delta = best_candidate.get("delta_minutes") if best_candidate else None

    match_method = None
    best_flags: dict = {}
    time_mismatch = False
    subdivision_mismatch = False

    if best_candidate and best_candidate["flags_true"] >= 2:
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

    stage_rows = {item.get("stage"): item.get("count", 0) for item in candidate_meta.get("stages", [])}
    debug_meta = {
        "candidates_total": len(scored_candidates),
        "subdivision_candidates_total": attributes.subdivision_candidates_total,
        "subdivision_candidates_after_pu_filter": (
            attributes.subdivision_candidates_after_pu_filter
        ),
        "pu_filter_fallback_used": attributes.pu_filter_fallback_used,
        "selected_pu_id": str(attributes.selected_pu_id)
        if attributes.selected_pu_id
        else None,
        "chosen_method": match_method,
        "candidate_stages": candidate_meta.get("stages", []),
        "candidate_queries": candidate_meta.get("stage_queries", []),
        "stage1_subdivision_time": stage_rows.get("stage1_subdivision_time", 0),
        "stage1_time": stage_rows.get("stage1_time", 0),
        "stage2_subdivision_time": stage_rows.get("stage2_subdivision_time", 0),
        "stage2_time": stage_rows.get("stage2_time", 0),
        "stage3_subdivision_time": stage_rows.get("stage3_subdivision_time", 0),
        "stage3_time": stage_rows.get("stage3_time", 0),
        "stage4_offenders": stage_rows.get("stage4_offenders", 0),
        "stage1_best_score": candidate_meta.get("stage1_best_score", 0),
        "score_threshold": candidate_meta.get("score_threshold", MATCH_STAGE_MIN_SCORE_THRESHOLD),
        "subdivision_confidence_high": candidate_meta.get("subdivision_confidence_high", False),
        "stage4_used": candidate_meta.get("stage4_used", False),
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
    if time_mismatch and best_delta is not None:
        diffs["date_time"] = {
            "message": "Событие найдено по подразделению и нарушителям; дата/время отличаются",
            "delta_minutes": best_delta,
            "extracted": format_dt_dmy_hm(attributes.date_time),
            "portal": format_dt_dmy_hm(best_event.event.date_detection),
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
