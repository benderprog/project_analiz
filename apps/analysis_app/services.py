from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from functools import lru_cache

from django.db.models import Prefetch
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from apps.classifier.models import EventTypePattern
from apps.analysis_app.utils.dt_display import format_local_naive, to_local_naive
from apps.analysis_app.utils.json_safe import date_to_str, offender_to_json
from apps.portaldb import repository
from apps.portaldb.models import Event, Offender

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


@dataclass
class ExtractedAttributes:
    date_time: datetime | None
    time_found: bool
    subdivision_id: str | None
    offenders: list[dict]
    subdivision_name: str | None
    subdivision_candidates: list[dict] = field(default_factory=list)
    subdivision_span: list[int] | None = None


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
        aware_dt = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        return aware_dt, time_found

    extractor = DatesExtractor(_get_morph())
    matches = list(extractor(text))
    if not matches:
        return None, False
    dt = _fact_to_datetime(matches[0].fact)
    if dt is None:
        return None, False
    time_found = dt.time() != time(0, 0)
    aware_dt = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
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


def extract_attributes(text: str) -> ExtractedAttributes:
    """Extract event attributes from a paragraph."""
    date_time, time_found = _extract_datetime(text)
    offenders = extract_offenders(text)
    subdivision_candidates = match_subdivision(text, top_k=5)
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


def _name_matches(candidate: dict, offender: Offender) -> bool:
    candidate_last, candidate_first, candidate_middle = _extract_name_parts(candidate)
    portal_last = normalize_name_part(offender.second_name)
    portal_first = normalize_name_part(offender.first_name)
    portal_middle = normalize_name_part(offender.patronymic_name)
    if not candidate_last or not candidate_first:
        return False
    if candidate_last != portal_last or candidate_first != portal_first:
        return False
    if candidate_middle and portal_middle and candidate_middle != portal_middle:
        return False
    return True


def _portal_offender_payload(offender: Offender) -> dict:
    birth_date = offender.date_of_birth
    if birth_date == DEFAULT_DOB:
        birth_date = None
    return {
        "full_name": " ".join(
            filter(None, [offender.second_name, offender.first_name, offender.patronymic_name])
        ),
        "birth_year": birth_date.year if birth_date else None,
        "birth_date": date_to_str(birth_date),
    }


def _build_offender_matches(extracted: list[dict], portal_offenders: list[Offender]) -> list[dict]:
    matches = []
    for offender in portal_offenders:
        for candidate in extracted:
            name_match = _name_matches(candidate, offender)
            candidate_birth_date = _candidate_birth_date(candidate)
            dob_match = bool(candidate_birth_date and dob_matches(candidate_birth_date, offender.date_of_birth))
            if name_match or dob_match:
                matches.append(
                    {
                        "svodka_offender": offender_to_json(candidate),
                        "portal_offender": _portal_offender_payload(offender),
                        "name_match": name_match,
                        "dob_match": dob_match,
                    }
                )
    return matches


def _offender_overlap_count(extracted: list[dict], portal_offenders: list[Offender]) -> int:
    if not extracted or not portal_offenders:
        return 0
    overlap = 0
    for offender in portal_offenders:
        for candidate in extracted:
            if not _name_matches(candidate, offender):
                continue
            candidate_birth_date = _candidate_birth_date(candidate)
            if candidate_birth_date and not dob_matches(candidate_birth_date, offender.date_of_birth):
                continue
            overlap += 1
            break
    return overlap


def _match_offenders(extracted: list[dict], event: Event) -> tuple[float, dict]:
    portal_offenders = list(event.offenders.all())
    counts = {
        "extracted": len(extracted),
        "portal": len(portal_offenders),
        "matched": 0,
    }
    if not extracted or not portal_offenders:
        return 0.0, counts

    scores = []
    for offender in portal_offenders:
        portal_name = " ".join(
            filter(None, [offender.second_name, offender.first_name, offender.patronymic_name])
        )
        portal_last = normalize_name_part(offender.second_name)
        best = 0.0
        for candidate in extracted:
            candidate_name = candidate.get("full_name", "")
            similarity = _offender_similarity(candidate_name.lower(), portal_name.lower())
            candidate_last = normalize_name_part(candidate.get("second_name"))
            if portal_last and candidate_last and portal_last == candidate_last:
                similarity += 0.1
            if offender.date_of_birth:
                candidate_birth_date = _candidate_birth_date(candidate)
                if candidate_birth_date and dob_matches(candidate_birth_date, offender.date_of_birth):
                    similarity += 0.15
            similarity = min(similarity, 1.0)
            best = max(best, similarity)
        if best >= 0.6:
            counts["matched"] += 1
        scores.append(best)
    return sum(scores) / len(scores), counts


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
) -> tuple[Event | None, int | None]:
    target_local = to_local_naive(target_dt)
    if target_local is None:
        return None, None
    date_from = target_local - timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    date_to = target_local + timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    candidates = list(
        Event.objects.using("portal").filter(
            find_subdivision_unit_id=subdivision_id,
            date_detection__range=(date_from, date_to),
        )
    )
    if not candidates:
        return None, None
    closest = min(
        candidates,
        key=lambda event: abs(to_local_naive(event.date_detection) - target_local),
    )
    delta_minutes = int(
        abs(
            to_local_naive(closest.date_detection) - target_local
        ).total_seconds()
        / 60
    )
    if delta_minutes > MATCH_TIME_DELTA_MINUTES:
        return None, None
    return repository.get_event_with_offenders(closest.event_id), delta_minutes


def _prefetch_portal_events(queryset):
    return queryset.prefetch_related(
        Prefetch("offenders", queryset=Offender.objects.using("portal"))
    )


def _select_event_by_subdivision_offenders(
    subdivision_id: str, extracted_offenders: list[dict], target_dt: datetime | None
) -> tuple[Event | None, int | None]:
    candidates = list(
        _prefetch_portal_events(
            Event.objects.using("portal")
            .filter(find_subdivision_unit_id=subdivision_id)
            .order_by("-date_detection")[:MATCH_STAGE_SUBDIVISION_LIMIT]
        )
    )
    if not candidates:
        return None, None
    best_event = None
    best_overlap = 0
    best_delta = None
    for event in candidates:
        overlap = _offender_overlap_count(extracted_offenders, list(event.offenders.all()))
        if overlap < 1:
            continue
        delta_minutes = None
        if target_dt:
            target_local = to_local_naive(target_dt)
            event_local = to_local_naive(event.date_detection)
            if target_local and event_local:
                delta_minutes = int(abs(event_local - target_local).total_seconds() / 60)
        should_replace = False
        if overlap > best_overlap:
            should_replace = True
        elif overlap == best_overlap and delta_minutes is not None:
            if best_delta is None or delta_minutes < best_delta:
                should_replace = True
        if should_replace:
            best_event = event
            best_overlap = overlap
            best_delta = delta_minutes
    if best_event is None:
        return None, None
    return best_event, best_delta


def _select_event_by_time_offenders(
    target_dt: datetime, extracted_offenders: list[dict]
) -> tuple[Event | None, int | None]:
    target_local = to_local_naive(target_dt)
    if target_local is None:
        return None, None
    date_from = target_local - timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    date_to = target_local + timedelta(minutes=MATCH_TIME_DELTA_MINUTES)
    candidates = list(
        _prefetch_portal_events(
            Event.objects.using("portal")
            .filter(date_detection__range=(date_from, date_to))
            .order_by("-date_detection")[:MATCH_STAGE_TIME_LIMIT]
        )
    )
    if not candidates:
        return None, None
    best_event = None
    best_overlap = 0
    best_delta = None
    for event in candidates:
        overlap = _offender_overlap_count(extracted_offenders, list(event.offenders.all()))
        if overlap < 1:
            continue
        event_local = to_local_naive(event.date_detection)
        if not event_local:
            continue
        delta_minutes = int(abs(event_local - target_local).total_seconds() / 60)
        if overlap > best_overlap or (overlap == best_overlap and delta_minutes < (best_delta or 10**9)):
            best_event = event
            best_overlap = overlap
            best_delta = delta_minutes
    if best_event is None:
        return None, None
    return best_event, best_delta


def match_event(attributes: ExtractedAttributes, text: str) -> dict:
    """Match extracted attributes to portal events and build comparison result."""
    subdivision_confidence_percent = 0.0
    best_candidate = attributes.subdivision_candidates[0] if attributes.subdivision_candidates else None
    if attributes.subdivision_candidates:
        subdivision_confidence_percent = round(
            attributes.subdivision_candidates[0]["score"] * 100, 2
        )
    predicted_type, predicted_article = _classify_event_type(text)

    best_event = None
    best_delta = None
    best_flags: dict = {}
    match_method = None
    time_mismatch = False
    subdivision_mismatch = False

    if attributes.date_time and attributes.subdivision_id:
        best_event, best_delta = _select_event_by_subdivision_time(
            attributes.subdivision_id,
            attributes.date_time,
        )
        if best_event:
            match_method = "subdivision+time"

    if not best_event and attributes.subdivision_id:
        best_event, best_delta = _select_event_by_subdivision_offenders(
            attributes.subdivision_id,
            attributes.offenders,
            attributes.date_time,
        )
        if best_event:
            match_method = "subdivision+offenders"
            time_mismatch = True
            best_flags = {
                "date_ok": False,
                "subdivision_ok": True,
                "offenders_ok": True,
            }

    if not best_event and attributes.date_time:
        best_event, best_delta = _select_event_by_time_offenders(
            attributes.date_time,
            attributes.offenders,
        )
        if best_event:
            match_method = "time+offenders"
            subdivision_mismatch = True
            best_flags = {
                "date_ok": True,
                "subdivision_ok": False,
                "offenders_ok": True,
            }

    if not best_event:
        unit_type_conflict = bool(
            best_candidate.get("flags", {}).get("unit_type_conflict") if best_candidate else False
        )
        return {
            "matched": False,
            "score_percent": 0,
            "time_delta_minutes": None,
            "offenders_score_percent": 0,
            "offenders_counts": {
                "extracted": len(attributes.offenders),
                "portal": 0,
                "matched": 0,
            },
            "subdivision_match_percent": subdivision_confidence_percent,
            "time_found": attributes.time_found,
            "date_time_present": bool(attributes.date_time),
            "subdivision_locality_query": best_candidate.get("query_locality") if best_candidate else None,
            "subdivision_locality_candidate": best_candidate.get("candidate_locality")
            if best_candidate
            else None,
            "subdivision_locality_mismatch": bool(
                best_candidate.get("locality_mismatch") if best_candidate else False
            ),
            "subdivision_unit_type_conflict": unit_type_conflict,
            "portal": None,
            "predicted": {
                "event_type": predicted_type,
                "article_of_law": predicted_article,
            },
            "match_method": None,
            "time_mismatch": False,
            "subdivision_mismatch": False,
            "diffs": {"message": "Событие не найдено по правилу 2 из 3."},
        }

    offenders_score, offenders_counts = _match_offenders(attributes.offenders, best_event)
    offenders_ok = offenders_score >= 0.6
    type_ok = predicted_type and predicted_type == best_event.event_type
    article_ok = predicted_article and predicted_article == best_event.article_of_law
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
            "actual": best_event.event_type,
        }
    if not best_flags.get("article_match"):
        diffs["article_of_law"] = {
            "expected": best_flags.get("predicted_article"),
            "actual": best_event.article_of_law,
        }
    if not best_flags.get("subdivision_ok"):
        diffs["subdivision"] = {
            "expected": attributes.subdivision_name,
            "actual": best_event.find_subdivision_unit.name,
        }
    if not best_flags.get("offenders_ok"):
        diffs["offenders"] = {
            "expected": [offender_to_json(offender) for offender in attributes.offenders],
            "actual": [
                {
                    "full_name": " ".join(
                        filter(
                            None,
                            [
                                offender.second_name,
                                offender.first_name,
                                offender.patronymic_name,
                            ],
                        )
                    ),
                    "birth_year": offender.date_of_birth.year,
                    "birth_date": date_to_str(offender.date_of_birth),
                }
                for offender in best_event.offenders.all()
            ],
        }

    portal_offenders = [_portal_offender_payload(offender) for offender in best_event.offenders.all()]
    offender_matches = _build_offender_matches(attributes.offenders, list(best_event.offenders.all()))
    subdivision_match_percent = subdivision_confidence_percent
    unit_type_conflict = bool(
        best_candidate.get("flags", {}).get("unit_type_conflict") if best_candidate else False
    )

    return {
        "matched": True,
        "matched_event_id": str(best_event.event_id),
        "score_percent": round(offenders_score * 100, 2),
        "extracted_timestamp_display": format_local_naive(attributes.date_time),
        "portal_timestamp_display": format_local_naive(best_event.date_detection),
        "time_delta_minutes": best_delta,
        "offenders_score_percent": best_flags.get("offenders_score", 0),
        "offenders_counts": best_flags.get("offenders_counts")
        or {
            "extracted": len(attributes.offenders),
            "portal": len(portal_offenders),
            "matched": offenders_counts.get("matched", 0),
        },
        "subdivision_match_percent": round(subdivision_match_percent, 2),
        "time_found": attributes.time_found,
        "date_time_present": bool(attributes.date_time),
        "subdivision_locality_query": best_candidate.get("query_locality") if best_candidate else None,
        "subdivision_locality_candidate": best_candidate.get("candidate_locality")
        if best_candidate
        else None,
        "subdivision_locality_mismatch": bool(
            best_candidate.get("locality_mismatch") if best_candidate else False
        ),
        "subdivision_unit_type_conflict": unit_type_conflict,
        "portal": {
            "timestamp": format_local_naive(best_event.date_detection),
            "subdivision_name": best_event.find_subdivision_unit.name
            if best_event.find_subdivision_unit
            else None,
            "offenders": portal_offenders,
            "event_type": best_event.event_type,
            "article_of_law": best_event.article_of_law,
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
    }
