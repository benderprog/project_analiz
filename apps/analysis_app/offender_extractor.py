from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache

from apps.analysis_app.offender_validation import is_valid_person_candidate

STOPWORDS = {
    "в",
    "на",
    "при",
    "и",
    "по",
    "р",
}

CYRILLIC_RE = re.compile(r"^[А-ЯЁа-яё-]+$")

_DOB_DATE_WITH_CONTEXT = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4})\s*(?:г\.?\s*р\.?|род\.?)")
_DOB_DATE_IN_PARENS = re.compile(
    r"\(\s*(?P<date>\d{2}\.\d{2}\.\d{4})\s*(?:г\.?\s*р\.?|род\.?)?\s*\)"
)
_DOB_YEAR_WITH_CONTEXT = re.compile(r"(?P<year>19\d{2}|20\d{2})\s*(?:г\.?\s*р\.?|род\.?)")
_DOB_YEAR_IN_PARENS = re.compile(
    r"\(\s*(?P<year>19\d{2}|20\d{2})\s*(?:г\.?\s*р\.?|род\.?)?\s*\)"
)

_INITIALS_REGEX = re.compile(
    r"\b(?P<last>[А-ЯЁ][а-яё]+)\s+"
    r"(?P<first>[А-ЯЁ])\.?\s*"
    r"(?:(?P<middle>[А-ЯЁ])\.?)?\b"
)

_CONTEXT_TRIGGERS = (
    "гражданин",
    "гражданка",
    "установлен",
    "выявлен",
    "выявлены",
    "задержан",
    "обнаружен",
)
_CONTEXT_REGEX = re.compile(
    rf"(?P<trigger>{'|'.join(_CONTEXT_TRIGGERS)})(?:\s+|:\s+)"
    r"(?P<last>[А-ЯЁ][а-яё]+)\s+"
    r"(?P<first>[А-ЯЁ][а-яё]+)"
    r"(?:\s+(?P<middle>[А-ЯЁ][а-яё]+))?",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _get_morph():
    """Provide a shared MorphVocab for Natasha extractors (required in 1.6+)."""
    from natasha import MorphVocab

    return MorphVocab()


def _match_span(match) -> tuple[int, int] | None:
    span_attr = getattr(match, "span", None)
    if span_attr is not None:
        span = span_attr() if callable(span_attr) else span_attr
        if isinstance(span, (tuple, list)) and len(span) == 2:
            return int(span[0]), int(span[1])
        if hasattr(span, "start") and hasattr(span, "stop"):
            return int(span.start), int(span.stop)
        if hasattr(span, "begin") and hasattr(span, "end"):
            return int(span.begin), int(span.end)
    if hasattr(match, "start") and hasattr(match, "end"):
        return int(match.start), int(match.end)
    if hasattr(match, "start") and hasattr(match, "stop"):
        return int(match.start), int(match.stop)
    return None


def _is_valid_token(token: str | None, *, allow_initial: bool = False) -> bool:
    if not token:
        return False
    lowered = token.strip().lower()
    if lowered in STOPWORDS:
        return False
    if len(lowered) < 2 and not allow_initial:
        return False
    return bool(CYRILLIC_RE.match(token))


def _looks_like_person(
    last: str | None, first: str | None, full_name: str, *, allow_initials: bool = False
) -> bool:
    if not last or not first:
        return False
    tokens = full_name.split()
    if len(tokens) < 2:
        return False
    if not _is_valid_token(last):
        return False
    if not _is_valid_token(first, allow_initial=allow_initials):
        return False
    return True


def _normalize_value(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^А-ЯЁа-яё]", "", value).lower()
    return cleaned.replace("ё", "е")


def normalize_name_part(value: str | None) -> str:
    normalized = _normalize_value(value)
    if len(normalized) <= 1:
        return normalized
    return normalized


def _make_key(offender: dict) -> str:
    last = normalize_name_part(offender.get("second_name"))
    first = normalize_name_part(offender.get("first_name"))
    middle = normalize_name_part(offender.get("patronymic_name"))
    return f"{last}|{first}|{middle}"


def _birth_rank(offender: dict) -> int:
    if offender.get("birth_date"):
        return 2
    if offender.get("birth_year"):
        return 1
    return 0


def parse_birth_info(text: str, anchor_end: int | None) -> tuple[date | None, int | None]:
    if anchor_end is None:
        return None, None
    window = text[anchor_end : anchor_end + 60]
    for pattern in (_DOB_DATE_WITH_CONTEXT, _DOB_DATE_IN_PARENS):
        match = pattern.search(window)
        if match:
            date_str = match.group("date")
            try:
                birth_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            except ValueError:
                return None, None
            return birth_date, birth_date.year
    for pattern in (_DOB_YEAR_WITH_CONTEXT, _DOB_YEAR_IN_PARENS):
        match = pattern.search(window)
        if match:
            return None, int(match.group("year"))
    return None, None


def _initial_full_name(last: str, first: str | None, middle: str | None) -> str:
    parts = [last]
    if first:
        parts.append(f"{first}.")
    if middle:
        parts.append(f"{middle}.")
    return " ".join(parts)


def _span_for_match(match, start_group: str, end_group: str) -> tuple[int, int] | None:
    try:
        start = match.start(start_group)
        end = match.end(end_group)
    except (IndexError, KeyError):
        return None
    return int(start), int(end)


def _extract_natasha(text: str) -> list[dict]:
    from natasha import NamesExtractor

    extractor = NamesExtractor(_get_morph())
    offenders = []
    for match in extractor(text):
        name = match.fact
        full_name = " ".join(filter(None, [name.last, name.first, name.middle]))
        if not _looks_like_person(name.last, name.first, full_name):
            continue
        if not is_valid_person_candidate(full_name):
            continue
        span = _match_span(match)
        birth_date, birth_year = parse_birth_info(text, span[1] if span else None)
        offenders.append(
            {
                "full_name": full_name,
                "second_name": name.last,
                "first_name": name.first,
                "patronymic_name": name.middle,
                "birth_date": birth_date,
                "birth_year": birth_year,
                "span": span,
                "surface_text": text[span[0] : span[1]] if span else full_name,
                "source": "natasha",
            }
        )
    return offenders


def _extract_initials(text: str) -> list[dict]:
    offenders = []
    for match in _INITIALS_REGEX.finditer(text):
        last = match.group("last")
        first = match.group("first")
        middle = match.group("middle")
        full_name = _initial_full_name(last, first, middle)
        if not _looks_like_person(last, first, full_name, allow_initials=True):
            continue
        if not is_valid_person_candidate(full_name):
            continue
        span = _match_span(match)
        birth_date, birth_year = parse_birth_info(text, span[1] if span else None)
        offenders.append(
            {
                "full_name": full_name,
                "second_name": last,
                "first_name": first,
                "patronymic_name": middle,
                "birth_date": birth_date,
                "birth_year": birth_year,
                "span": span,
                "surface_text": text[span[0] : span[1]] if span else full_name,
                "source": "regex_initials",
            }
        )
    return offenders


def _extract_context(text: str) -> list[dict]:
    offenders = []
    for match in _CONTEXT_REGEX.finditer(text):
        last = match.group("last")
        first = match.group("first")
        middle = match.group("middle")
        full_name = " ".join(filter(None, [last, first, middle]))
        if not _looks_like_person(last, first, full_name):
            continue
        if not is_valid_person_candidate(full_name):
            continue
        span = _span_for_match(match, "last", "middle" if middle else "first")
        birth_date, birth_year = parse_birth_info(text, span[1] if span else None)
        offenders.append(
            {
                "full_name": full_name,
                "second_name": last,
                "first_name": first,
                "patronymic_name": middle,
                "birth_date": birth_date,
                "birth_year": birth_year,
                "span": span,
                "surface_text": text[span[0] : span[1]] if span else full_name,
                "source": "regex_context",
            }
        )
    return offenders


def _overlaps(span_a: tuple[int, int] | None, span_b: tuple[int, int] | None) -> bool:
    if not span_a or not span_b:
        return False
    return span_a[0] < span_b[1] and span_b[0] < span_a[1]


def _merge_candidates(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged = list(primary)
    for candidate in secondary:
        span = candidate.get("span")
        if any(_overlaps(span, existing.get("span")) for existing in merged):
            continue
        merged.append(candidate)
    return merged


def _deduplicate(offenders: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for offender in offenders:
        key = _make_key(offender)
        existing = seen.get(key)
        if not existing:
            seen[key] = offender
            continue
        existing_rank = _birth_rank(existing)
        candidate_rank = _birth_rank(offender)
        if candidate_rank > existing_rank:
            seen[key] = offender
        elif candidate_rank == existing_rank:
            existing_name = existing.get("full_name") or ""
            candidate_name = offender.get("full_name") or ""
            if len(candidate_name) > len(existing_name):
                seen[key] = offender
    return list(seen.values())


def extract_offenders(text: str) -> list[dict]:
    natasha = _extract_natasha(text)
    initials = _extract_initials(text)
    context = _extract_context(text)
    merged = _merge_candidates(natasha, initials)
    merged = _merge_candidates(merged, context)
    return _deduplicate(merged)
