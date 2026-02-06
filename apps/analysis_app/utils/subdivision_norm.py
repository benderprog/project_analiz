from __future__ import annotations

import re

_DASH_REGEX = re.compile(r"[—–−]")
_QUOTES_REGEX = re.compile(r"[«»\"“”]")
_NO_NUMBER_REGEX = re.compile(r"\b(?:no|n)\s*\.?\s*(\d+)\b", re.IGNORECASE)
_UNIT_NUMBER_REGEX = re.compile(r"\b(опк|оп|пз|погз|пого)\s*[-№]?\s*(\d+)\b")
_LOCALITY_REGEX = re.compile(r"\((г\.|с\.|пгт\.?)\s*([^)]+)\)", re.IGNORECASE)


def normalize_text(value: str) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    normalized = normalized.replace("ё", "е")
    normalized = _QUOTES_REGEX.sub("", normalized)
    normalized = _DASH_REGEX.sub("-", normalized)
    normalized = _NO_NUMBER_REGEX.sub(r"№\1", normalized)
    normalized = re.sub(r"№\s*(\d+)", r"№\1", normalized)
    normalized = _UNIT_NUMBER_REGEX.sub(r"\1 №\2", normalized)
    normalized = normalized.replace("(", " ").replace(")", " ")
    normalized = re.sub(r"(?<=\w)-(?=\w)", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_locality(value: str) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    match = _LOCALITY_REGEX.search(value)
    if not match:
        return None, None
    prefix = match.group(1).strip().lower().replace(".", "")
    locality = normalize_text(match.group(2).strip())
    if not locality:
        return None, None
    return prefix, locality
