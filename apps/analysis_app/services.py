from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from django.utils import timezone

from apps.classifier.models import EventTypeClassifier
from apps.portaldb import repository
from apps.portaldb.models import Event

from .semantic import get_sentence_model


@dataclass
class ExtractedAttributes:
    date_time: datetime | None
    subdivision_id: str | None
    offenders: list[dict]
    subdivision_name: str | None


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


def _extract_date(text: str) -> datetime | None:
    """Extract date/time using Natasha; return timezone-aware datetime."""
    from natasha import DatesExtractor

    extractor = DatesExtractor()
    matches = list(extractor(text))
    if not matches:
        return None
    dt = matches[0].fact.as_datetime()
    if dt is None:
        return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _extract_names(text: str) -> list[dict]:
    """Extract offender names and optional birth years."""
    from natasha import NamesExtractor

    extractor = NamesExtractor()
    offenders = []
    for match in extractor(text):
        name = match.fact
        full_name = " ".join(filter(None, [name.last, name.first, name.middle]))
        year = _find_birth_year(text, match.span[1])
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


def _find_birth_year(text: str, start_idx: int) -> int | None:
    snippet = text[start_idx : start_idx + 20]
    match = re.search(r"(19\d{2}|20\d{2})", snippet)
    return int(match.group(1)) if match else None


def _detect_subdivision(text: str) -> tuple[str | None, str | None]:
    subdivisions = list(repository.list_subdivisions())
    lowered = text.lower()
    for subdivision in subdivisions:
        if subdivision.name.lower() in lowered:
            return str(subdivision.subdivision_id), subdivision.name
    return None, None


def extract_attributes(text: str) -> ExtractedAttributes:
    """Extract event attributes from a paragraph."""
    date_time = _extract_date(text)
    offenders = _extract_names(text)
    subdivision_id, subdivision_name = _detect_subdivision(text)
    return ExtractedAttributes(
        date_time=date_time,
        subdivision_id=subdivision_id,
        offenders=offenders,
        subdivision_name=subdivision_name,
    )


def _offender_similarity(text_a: str, text_b: str) -> float:
    model = get_sentence_model()
    if model:
        embeddings = model.encode([text_a, text_b])
        similarity = float(
            (embeddings[0] @ embeddings[1])
            / (sum(embeddings[0] ** 2) ** 0.5 * sum(embeddings[1] ** 2) ** 0.5)
        )
        return similarity
    return SequenceMatcher(None, text_a, text_b).ratio()


def _match_offenders(extracted: list[dict], event: Event) -> float:
    if not extracted or not event.offenders.all():
        return 0.0

    scores = []
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
        scores.append(best)
    return sum(scores) / len(scores)


def _classify_event_type(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    for row in EventTypeClassifier.objects.all():
        pattern = row.event_pattern.lower().strip()
        if pattern and re.search(pattern, lowered):
            return row.event_type, row.article_of_law
        if pattern and pattern in lowered:
            return row.event_type, row.article_of_law
    return None, None


def match_event(attributes: ExtractedAttributes, text: str) -> dict:
    """Match extracted attributes to portal events and build comparison result."""
    candidates = []
    if attributes.date_time:
        candidates = list(repository.find_close_events_by_date(attributes.date_time))
    else:
        candidates = list(repository.find_candidate_events())

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
        offenders_score = _match_offenders(attributes.offenders, event)
        offenders_ok = offenders_score >= 0.6

        flags = {
            "date_ok": date_ok,
            "subdivision_ok": bool(subdivision_ok),
            "offenders_ok": offenders_ok,
        }
        if sum(flags.values()) < 2:
            continue

        predicted_type, predicted_article = _classify_event_type(text)
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

    return {
        "matched": True,
        "matched_event_id": str(best_event.event_id),
        "score_percent": round(best_score, 2),
        "time_delta_minutes": best_delta,
        "diffs": diffs,
    }
