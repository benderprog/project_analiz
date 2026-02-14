from __future__ import annotations

import re
from dataclasses import asdict, dataclass


_TOKEN_RE = re.compile(r"[А-ЯЁа-яё0-9.-]+")
_RANK_PATTERN = (
    r"(?:"
    r"(?:ст\.\s*)?(?:пр-к|л-т|м-н)"
    r"|лейтенант|капитан|майор|подполковник|полковник|мичман|старшина"
    r"|генерал|адмирал|контр-адмирал|капитан-лейтенант|прапорщик|кап\.?"
    r")(?:\s+(?:2|3)\s+ранга)?"
)
_STAFF_RE = re.compile(
    rf"(?:(?P<rank>{_RANK_PATTERN})\s+)?(?P<surname>[А-ЯЁ][а-яё]{{2,}})\s+(?P<initials>(?:[А-ЯЁ]\s*\.\s*){{2}})(?:\+\d+)?",
    re.IGNORECASE,
)
_RANK_PREFIX_RE = re.compile(
    r"(?:^|[\s(,;:])(?P<rank>(?:(?:ст\.\s*)?(?:пр-к|л-т|м-н)|лейтенант|капитан|майор|подполковник|полковник|мичман|старшина|генерал|адмирал|контр-адмирал|капитан-лейтенант|прапорщик|кап\.?)(?:\s+(?:2|3)\s+ранга)?)\s*$",
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
    rank = re.sub(r"\s+", " ", raw).strip()
    rank = re.sub(r"(?i)^ст\.\s+пр-к$", "ст.пр-к", rank)
    return rank


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

        rank_norm = _normalize_rank(rank_raw)
        display = f"{rank_norm} {surname} {initials}".strip() if rank_norm else f"{surname} {initials}"
        key = _staff_key(surname, initials, rank_norm)
        if key in seen:
            continue
        seen.add(key)
        seen_spans.append(span)
        found.append(
            StaffMention(
                rank_raw=rank_raw,
                rank_norm=rank_norm,
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
        if rank_raw and display:
            display = f"{rank_raw} {display}"

        if span_tuple:
            rank_start = max(0, span_tuple[0] - len(rank_raw) - 2)
            rank_match = _RANK_PREFIX_RE.search(text[rank_start:span_tuple[0]])
            if rank_match:
                actual_start = rank_start + rank_match.start("rank")
                span_tuple = (actual_start, span_tuple[1])
        if span_tuple and _has_significant_overlap(span_tuple, seen_spans):
            continue

        rank_norm = _normalize_rank(rank_raw)
        key = _staff_key(surname, initials, rank_norm)
        if not key or key in seen:
            continue
        seen.add(key)
        if span_tuple:
            seen_spans.append(span_tuple)
        result.append(
            StaffMention(
                rank_raw=rank_raw,
                rank_norm=rank_norm,
                surname=surname,
                initials=initials,
                display=display.strip(),
                span=span_tuple,
            )
        )
    return result
