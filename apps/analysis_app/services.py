from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from functools import lru_cache
from uuid import UUID

from django.conf import settings
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
from .offenders.normalize import normalize_fio_to_nominative
from .offenders.matching import (
    match_offenders_with_details,
    mention_to_dict,
    portal_to_dict,
    split_mentions_by_employee_context,
)
from .offenders.types import OffenderMention, PortalOffender
from .staff_extractor import build_staff_from_excluded_mentions, extract_staff_mentions
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
MATCH_STAGE4_OFFENDER_LIMIT = 200
MATCH_STAGE4_OFFENDER_LIMIT_NO_DOB = 75

_DOB_FULL_DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
_DOB_YEAR_WITH_MARKER_RE = re.compile(r"\b\d{4}\b(?=\s*(?:г\s*\.?\s*р\.?|род\.?))", re.IGNORECASE)
_DOB_YEAR_IN_PARENS_RE = re.compile(
    r"\(\s*(\d{4})\s*(?:г\s*\.?\s*р\.?)?\s*\)",
    re.IGNORECASE,
)



def _normalize_surname(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.lower().replace("ё", "е")
    normalized = re.sub(r"[^а-яa-z0-9]", "", normalized)
    return normalized.strip()


def _staff_to_offender_payload(staff_item: dict) -> dict:
    surname = (staff_item or {}).get("surname") or ""
    initials = (staff_item or {}).get("initials") or ""
    initials_letters = re.findall(r"[А-ЯЁ]", initials)
    first_name = initials_letters[0] if len(initials_letters) > 0 else ""
    patronymic_name = initials_letters[1] if len(initials_letters) > 1 else ""
    full_name = " ".join(filter(None, [surname, first_name, patronymic_name]))
    return {
        "full_name": full_name,
        "second_name": surname,
        "first_name": first_name,
        "patronymic_name": patronymic_name,
        "birth_date": None,
        "birth_year": None,
        "source": "staff_override",
        "staff_override_is_offender": True,
    }


def _apply_staff_offender_override(attributes: ExtractedAttributes, portal_offenders: list[OffenderDTO]) -> list[dict]:
    db_surnames = {
        _normalize_surname(item.second_name)
        for item in portal_offenders
        if _normalize_surname(item.second_name)
    }
    if not db_surnames:
        return []

    kept_staff: list[dict] = []
    overridden: list[dict] = []
    existing_offender_keys = {
        (
            _normalize_surname(item.get("second_name")),
            (item.get("first_name") or "").lower(),
            (item.get("patronymic_name") or "").lower(),
        )
        for item in attributes.offenders
    }

    for staff_item in attributes.staff:
        surname_norm = _normalize_surname(staff_item.get("surname"))
        if surname_norm and surname_norm in db_surnames:
            offender_payload = _staff_to_offender_payload(staff_item)
            offender_key = (
                _normalize_surname(offender_payload.get("second_name")),
                (offender_payload.get("first_name") or "").lower(),
                (offender_payload.get("patronymic_name") or "").lower(),
            )
            if offender_key not in existing_offender_keys:
                overridden.append(offender_payload)
                existing_offender_keys.add(offender_key)
            continue
        kept_staff.append(staff_item)

    if overridden:
        attributes.offenders = [*attributes.offenders, *overridden]
    attributes.staff = kept_staff
    return overridden

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
    staff: list[dict] = field(default_factory=list)
    subdivision_candidates: list[dict] = field(default_factory=list)
    subdivision_span: list[int] | None = None
    selected_pu_id: uuid.UUID | None = None
    subdivision_candidates_total: int = 0
    subdivision_candidates_after_pu_filter: int = 0
    pu_filter_fallback_used: bool = False
    subdivision_query_source: str | None = None
    subdivision_query_text: str | None = None
    subdivision_accept_reason: str | None = None


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
    offenders_all = extract_offenders(text)
    for offender in offenders_all:
        second_name = offender.get("second_name") or ""
        first_name = offender.get("first_name") or ""
        patronymic_name = offender.get("patronymic_name") or ""
        normalized = normalize_fio_to_nominative(second_name, first_name, patronymic_name)
        offender["second_name"], offender["first_name"], offender["patronymic_name"] = normalized
        offender["full_name"] = " ".join(part for part in normalized if part)
    mentions = [_mention_from_dict(item) for item in offenders_all]
    eligible_mentions, excluded_mentions = split_mentions_by_employee_context(text, mentions)
    eligible_spans = {mention.span for mention in eligible_mentions}
    offenders = [
        offender
        for offender in offenders_all
        if tuple(offender.get("span") or ()) in eligible_spans
    ]
    for offender in offenders:
        span = offender.get("span")
        if not span or len(span) != 2:
            continue
        start, end = int(span[0]), int(span[1])
        window_end = min(len(text), end + 60)
        window = text[end:window_end]
        full_date_match = _DOB_FULL_DATE_RE.search(window)
        if full_date_match:
            offender["dob_span"] = (end + full_date_match.start(), end + full_date_match.end())
            offender["dob_kind"] = "date"
            continue
        year_match = _DOB_YEAR_WITH_MARKER_RE.search(window)
        if year_match:
            offender["dob_span"] = (end + year_match.start(), end + year_match.end())
            offender["dob_kind"] = "year"
            continue
        year_paren_match = _DOB_YEAR_IN_PARENS_RE.search(window)
        if year_paren_match:
            offender["dob_span"] = (
                end + year_paren_match.start(1),
                end + year_paren_match.end(1),
            )
            offender["dob_kind"] = "year"

    extracted_staff = extract_staff_mentions(text)
    excluded_staff = build_staff_from_excluded_mentions(excluded_mentions, text)
    staff: list[dict] = []
    seen_staff_keys: set[tuple[str, str, str]] = set()
    seen_staff_spans: list[tuple[int, int]] = []
    for item in [*extracted_staff, *excluded_staff]:
        item_dict = item.to_dict()
        span = item_dict.get("span")
        span_tuple = None
        if isinstance(span, tuple) and len(span) == 2:
            span_tuple = (int(span[0]), int(span[1]))
        elif isinstance(span, list) and len(span) == 2:
            span_tuple = (int(span[0]), int(span[1]))

        if span_tuple:
            overlaps = any(min(span_tuple[1], s[1]) - max(span_tuple[0], s[0]) > 0 for s in seen_staff_spans)
            if overlaps:
                continue

        key = (
            str(item_dict.get("surname") or "").lower().replace("ё", "е"),
            str(item_dict.get("initials") or "").lower().replace("ё", "е"),
            str(item_dict.get("rank_norm") or "").lower().replace("ё", "е"),
        )
        if key in seen_staff_keys:
            continue
        seen_staff_keys.add(key)
        if span_tuple:
            seen_staff_spans.append(span_tuple)
        staff.append(item_dict)
    subdivision_candidates, candidate_meta = match_subdivision(
        text,
        top_k=5,
        selected_pu_id=selected_pu_id,
    )
    best_candidate = subdivision_candidates[0] if subdivision_candidates else None
    accept_threshold = float(
        getattr(settings, "SUBDIVISION_ACCEPT_THRESHOLD", SUBDIVISION_MATCH_THRESHOLD)
    )
    accept_reason = None
    quoted_lexical_hit = bool(
        best_candidate
        and candidate_meta.get("subdivision_query_source") == "quoted_name"
        and best_candidate.get("lexical_hit")
    )
    if best_candidate and best_candidate["score"] >= accept_threshold:
        subdivision_id = best_candidate["portal_subdivision_id"]
        subdivision_name = best_candidate["name"]
        accept_reason = "semantic_threshold"
    elif best_candidate and quoted_lexical_hit:
        subdivision_id = best_candidate["portal_subdivision_id"]
        subdivision_name = best_candidate["name"]
        accept_reason = "lexical_quoted_hit"
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
        staff=staff,
        subdivision_name=subdivision_name,
        subdivision_candidates=subdivision_candidates,
        subdivision_span=subdivision_span,
        selected_pu_id=selected_pu_id,
        subdivision_candidates_total=candidate_meta.get("subdivision_candidates_total", 0),
        subdivision_candidates_after_pu_filter=candidate_meta.get(
            "subdivision_candidates_after_pu_filter", 0
        ),
        pu_filter_fallback_used=candidate_meta.get("pu_filter_fallback_used", False),
        subdivision_query_source=candidate_meta.get("subdivision_query_source"),
        subdivision_query_text=candidate_meta.get("subdivision_query_text"),
        subdivision_accept_reason=accept_reason,
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


def _extract_text_window(text: str, span: tuple[int, int] | None, width: int = 80) -> str:
    if not text:
        return ""
    if not isinstance(span, tuple) or len(span) != 2:
        start = 0
    else:
        start = max(0, min(len(text), int(span[1])))
    end = max(start, min(len(text), start + max(0, width)))
    return text[start:end]


def _is_year_only_dob_in_text(window: str, year: int) -> bool:
    if not window:
        return False
    year_str = str(year)
    if not re.search(rf"\b{re.escape(year_str)}\b", window):
        return False
    full_date_with_year = re.search(rf"\b\d{{2}}\.\d{{2}}\.{re.escape(year_str)}\b", window)
    return full_date_with_year is None


def _svodka_offender_birth_query(off: dict, text: str) -> tuple[date | None, int | None, str]:
    raw_birth_date = off.get("birth_date")
    birth_year = off.get("birth_year")
    span = off.get("span")
    if isinstance(span, list):
        span = tuple(span)
    if not isinstance(span, tuple) or len(span) != 2:
        span = None

    parsed_birth_year: int | None = None
    if birth_year is not None:
        try:
            parsed_birth_year = int(birth_year)
        except (TypeError, ValueError):
            parsed_birth_year = None

    birth_date = _candidate_birth_date({"birth_date": raw_birth_date})
    if not birth_date and isinstance(raw_birth_date, str):
        raw_value = raw_birth_date.strip()
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                birth_date = datetime.strptime(raw_value, fmt).date()
                break
            except ValueError:
                continue

    if parsed_birth_year is None and isinstance(birth_date, date):
        parsed_birth_year = birth_date.year

    if parsed_birth_year is None and not birth_date:
        return None, None, "none"

    window = _extract_text_window(text, span)

    if parsed_birth_year is not None and _is_year_only_dob_in_text(window, parsed_birth_year):
        return None, parsed_birth_year, "year"

    if isinstance(birth_date, date):
        is_jan_first = birth_date.month == 1 and birth_date.day == 1
        has_full_date_in_window = bool(re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", window))
        if is_jan_first and not has_full_date_in_window:
            return None, birth_date.year, "year"
        return birth_date, parsed_birth_year, "date"

    return None, parsed_birth_year, "year"


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


def _status_key_for_svodka_offender(offender: dict) -> str:
    span = offender.get("span")
    if isinstance(span, list) and len(span) == 2:
        return f"{int(span[0])}:{int(span[1])}"
    if isinstance(span, tuple) and len(span) == 2:
        return f"{int(span[0])}:{int(span[1])}"
    return ""


def _is_year_only_birth_date(value) -> bool:
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return False
    return isinstance(value, date) and value.month == 1 and value.day == 1


def _normalized_person_key(offender: dict) -> tuple[str, str, str, str]:
    offender = offender or {}
    second_name = _normalize_surname(offender.get("second_name"))
    first_name = _normalize_surname(offender.get("first_name"))
    patronymic_name = _normalize_surname(offender.get("patronymic_name"))
    full_name = _normalize_surname(offender.get("full_name"))
    return second_name, first_name, patronymic_name, full_name


def _normalized_birth_key(offender: dict) -> str:
    offender = offender or {}
    birth_date = offender.get("birth_date")
    if isinstance(birth_date, date):
        return birth_date.isoformat()
    if isinstance(birth_date, str):
        return birth_date
    birth_year = offender.get("birth_year")
    if birth_year is None:
        return ""
    return str(birth_year)


def _portal_offender_key(offender: dict) -> tuple[tuple[str, str, str, str], str]:
    return _normalized_person_key(offender), _normalized_birth_key(offender)


def _mention_offender_key(offender: dict) -> tuple[tuple[str, str, str, str], str]:
    return _normalized_person_key(offender), _normalized_birth_key(offender)


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

    covered_portal = {
        _portal_offender_key(pair.get("portal_offender") or {})
        for pair in matches["matched_pairs"]
    }
    covered_mentions = {
        _mention_offender_key(pair.get("svodka_offender") or {})
        for pair in matches["matched_pairs"]
    }
    covered_portal.update(
        _portal_offender_key(pair.get("portal_offender") or {})
        for pair in matches["dob_mismatch_pairs"]
    )
    covered_mentions.update(
        _mention_offender_key(pair.get("svodka_offender") or {})
        for pair in matches["dob_mismatch_pairs"]
    )

    matches["missing_in_svodka"] = [
        portal
        for portal in matches["missing_in_svodka"]
        if _portal_offender_key(portal) not in covered_portal
    ]
    matches["missing_in_portal"] = [
        mention
        for mention in matches["missing_in_portal"]
        if _mention_offender_key(mention) not in covered_mentions
    ]

    counts["missing_in_svodka"] = len(matches["missing_in_svodka"])
    counts["missing_in_portal"] = len(matches["missing_in_portal"])

    status_by_key: dict[str, str] = {}
    for missing in matches["missing_in_portal"]:
        key = _status_key_for_svodka_offender(missing)
        if key:
            status_by_key[key] = "err"

    for mismatch in matches["dob_mismatch_pairs"]:
        svodka_offender = mismatch.get("svodka_offender") or {}
        key = _status_key_for_svodka_offender(svodka_offender)
        if not key:
            continue
        if status_by_key.get(key) != "err":
            status_by_key[key] = "warn"

    for pair in matches["matched_pairs"]:
        svodka_offender = pair.get("svodka_offender") or {}
        portal_offender = pair.get("portal_offender") or {}
        key = _status_key_for_svodka_offender(svodka_offender)
        if not key:
            continue
        if status_by_key.get(key) in {"err", "warn"}:
            continue
        svodka_birth_date = svodka_offender.get("birth_date")
        portal_birth_date = portal_offender.get("birth_date")
        svodka_has_dob = bool(svodka_birth_date or svodka_offender.get("birth_year"))
        portal_has_dob = bool(portal_birth_date or portal_offender.get("birth_year"))
        both_missing_dob = not svodka_has_dob and not portal_has_dob
        exact_dob = bool(svodka_birth_date and portal_birth_date and svodka_birth_date == portal_birth_date)
        year_precision_mismatch = (
            bool(svodka_birth_date and portal_birth_date)
            and svodka_birth_date != portal_birth_date
            and (
                (_is_year_only_birth_date(svodka_birth_date) and not _is_year_only_birth_date(portal_birth_date))
                or (_is_year_only_birth_date(portal_birth_date) and not _is_year_only_birth_date(svodka_birth_date))
            )
        )
        discrepancy_text = str(pair.get("discrepancy") or "").lower()
        year_only_aligned = (
            bool(svodka_birth_date and portal_birth_date)
            and _is_year_only_birth_date(svodka_birth_date)
            and getattr(svodka_birth_date, "year", None) == getattr(portal_birth_date, "year", None)
        )
        only_dob_refined_discrepancy = discrepancy_text in {
            "dob уточнено",
            "др уточнено",
        }
        if pair.get("match_type") == "exact" and (exact_dob or both_missing_dob or year_only_aligned):
            status_by_key[key] = "ok"
        elif year_precision_mismatch and year_only_aligned:
            status_by_key[key] = "ok"
        elif only_dob_refined_discrepancy:
            status_by_key[key] = "ok"
        else:
            status_by_key[key] = "warn"

    matches["svodka_status_by_span"] = status_by_key
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
    limit: int = MATCH_STAGE4_OFFENDER_LIMIT,
) -> tuple[list[EventDTO], list[dict]]:
    gateway = get_portal_gateway()
    stage4_events: dict[str, EventDTO] = {}
    debug_queries: list[dict] = []

    mention_candidates = [(_mention_from_dict(item), item) for item in attributes.offenders]
    mentions = [mention for mention, _ in mention_candidates]
    eligible_mentions, _ = split_mentions_by_employee_context(text, mentions)
    eligible_spans = {mention.span for mention in eligible_mentions if mention.span}
    offenders = [
        offender
        for mention, offender in mention_candidates
        if mention.span and mention.span in eligible_spans
    ]

    for offender in offenders:
        surname = (offender.get("second_name") or "").strip()
        if not surname:
            full_name = (offender.get("full_name") or "").strip()
            if full_name:
                surname = full_name.split()[0]
        if not surname:
            continue

        birth_date, birth_year, dob_mode = _svodka_offender_birth_query(offender, text)
        subdivision_id = attributes.subdivision_id if subdivision_confidence_high else None
        query_limit = limit
        warnings: list[str] = []
        if not birth_date and not birth_year:
            query_limit = min(limit, MATCH_STAGE4_OFFENDER_LIMIT_NO_DOB)
            warnings.append("dob_missing_limit_reduced")
            logger.warning(
                "Stage4 offender fallback without DOB for surname '%s'; using bounded limit=%s",
                surname,
                query_limit,
            )

        subdivision_events: list[EventDTO] = []
        offender_only_events: list[EventDTO] = []
        query_path = "offender_only"

        if subdivision_id:
            subdivision_events = gateway.search_events_by_offender(
                second_name=surname,
                birth_date=birth_date,
                birth_year=birth_year,
                subdivision_id=subdivision_id,
                limit=query_limit,
            )
            query_path = "offender_subdivision"

        if not subdivision_events:
            offender_only_events = gateway.search_events_by_offender(
                second_name=surname,
                birth_date=birth_date,
                birth_year=birth_year,
                subdivision_id=None,
                limit=query_limit,
            )
            if subdivision_id:
                query_path = "offender_subdivision_then_only"

        events = subdivision_events or offender_only_events
        debug_queries.append(
            {
                "stage": "stage4_offenders",
                "method": "search_events_by_offender",
                "stage4_path": query_path,
                "surname": surname,
                "offender_query_name": (offender.get("full_name") or surname),
                "dob_mode": dob_mode,
                "birth_date": date_to_str(birth_date) if birth_date else None,
                "used_birth_date": bool(birth_date),
                "birth_year": birth_year,
                "subdivision_ids": [str(subdivision_id)] if subdivision_id else [],
                "subdivision_ids_count": 1 if subdivision_id else 0,
                "stage4_rows_subdivision": len(subdivision_events),
                "stage4_rows_only": len(offender_only_events),
                "rows": len(events),
                "limit": query_limit,
                "warnings": warnings,
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
    accept_threshold = float(
        getattr(settings, "SUBDIVISION_ACCEPT_THRESHOLD", SUBDIVISION_MATCH_THRESHOLD)
    )
    subdivision_confidence_high = bool(
        subdivision_candidate.get("score", 0) >= accept_threshold or attributes.selected_pu_id
    )

    if not attributes.date_time:
        return [], {
            "stages": [],
            "stage_queries": [],
            "subdivision_confidence_high": subdivision_confidence_high,
            "stage1_best_score": 0,
            "score_threshold": score_threshold,
            "stage4_used": False,
            "pre_stage4_best_score": 0,
            "pre_stage4_candidate_count": 0,
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
    stage4_executed = False
    stage4_path = None
    stage4_rows_subdivision = 0
    stage4_rows_only = 0
    best_score = scored[0]["flags_true"] if scored else 0
    selected_by_pre_stage4 = bool(scored and best_score >= score_threshold)
    should_run_stage4 = bool(
        attributes.offenders
        and (
            not scored
            or not selected_by_pre_stage4
            or best_score < score_threshold
        )
    )
    if should_run_stage4:
        stage4_executed = True
        stage4_events, stage4_queries = _stage4_candidates_by_offenders(
            attributes, text=text, subdivision_confidence_high=subdivision_confidence_high
        )
        stage_queries.extend(stage4_queries)
        if stage4_queries:
            row_subdivision = sum(item.get("stage4_rows_subdivision", 0) for item in stage4_queries)
            row_only = sum(item.get("stage4_rows_only", 0) for item in stage4_queries)
            stage4_rows_subdivision = row_subdivision
            stage4_rows_only = row_only
            paths = {item.get("stage4_path") for item in stage4_queries}
            if "offender_subdivision_then_only" in paths:
                stage4_path = "offender_subdivision_then_only"
            elif "offender_subdivision" in paths:
                stage4_path = "offender_subdivision"
            elif "offender_only" in paths:
                stage4_path = "offender_only"
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
        "stage4_executed": stage4_executed,
        "stage4_path": stage4_path,
        "stage4_rows_subdivision": stage4_rows_subdivision,
        "stage4_rows_only": stage4_rows_only,
        "pre_stage4_best_score": best_score,
        "pre_stage4_candidate_count": len(hydrated),
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
        "method_unresolved": match_method is None,
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
        "pre_stage4_best_score": candidate_meta.get("pre_stage4_best_score", 0),
        "pre_stage4_candidate_count": candidate_meta.get("pre_stage4_candidate_count", 0),
        "score_threshold": candidate_meta.get("score_threshold", MATCH_STAGE_MIN_SCORE_THRESHOLD),
        "subdivision_confidence_high": candidate_meta.get("subdivision_confidence_high", False),
        "stage4_used": candidate_meta.get("stage4_used", False),
        "stage4_executed": candidate_meta.get("stage4_executed", False),
        "stage4_path": candidate_meta.get("stage4_path"),
        "stage4_rows_subdivision": candidate_meta.get("stage4_rows_subdivision", 0),
        "stage4_rows_only": candidate_meta.get("stage4_rows_only", 0),
        "subdivision_query_source": attributes.subdivision_query_source,
        "subdivision_query_text": attributes.subdivision_query_text,
        "subdivision_accept_reason": attributes.subdivision_accept_reason,
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
    overridden_staff_offenders = _apply_staff_offender_override(attributes, portal_offenders)
    offenders_score, offenders_counts, offender_matches = match_offenders(
        attributes.offenders, portal_offenders, text
    )
    if overridden_staff_offenders:
        offender_matches["staff_overridden_to_offenders"] = overridden_staff_offenders
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
