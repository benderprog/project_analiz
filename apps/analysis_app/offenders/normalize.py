from __future__ import annotations

from apps.analysis_app.offenders.constants import PATRONYMIC_SUFFIXES


def _normalize_token_case(value: str) -> str:
    if not value:
        return value
    if "-" in value:
        return "-".join(_normalize_token_case(part) for part in value.split("-"))
    return value[:1].upper() + value[1:].lower()


def _normalize_token(value: str, *, keep_suffix_lowercase: bool = False) -> str:
    if not value:
        return value
    words = [word for word in value.strip().split() if word]
    normalized: list[str] = []
    for word in words:
        stripped = word.strip()
        if keep_suffix_lowercase and stripped.lower() in PATRONYMIC_SUFFIXES:
            normalized.append(stripped.lower())
        else:
            normalized.append(_normalize_token_case(stripped))
    return " ".join(normalized)


def normalize_fio_to_nominative(second: str, first: str, middle: str) -> tuple[str, str, str]:
    normalized_second = _normalize_token(second or "")
    normalized_first = _normalize_token(first or "")
    normalized_middle = _normalize_token(middle or "", keep_suffix_lowercase=True)
    return normalized_second, normalized_first, normalized_middle
