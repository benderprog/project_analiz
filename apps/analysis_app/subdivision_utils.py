from __future__ import annotations

import hashlib
import re

from apps.analysis_app.utils.subdivision_norm import normalize_text


_BRACKETS_REGEX = re.compile(r"\s*\([^)]*\)")
_LOCALITY_REGEX = re.compile(r"\((г\.|с\.|пгт\.?)\s*([^)]+)\)", re.IGNORECASE)

_ABBREVIATION_EXPANSIONS = {
    "ОП": ["ОПК", "отделение пограничного контроля", "отделение погранконтроля"],
    "ПЗ": ["пограничная застава", "погранзастава"],
    "ПОГЗ": ["пограничная застава", "погранзастава"],
    "ПОГО": ["пограничное отделение", "погранотделение"],
}


def normalize_subdivision_name(name: str) -> str:
    return normalize_text(name)


def _strip_quotes(value: str) -> str:
    return re.sub(r"[«»\"“”]", "", value).strip()


def _extract_locality_phrase(value: str) -> str | None:
    match = _LOCALITY_REGEX.search(value)
    if not match:
        return None
    prefix = match.group(1).strip().lower()
    name = match.group(2).strip()
    return f"{prefix} {name}".strip()


def _number_variants(prefix: str, number: str) -> list[str]:
    return [
        f"{prefix}{number}",
        f"{prefix}-{number}",
        f"{prefix} №{number}",
        f"{prefix} № {number}",
        f"{prefix} N{number}",
        f"{prefix} No{number}",
    ]


def build_subdivision_aliases(name: str, limit: int = 30) -> list[str]:
    base = name.strip()
    if not base:
        return []

    aliases: dict[str, None] = {}

    locality_phrase = _extract_locality_phrase(base)
    base_no_locality = _BRACKETS_REGEX.sub("", base).strip()

    def _add(value: str) -> None:
        cleaned = value.strip()
        if cleaned:
            aliases.setdefault(cleaned, None)

    base_variants = {base, base_no_locality, _strip_quotes(base), _strip_quotes(base_no_locality)}
    expanded_variants: set[str] = set()

    for variant in base_variants:
        if not variant:
            continue
        expanded_variants.add(variant)
        hyphen_space = re.sub(r"\s*[-—–−]\s*", " ", variant).strip()
        if hyphen_space:
            expanded_variants.add(hyphen_space)

        match = re.match(r"^(?P<prefix>ОП|ПЗ|ПОГЗ|ПОГО|ПОГК)\b\.?\s*(?P<rest>.*)$", variant)
        if match:
            prefix = match.group("prefix")
            rest = match.group("rest").strip()
            for expansion in _ABBREVIATION_EXPANSIONS.get(prefix, []):
                expanded_variants.add(f"{expansion} {rest}".strip())

    for variant in expanded_variants:
        _add(variant)
        number_match = re.search(r"\b(ОП|ОПК|ПЗ|ПОГЗ|ПОГО|ПОГК)\s*№?\s*(\d+)\b", variant)
        if number_match:
            prefix, number = number_match.groups()
            for numbered in _number_variants(prefix, number):
                if variant.endswith(number_match.group(0)):
                    base_variant = variant[: number_match.start()].strip()
                    composed = f"{base_variant} {numbered}".strip()
                    _add(composed)
                else:
                    _add(variant.replace(number_match.group(0), numbered))

    if locality_phrase:
        with_locality = list(aliases.keys())
        for variant in with_locality:
            _add(f"{variant} ({locality_phrase})")
            _add(f"{variant} {locality_phrase}")

    result = list(aliases.keys())
    result.sort(key=lambda item: (len(item), item))
    return result[:limit]


def to_py_float(value) -> float:
    return float(value)


def to_py_floats(vec) -> list[float]:
    if vec is None:
        return []
    if hasattr(vec, "tolist"):
        vec = vec.tolist()
    return [to_py_float(item) for item in vec]


def build_embedding_source_hash(normalized_name: str, aliases: list[str] | None) -> str:
    alias_list = sorted(aliases or [])
    payload = f"{normalized_name}|{'|'.join(alias_list)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
