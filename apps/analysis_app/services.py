from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from uuid import UUID

from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from apps.classifier.models import EventTypePattern
from apps.analysis_app.utils.dt_display import format_dt_dmy_hm, to_local_naive
from apps.analysis_app.utils.json_safe import date_to_str, offender_to_json
from apps.analysis_app.utils.offender_format import (
    normalize_name_key,
    portal_offender_fullname,
    svodka_offender_fullname,
)
from apps.portaldb.gateway.dtos import EventDTO, OffenderDTO
from apps.portaldb.gateway.factory import get_portal_gateway

from .offender_extractor import extract_offenders, normalize_name_part
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

def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.utc)
    return dt.astimezone(timezone.utc)


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


def _offender_similarity(text_a: str, text_b: str) -> float:
    try:
        model = get_sentence_model()
    except RuntimeError as exc:
        logger.info("Semantic model unavailable, falling back to sequence match: %s", exc)
        model = None
    if model:
        embeddings = model.encode([text_a, text_b])
        similarity = float(
            (embeddings[0] @ embeddings[1])
            / (sum(embeddings[0] ** 2) ** 0.5 * sum(embeddings[1] ** 2) ** 0.5)
        )
        return similarity
    return SequenceMatcher(None, text_a, text_b).ratio()


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


def _extract_name_parts(offender: dict) -> tuple[str, str, str]:
    last = normalize_name_part(offender.get("second_name"))
    first = normalize_name_part(offender.get("first_name"))
    middle = normalize_name_part(offender.get("patronymic_name"))
    if not last or not first:
        full_name = offender.get("full_name") or ""
        parts = [normalize_name_part(part) for part in full_name.split()]
        if len(parts) >= 2:
            last = last or parts[0]
            first = first or parts[1]
            if len(parts) >= 3:
                middle = middle or parts[2]
    return last, first, middle


def _name_matches(candidate: dict, offender: OffenderDTO) -> bool:
    candidate_key = normalize_name_key(svodka_offender_fullname(candidate))
    portal_key = normalize_name_key(portal_offender_fullname(offender))
    if not candidate_key or not portal_key:
        return False
    return candidate_key == portal_key


def _portal_offender_payload(offender: OffenderDTO) -> dict:
    birth_date = offender.date_of_birth
    if birth_date == DEFAULT_DOB:
        birth_date = None
    return {
        "full_name": portal_offender_fullname(offender),
        "second_name": offender.second_name,
        "first_name": offender.first_name,
        "patronymic_name": offender.patronymic_name,
        "birth_year": birth_date.year if birth_date else None,
        "birth_date": date_to_str(birth_date),
    }


def _portal_offenders(event: HydratedEvent) -> list[OffenderDTO]:
    return list(event.offenders)


def match_offenders(
    extracted: list[dict], portal_offenders: list[OffenderDTO]
) -> tuple[float, dict, dict]:
    counts = {
        "matched": 0,
        "portal_total": len(portal_offenders),
        "svodka_total": len(extracted),
        "dob_mismatch": 0,
        "missing_in_portal": 0,
        "missing_in_svodka": 0,
    }

    def is_year_only(dob: date | None) -> bool:
        return bool(dob and dob != DEFAULT_DOB and dob.month == 1 and dob.day == 1)

    def is_full_dob(dob: date | None) -> bool:
        return bool(dob and dob != DEFAULT_DOB and not is_year_only(dob))

    def offender_key_from_candidate(candidate: dict) -> str:
        return normalize_name_key(svodka_offender_fullname(candidate))

    def offender_key_from_portal(offender: OffenderDTO) -> str:
        return normalize_name_key(portal_offender_fullname(offender))

    candidate_records = []
    for idx, candidate in enumerate(extracted):
        dob = _candidate_birth_date(candidate)
        if dob == DEFAULT_DOB:
            dob = None
        candidate_records.append(
            {
                "idx": idx,
                "offender": candidate,
                "key": offender_key_from_candidate(candidate) or f"__missing_candidate_{idx}",
                "dob": dob,
            }
        )

    portal_records = []
    for idx, offender in enumerate(portal_offenders):
        dob = offender.date_of_birth
        if dob == DEFAULT_DOB:
            dob = None
        portal_records.append(
            {
                "idx": idx,
                "offender": offender,
                "key": offender_key_from_portal(offender) or f"__missing_portal_{idx}",
                "dob": dob,
            }
        )

    candidates_by_key: dict[str, list[dict]] = {}
    portals_by_key: dict[str, list[dict]] = {}
    for candidate in candidate_records:
        candidates_by_key.setdefault(candidate["key"], []).append(candidate)
    for portal in portal_records:
        portals_by_key.setdefault(portal["key"], []).append(portal)

    matched_pairs = []
    dob_mismatch_pairs = []
    used_candidates: set[int] = set()
    used_portals: set[int] = set()

    def mark_match(candidate: dict, portal: dict) -> None:
        used_candidates.add(candidate["idx"])
        used_portals.add(portal["idx"])
        matched_pairs.append(
            {
                "svodka_offender": offender_to_json(candidate["offender"]),
                "portal_offender": _portal_offender_payload(portal["offender"]),
            }
        )

    def mark_mismatch(candidate: dict, portal: dict) -> None:
        used_candidates.add(candidate["idx"])
        used_portals.add(portal["idx"])
        dob_mismatch_pairs.append(
            {
                "svodka_offender": offender_to_json(candidate["offender"]),
                "portal_offender": _portal_offender_payload(portal["offender"]),
                "svodka_dob": date_to_str(candidate["dob"]),
                "portal_dob": date_to_str(portal["dob"]),
            }
        )

    for key in set(candidates_by_key) | set(portals_by_key):
        candidates = [c for c in candidates_by_key.get(key, []) if c["idx"] not in used_candidates]
        portals = [p for p in portals_by_key.get(key, []) if p["idx"] not in used_portals]
        if not candidates or not portals:
            continue

        for portal in portals:
            if portal["idx"] in used_portals:
                continue
            for candidate in candidates:
                if candidate["idx"] in used_candidates:
                    continue
                if candidate["dob"] and portal["dob"] and candidate["dob"] == portal["dob"]:
                    mark_match(candidate, portal)
                    break

        for portal in portals:
            if portal["idx"] in used_portals:
                continue
            for candidate in candidates:
                if candidate["idx"] in used_candidates:
                    continue
                if dob_matches(candidate["dob"], portal["dob"]):
                    mark_match(candidate, portal)
                    break

    for key in set(candidates_by_key) | set(portals_by_key):
        candidates = [c for c in candidates_by_key.get(key, []) if c["idx"] not in used_candidates]
        portals = [p for p in portals_by_key.get(key, []) if p["idx"] not in used_portals]
        if not candidates or not portals:
            continue
        for portal in portals:
            if portal["idx"] in used_portals:
                continue
            if not is_full_dob(portal["dob"]):
                continue
            for candidate in candidates:
                if candidate["idx"] in used_candidates:
                    continue
                if not is_full_dob(candidate["dob"]):
                    continue
                if candidate["dob"] != portal["dob"]:
                    mark_mismatch(candidate, portal)
                    break

    missing_in_portal = [
        offender_to_json(record["offender"])
        for record in candidate_records
        if record["idx"] not in used_candidates
    ]
    missing_in_svodka = [
        _portal_offender_payload(record["offender"])
        for record in portal_records
        if record["idx"] not in used_portals
    ]

    counts["matched"] = len(matched_pairs)
    counts["dob_mismatch"] = len(dob_mismatch_pairs)
    counts["missing_in_portal"] = len(missing_in_portal)
    counts["missing_in_svodka"] = len(missing_in_svodka)

    score = counts["matched"] / counts["portal_total"] if counts["portal_total"] else 0.0

    return (
        score,
        counts,
        {
            "matched_pairs": matched_pairs,
            "dob_mismatch_pairs": dob_mismatch_pairs,
            "missing_in_portal": missing_in_portal,
            "missing_in_svodka": missing_in_svodka,
        },
    )




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


def _build_subdivision_offender_candidates(
    subdivision_id: str, extracted_offenders: list[dict], target_dt: datetime | None
) -> list[dict]:
    gateway = get_portal_gateway()
    anchor_dt = _to_utc(target_dt) or timezone.now().astimezone(timezone.utc)
    events = gateway.search_events_by_time(
        anchor_dt - timedelta(days=36500),
        anchor_dt + timedelta(days=36500),
        MATCH_STAGE_SUBDIVISION_LIMIT,
    )
    candidates = [
        EventDTO(
            event_id=e.event_id,
            date_detection=e.date_detection,
            subdivision_id=e.subdivision_id,
            event_type=e.event_type,
            article_of_law=e.article_of_law,
        )
        for e in events
        if str(e.subdivision_id) == str(subdivision_id)
    ]
    candidates = _hydrate_events_with_offenders(candidates)
    target_utc = _to_utc(target_dt) if target_dt else None
    if not candidates or not extracted_offenders:
        return []
    scored_candidates = []
    for event in candidates:
        _, counts, _ = match_offenders(extracted_offenders, _portal_offenders(event))
        overlap = counts["matched"]
        if overlap < 1:
            continue
        delta_minutes = None
        if target_utc:
            event_dt_utc = _to_utc(event.event.date_detection)
            if event_dt_utc:
                delta_minutes = int(abs(event_dt_utc - target_utc).total_seconds() / 60)
        scored_candidates.append(
            {"event": event, "overlap": overlap, "delta_minutes": delta_minutes}
        )
    return scored_candidates


def _build_time_offender_candidates(
    target_dt: datetime, extracted_offenders: list[dict]
) -> list[dict]:
    target_utc = _to_utc(target_dt)
    if target_utc is None:
        return []
    date_from = target_utc - timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    date_to = target_utc + timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    gateway = get_portal_gateway()
    events = gateway.search_events_by_time(date_from, date_to, MATCH_STAGE_TIME_LIMIT)
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
    candidates = _hydrate_events_with_offenders(candidates)
    target_utc = _to_utc(target_dt) if target_dt else None
    if not candidates or not extracted_offenders:
        return []
    scored_candidates = []
    for event in candidates:
        _, counts, _ = match_offenders(extracted_offenders, _portal_offenders(event))
        overlap = counts["matched"]
        if overlap < 1:
            continue
        event_dt_utc = _to_utc(event.event.date_detection)
        if not event_dt_utc:
            continue
        delta_minutes = int(abs(event_dt_utc - target_utc).total_seconds() / 60)
        scored_candidates.append(
            {"event": event, "overlap": overlap, "delta_minutes": delta_minutes}
        )
    return scored_candidates


def _build_subdivision_time_candidates(
    subdivision_id: str, target_dt: datetime
) -> list[dict]:
    target_utc = _to_utc(target_dt)
    if target_utc is None:
        return []
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
    scored_candidates = []
    for event in candidates:
        event_dt_utc = _to_utc(event.date_detection)
        if not event_dt_utc:
            continue
        delta_minutes = int(abs(event_dt_utc - target_utc).total_seconds() / 60)
        if delta_minutes <= MATCH_TIME_DELTA_MINUTES:
            scored_candidates.append({"event": event, "delta_minutes": delta_minutes})
    return scored_candidates


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

    if attributes.date_time and attributes.subdivision_id:
        candidates_a = _build_subdivision_time_candidates(
            attributes.subdivision_id,
            attributes.date_time,
        )
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

    def _best_by_overlap(candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda candidate: (
                -candidate["overlap"],
                candidate["delta_minutes"] if candidate["delta_minutes"] is not None else 10**9,
            ),
        )

    def _best_by_delta(candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        return min(candidates, key=lambda candidate: candidate["delta_minutes"])

    best_candidate = None
    match_method = None
    best_delta = None
    best_flags: dict = {}
    time_mismatch = False
    subdivision_mismatch = False

    if candidates_a:
        best_candidate = _best_by_delta(candidates_a)
        match_method = "subdivision+time"
    elif candidates_c:
        best_candidate = _best_by_overlap(candidates_c)
        match_method = "time+offenders"
        subdivision_mismatch = True
        best_flags = {
            "date_ok": True,
            "subdivision_ok": False,
            "offenders_ok": True,
        }
    elif candidates_b:
        best_candidate = _best_by_overlap(candidates_b)
        match_method = "subdivision+offenders"
        time_mismatch = True
        best_flags = {
            "date_ok": False,
            "subdivision_ok": True,
            "offenders_ok": True,
        }

    best_event = None
    if best_candidate:
        best_event = best_candidate["event"]
        best_delta = best_candidate.get("delta_minutes")
        if match_method == "subdivision+time":
            hydrated = _hydrate_events_with_offenders([best_event])
            best_event = hydrated[0] if hydrated else None

    top_overlap_c = max((item["overlap"] for item in candidates_c), default=0)
    top_overlap_b = max((item["overlap"] for item in candidates_b), default=0)
    debug_meta = {
        "candidates_A": len(candidates_a),
        "candidates_C": len(candidates_c),
        "candidates_B": len(candidates_b),
        "subdivision_candidates_total": attributes.subdivision_candidates_total,
        "subdivision_candidates_after_pu_filter": (
            attributes.subdivision_candidates_after_pu_filter
        ),
        "pu_filter_fallback_used": attributes.pu_filter_fallback_used,
        "selected_pu_id": str(attributes.selected_pu_id)
        if attributes.selected_pu_id
        else None,
        "top_overlaps": {
            "stage_c": top_overlap_c,
            "stage_b": top_overlap_b,
        },
        "chosen_method": match_method,
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
        attributes.offenders, portal_offenders
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
