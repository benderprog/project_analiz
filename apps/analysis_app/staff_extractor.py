from __future__ import annotations

import re
from dataclasses import asdict, dataclass


_TOKEN_RE = re.compile(r"[А-ЯЁа-яё0-9.-]+")
_SURNAME_INITIALS_RE = re.compile(
    r"(?P<surname>[А-ЯЁ][а-яё]{2,})\s+(?P<initials>(?:[А-ЯЁ]\s*\.?\s*){2})(?:\+\d+)?"
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


def extract_staff_mentions(text: str) -> list[StaffMention]:
    found: list[StaffMention] = []
    seen: set[str] = set()

    for match in _SURNAME_INITIALS_RE.finditer(text):
        surname = match.group("surname")
        initials = _normalize_initials(match.group("initials"))
        if not initials:
            continue

        span = (match.start(), match.end())
        rank_raw = _extract_rank_before(text, match.start("surname"))

        if not rank_raw:
            continue

        rank_norm = _normalize_rank(rank_raw)
        display = f"{rank_norm} {surname} {initials}".strip() if rank_norm else f"{surname} {initials}"
        key = f"{surname.lower()}|{initials}|{rank_norm.lower()}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            StaffMention(
                rank_raw=rank_raw,
                rank_norm=rank_norm,
                surname=surname,
                initials=initials,
                display=display,
            )
        )
    return found


def build_staff_from_excluded_mentions(excluded_mentions: list, text: str) -> list[StaffMention]:
    result: list[StaffMention] = []
    seen = set()
    for mention in excluded_mentions:
        surname = getattr(mention, "second_name", "") or ""
        first = getattr(mention, "first_name", "") or ""
        middle = getattr(mention, "patronymic_name", "") or ""
        span = getattr(mention, "span", None)
        rank_raw = ""
        if span and isinstance(span, tuple) and len(span) == 2:
            rank_raw = _extract_rank_before(text, span[0])

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

        key = display.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(
            StaffMention(
                rank_raw=rank_raw,
                rank_norm=_normalize_rank(rank_raw),
                surname=surname,
                initials=initials,
                display=display.strip(),
            )
        )
    return result
