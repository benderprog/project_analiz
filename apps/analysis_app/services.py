from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from functools import lru_cache

from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from apps.classifier.models import EventTypePattern
from apps.analysis_app.utils.dt_display import format_local_naive
from apps.portaldb import repository
from apps.portaldb.models import Event

from .semantic import get_sentence_model
from .subdivision_matcher import (
    SUBDIVISION_MATCH_THRESHOLD,
    match_subdivision,
)

logger = logging.getLogger(__name__)


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


def _extract_names(text: str) -> list[dict]:
    """Extract offender names and optional birth years."""
    from natasha import NamesExtractor

    extractor = NamesExtractor(_get_morph())
    offenders = []
    for match in extractor(text):
        name = match.fact
        full_name = " ".join(filter(None, [name.last, name.first, name.middle]))
        end_idx = _match_end_index(match)
        year = _find_birth_year(text, end_idx) if end_idx is not None else None
        offenders.append(
            {
                "full_name": full_name,
                "first_name": name.first,
                "second_name": name.last,
                "patronymic_name": name.middle,
                "birth_year": year,
            }
        )
    return offenders


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


def _find_birth_year(text: str, start_idx: int) -> int | None:
    snippet = text[start_idx : start_idx + 20]
    match = re.search(r"(19\d{2}|20\d{2})", snippet)
    return int(match.group(1)) if match else None


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
    offenders = _extract_names(text)
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


def _match_offenders(extracted: list[dict], event: Event) -> tuple[float, int]:
    if not extracted or not event.offenders.all():
        return 0.0, 0

    scores = []
    matched_count = 0
    for offender in event.offenders.all():
        portal_name = " ".join(
            filter(None, [offender.second_name, offender.first_name, offender.patronymic_name])
        )
        best = 0.0
        for candidate in extracted:
            candidate_name = candidate.get("full_name", "")
            similarity = _offender_similarity(candidate_name.lower(), portal_name.lower())
            if candidate.get("birth_year") and offender.date_of_birth:
                if offender.date_of_birth.year == candidate["birth_year"]:
                    similarity += 0.1
            best = max(best, similarity)
        if best >= 0.6:
            matched_count += 1
        scores.append(best)
    return sum(scores) / len(scores), matched_count


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


def match_event(attributes: ExtractedAttributes, text: str) -> dict:
    """Match extracted attributes to portal events and build comparison result."""
    subdivision_confidence_percent = 0.0
    best_candidate = attributes.subdivision_candidates[0] if attributes.subdivision_candidates else None
    if attributes.subdivision_candidates:
        subdivision_confidence_percent = round(
            attributes.subdivision_candidates[0]["score"] * 100, 2
        )
    candidates = []
    if attributes.date_time:
        candidates = list(repository.find_close_events_by_date(attributes.date_time))
    else:
        candidates = list(repository.find_candidate_events())

    predicted_type, predicted_article = _classify_event_type(text)

    if attributes.subdivision_id:
        candidates = [
            event
            for event in candidates
            if str(event.find_subdivision_unit_id) == attributes.subdivision_id
        ]

    best_event = None
    best_score = -1.0
    best_delta = None
    best_flags = {}
    best_offenders_matched = 0

    for event in candidates:
        event = repository.get_event_with_offenders(event.event_id)
        date_ok = False
        delta_minutes = None
        if attributes.date_time:
            delta = abs(event.date_detection - attributes.date_time)
            delta_minutes = int(delta.total_seconds() / 60)
            date_ok = delta <= timedelta(minutes=30)

        subdivision_ok = (
            attributes.subdivision_id
            and str(event.find_subdivision_unit_id) == attributes.subdivision_id
        )
        offenders_score, offenders_matched = _match_offenders(attributes.offenders, event)
        offenders_ok = offenders_score >= 0.6

        flags = {
            "date_ok": date_ok,
            "subdivision_ok": bool(subdivision_ok),
            "offenders_ok": offenders_ok,
        }
        if sum(flags.values()) < 2:
            continue

        type_ok = predicted_type and predicted_type == event.event_type
        article_ok = predicted_article and predicted_article == event.article_of_law

        score = 0.0
        score += 40.0 if subdivision_ok else 0.0
        score += offenders_score * 40.0
        score += 20.0 if type_ok and article_ok else 0.0

        if score > best_score:
            best_event = event
            best_score = score
            best_delta = delta_minutes
            best_offenders_matched = offenders_matched
            best_flags = {
                **flags,
                "type_match": type_ok,
                "article_match": article_ok,
                "predicted_type": predicted_type,
                "predicted_article": predicted_article,
                "offenders_score": round(offenders_score * 100, 2),
            }

    if not best_event:
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
            "portal": None,
            "predicted": {
                "event_type": predicted_type,
                "article_of_law": predicted_article,
            },
            "diffs": {"message": "Событие не найдено по правилу 2 из 3."},
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
            "expected": attributes.offenders,
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
                }
                for offender in best_event.offenders.all()
            ],
        }

    portal_offenders = [
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
            "birth_year": offender.date_of_birth.year if offender.date_of_birth else None,
        }
        for offender in best_event.offenders.all()
    ]
    subdivision_match_percent = subdivision_confidence_percent

    return {
        "matched": True,
        "matched_event_id": str(best_event.event_id),
        "score_percent": round(best_score, 2),
        "extracted_timestamp_display": format_local_naive(attributes.date_time),
        "portal_timestamp_display": format_local_naive(best_event.date_detection),
        "time_delta_minutes": best_delta,
        "offenders_score_percent": best_flags.get("offenders_score", 0),
        "offenders_counts": {
            "extracted": len(attributes.offenders),
            "portal": len(portal_offenders),
            "matched": best_offenders_matched,
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
        "diffs": diffs,
    }
