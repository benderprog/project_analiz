from __future__ import annotations

import re
from difflib import SequenceMatcher
from dataclasses import asdict, dataclass


_TOKEN_RE = re.compile(r"[А-ЯЁа-яё0-9.-]+")


def normalize_rank_token(value: str) -> str:
    lowered = (value or "").lower().replace("ё", "е")
    lowered = re.sub(r"[–—−]", "-", lowered)
    lowered = re.sub(r"[\s\-]", "", lowered)
    lowered = re.sub(r"[\./\\,;:()\[\]{}\"'«»]", "", lowered)
    return re.sub(r"[^а-я0-9]", "", lowered)


_CANONICAL_RANK_ALIASES = {
    "прк": "Прапорщик",
    "прапорщик": "Прапорщик",
    "стпрк": "Старший прапорщик",
    "старшийпрапорщик": "Старший прапорщик",
    "мллт": "Младший лейтенант",
    "младшийлейтенант": "Младший лейтенант",
    "лт": "Лейтенант",
    "лейтенант": "Лейтенант",
    "стлт": "Старший лейтенант",
    "старшийлейтенант": "Старший лейтенант",
    "кн": "Капитан",
    "кап": "Капитан",
    "капитан": "Капитан",
    "мр": "Майор",
    "майор": "Майор",
    "ппк": "Подполковник",
    "подполковник": "Подполковник",
    "пк": "Полковник",
    "полковник": "Полковник",
    "мн": "Мичман",
    "мичман": "Мичман",
    "стмн": "Старший мичман",
    "старшиймичман": "Старший мичман",
    "кл": "Капитан-лейтенант",
    "капитанлейтенант": "Капитан-лейтенант",
    "к3р": "Капитан 3-го ранга",
    "капитан3горанга": "Капитан 3-го ранга",
    "капитан3ранга": "Капитан 3-го ранга",
    "к2р": "Капитан 2-го ранга",
    "капитан2горанга": "Капитан 2-го ранга",
    "капитан2ранга": "Капитан 2-го ранга",
    "к1р": "Капитан 1-го ранга",
    "капитан1горанга": "Капитан 1-го ранга",
    "капитан1ранга": "Капитан 1-го ранга",
    "старшина": "Старшина",
    "генерал": "Генерал",
    "адмирал": "Адмирал",
    "контрадмирал": "Контр-адмирал",
}

RANK_ALIASES = {
    normalize_rank_token(alias): full_rank
    for alias, full_rank in _CANONICAL_RANK_ALIASES.items()
}
_FULL_RANK_KEYS = {k: v for k, v in RANK_ALIASES.items() if len(k) >= 6}


def _abbr_pattern(alias: str) -> str:
    joiner = r"[\s.\-/\\–—]*"
    return joiner.join(re.escape(char) for char in alias)


_SHORT_ALIASES = sorted(
    {
        normalize_rank_token(alias)
        for alias in (
            "пр-к",
            "ст. пр-к",
            "мл. л-т",
            "л-т",
            "ст. л-т",
            "к-н",
            "м-р",
            "п/п-к",
            "п-к",
            "м-н",
            "ст. м-н",
            "к/л",
            "к-3р",
            "к-2р",
            "к-1р",
        )
    },
    key=len,
    reverse=True,
)
_SHORT_RANK_PATTERN = "|".join(_abbr_pattern(alias) for alias in _SHORT_ALIASES)
_FULL_RANK_PATTERN = (
    r"(?:"
    r"прапорщик|старш(?:ий|ая)\s+прапорщик|младш(?:ий|ая)\s+лейтенант|лейтенант|старш(?:ий|ая)\s+лейтенант"
    r"|капитан(?:\s*[\-–—]?\s*лейтенант)?|майор|подполковник|полковник"
    r"|мичман|старш(?:ий|ая)\s+мичман|старшина|генерал|адмирал|контр\s*[\-–—]?\s*адмирал"
    r")(?:\s+[-–—]?\s*[123](?:-?\s*го)?\s+ранга)?"
)
_RANK_PATTERN = rf"(?:{_SHORT_RANK_PATTERN}|{_FULL_RANK_PATTERN}|[А-ЯЁа-яё]{{6,}})"
_STAFF_RE = re.compile(
    rf"(?:^|[\s(,;:])(?:(?P<rank>{_RANK_PATTERN})\s+)?(?P<surname>[А-ЯЁ][а-яё]{{2,}})\s+(?P<initials>(?:[А-ЯЁ]\s*\.\s*){{2}})(?:\+\d+)?",
    re.IGNORECASE,
)
_RANK_PREFIX_RE = re.compile(
    rf"(?:^|[\s(,;:])(?P<rank>{_RANK_PATTERN})\s*$",
    re.IGNORECASE,
)

_RANK_MARKERS = {
    "л-т",
    "лейтенант",
    "ст",
    "старший",
    "ст.",
    "кап",
    "кап.",
    "капитан",
    "майор",
    "подполковник",
    "полковник",
    "мичман",
    "м-н",
    "ст.м-н",
    "старшина",
    "генерал",
    "адмирал",
    "контр-адмирал",
    "капитан-лейтенант",
    "пр-к",
    "прапорщик",
    "ранга",
}
_CONNECTOR_TOKENS = {"2", "3", "ст", "ст.", "мл", "мл."}


@dataclass(frozen=True)
class StaffMention:
    rank_raw: str
    rank_norm: str
    rank_full: str
    surname: str
    initials: str
    display: str
    span: tuple[int, int] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_token(value: str) -> str:
    return re.sub(r"[^а-яё0-9]", "", value.lower()).replace("ё", "е")


def _normalize_initials(raw: str) -> str:
    letters = re.findall(r"[А-ЯЁ]", raw)
    if len(letters) < 2:
        return ""
    return f"{letters[0]}.{letters[1]}."


def _inside_parentheses(text: str, span: tuple[int, int]) -> bool:
    start, end = span
    open_idx = text.rfind("(", 0, start)
    close_idx = text.find(")", end)
    return open_idx != -1 and close_idx != -1 and open_idx < start < end <= close_idx


def _extract_rank_before(text: str, surname_start: int) -> str:
    prefix = text[max(0, surname_start - 40) : surname_start]
    rank_match = _RANK_PREFIX_RE.search(prefix)
    if rank_match:
        return rank_match.group("rank").strip(" ,;:")

    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    index = next((i for i, (_, s, e) in enumerate(tokens) if s <= surname_start < e), None)
    if index is None or index == 0:
        return ""

    normalized_markers = {_norm_token(x) for x in _RANK_MARKERS}
    normalized_connectors = {_norm_token(x) for x in _CONNECTOR_TOKENS}

    rank_tokens: list[str] = []
    has_marker = False
    for i in range(index - 1, max(-1, index - 5), -1):
        token = tokens[i][0]
        norm = _norm_token(token)
        if norm in normalized_markers:
            has_marker = True
            rank_tokens.append(token)
            continue
        if rank_tokens and norm in normalized_connectors:
            rank_tokens.append(token)
            continue
        break

    if not has_marker:
        return ""

    rank_tokens.reverse()
    return re.sub(r"\s+", " ", " ".join(rank_tokens)).strip(" ,;:")


def _normalize_rank(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip(" ,;:")


def _resolve_rank(raw: str) -> tuple[str, str]:
    rank_norm = _normalize_rank(raw)
    normalized = normalize_rank_token(rank_norm)
    if not normalized:
        return rank_norm, ""

    direct = RANK_ALIASES.get(normalized)
    if direct:
        return rank_norm, direct

    if len(normalized) < 6:
        return rank_norm, ""

    best_key = ""
    best_ratio = 0.0
    for key in _FULL_RANK_KEYS:
        ratio = SequenceMatcher(None, normalized, key).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_key = key
    if best_key and best_ratio >= 0.8:
        return rank_norm, _FULL_RANK_KEYS[best_key]
    return rank_norm, ""


def _staff_key(surname: str, initials: str, rank: str) -> str:
    surname_norm = surname.lower().replace("ё", "е")
    initials_norm = initials.lower().replace("ё", "е")
    rank_norm = rank.lower().replace("ё", "е")
    return f"{surname_norm}|{initials_norm}|{rank_norm}"


def _has_significant_overlap(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    for existing_start, existing_end in spans:
        overlap = min(end, existing_end) - max(start, existing_start)
        if overlap > 0:
            return True
    return False


def extract_staff_mentions(text: str) -> list[StaffMention]:
    found: list[StaffMention] = []
    seen: set[str] = set()
    seen_spans: list[tuple[int, int]] = []

    for match in _STAFF_RE.finditer(text):
        surname = match.group("surname")
        initials = _normalize_initials(match.group("initials"))
        if not initials:
            continue

        rank_raw = (match.group("rank") or "").strip(" ,;:")
        if not rank_raw:
            rank_raw = _extract_rank_before(text, match.start("surname"))
        if not rank_raw:
            continue

        span_start = match.start("rank") if match.group("rank") else match.start("surname")
        span = (span_start, match.end())
        if _has_significant_overlap(span, seen_spans):
            continue

        rank_norm, rank_full = _resolve_rank(rank_raw)
        if not rank_full and not normalize_rank_token(rank_norm) in RANK_ALIASES:
            continue

        rank_for_display = rank_full or rank_norm
        display = f"{rank_for_display} {surname} {initials}".strip() if rank_for_display else f"{surname} {initials}"
        key = _staff_key(surname, initials, rank_for_display)
        if key in seen:
            continue
        seen.add(key)
        seen_spans.append(span)
        found.append(
            StaffMention(
                rank_raw=rank_raw,
                rank_norm=rank_norm,
                rank_full=rank_full,
                surname=surname,
                initials=initials,
                display=display,
                span=span,
            )
        )
    return found


def build_staff_from_excluded_mentions(excluded_mentions: list, text: str) -> list[StaffMention]:
    result: list[StaffMention] = []
    seen: set[str] = set()
    seen_spans: list[tuple[int, int]] = []
    for mention in excluded_mentions:
        surname = ""
        first = getattr(mention, "first_name", "") or ""
        middle = getattr(mention, "patronymic_name", "") or ""
        span = getattr(mention, "span", None)
        rank_raw = ""
        span_tuple: tuple[int, int] | None = None
        if span and isinstance(span, tuple) and len(span) == 2:
            span_tuple = (int(span[0]), int(span[1]))
            surname = text[span_tuple[0] : span_tuple[1]].split()[0]
            rank_raw = _extract_rank_before(text, span[0])
        if not surname:
            surname = getattr(mention, "second_name", "") or ""

        initials = ""
        if len(first) == 1 and len(middle) == 1:
            initials = f"{first}.{middle}."
        display = getattr(mention, "full_name", "") or " ".join(filter(None, [surname, first, middle]))
        if initials and surname:
            display = f"{surname} {initials}"
        if not rank_raw:
            continue
        rank_norm, rank_full = _resolve_rank(rank_raw)
        rank_for_display = rank_full or rank_norm
        if not rank_for_display:
            continue
        if display:
            display = f"{rank_for_display} {display}"

        if span_tuple:
            rank_start = max(0, span_tuple[0] - len(rank_raw) - 2)
            rank_match = _RANK_PREFIX_RE.search(text[rank_start:span_tuple[0]])
            if rank_match:
                actual_start = rank_start + rank_match.start("rank")
                span_tuple = (actual_start, span_tuple[1])
        if span_tuple and _has_significant_overlap(span_tuple, seen_spans):
            continue

        key = _staff_key(surname, initials, rank_for_display)
        if not key or key in seen:
            continue
        seen.add(key)
        if span_tuple:
            seen_spans.append(span_tuple)
        result.append(
            StaffMention(
                rank_raw=rank_raw,
                rank_norm=rank_norm,
                rank_full=rank_full,
                surname=surname,
                initials=initials,
                display=display.strip(),
                span=span_tuple,
            )
        )
    return result
