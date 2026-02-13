from __future__ import annotations

from functools import lru_cache


def _to_title(token: str) -> str:
    if not token:
        return token
    return token[:1].upper() + token[1:].lower()


def _fallback_nominative(value: str, *, part: str) -> str:
    if not value:
        return value

    if part == "last" and value.endswith(("а", "я")) and len(value) > 3:
        return value[:-1]

    if part == "first":
        if value.endswith("ия") and len(value) > 3:
            return value[:-2] + "ий"
        if value.endswith("я") and len(value) > 2:
            return value[:-1] + "й"
        if value.endswith("и") and len(value) > 2:
            return value[:-1] + "я"
        if value.endswith("а") and len(value) > 2:
            return value[:-1]

    if part == "middle":
        if value.endswith("ича") and len(value) > 4:
            return value[:-3] + "ич"
        if value.endswith("овича") and len(value) > 6:
            return value[:-1]
        if value.endswith("евича") and len(value) > 6:
            return value[:-1]

    return value


@lru_cache(maxsize=1)
def _get_morph():
    try:
        import pymorphy2
    except Exception:
        return None
    return pymorphy2.MorphAnalyzer()


def _normalize_token(value: str, *, part: str) -> str:
    if not value:
        return value
    if not all("А" <= ch <= "я" or ch in "Ёё-" for ch in value):
        return value

    morph = _get_morph()
    if morph is None:
        return _to_title(_fallback_nominative(value.lower(), part=part))

    tag_map = {"last": "Surn", "first": "Name", "middle": "Patr"}
    preferred_tag = tag_map.get(part)
    lower_value = value.lower()
    parses = morph.parse(lower_value)
    preferred = [item for item in parses if preferred_tag and preferred_tag in item.tag]
    ordered = preferred or parses

    normalized = None
    for parse in ordered:
        inflected = parse.inflect({"nomn"})
        if not inflected:
            continue
        candidate = inflected.word
        normalized = candidate
        break

    if normalized is None:
        normalized = _fallback_nominative(lower_value, part=part)
    return _to_title(normalized)


def normalize_fio_to_nominative(second: str, first: str, middle: str) -> tuple[str, str, str]:
    normalized_second = _normalize_token(second or "", part="last")
    normalized_first = _normalize_token(first or "", part="first")
    normalized_middle = _normalize_token(middle or "", part="middle")

    likely_male = (normalized_middle or "").lower().endswith("ич") or (
        (normalized_first or "")[-1:].lower() in {"й"}
    )
    if (
        likely_male
        and second
        and second.lower().endswith(("а", "я"))
        and normalized_second.lower() == second.lower()
    ):
        normalized_second = _to_title(_fallback_nominative(second.lower(), part="last"))

    return normalized_second, normalized_first, normalized_middle

