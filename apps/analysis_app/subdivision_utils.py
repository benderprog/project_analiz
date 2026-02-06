from __future__ import annotations

import re


_DASH_REGEX = re.compile(r"[—–−]")
_BRACKETS_REGEX = re.compile(r"\s*\([^)]*\)")


def normalize_subdivision_name(name: str) -> str:
    value = name.strip().lower()
    value = value.replace("ё", "е")
    value = _DASH_REGEX.sub("-", value)
    value = value.replace("№", "n")
    value = re.sub(r"\s*-\s*", "-", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_subdivision_aliases(name: str) -> list[str]:
    base = name.strip()
    if not base:
        return []
    aliases: set[str] = set()

    def _add_variants(value: str) -> None:
        if not value:
            return
        hyphen_space = re.sub(r"\s*[-—–−]\s*", " ", value).strip()
        if hyphen_space and hyphen_space != value:
            aliases.add(hyphen_space)
        if "№" in value:
            aliases.add(re.sub(r"\s*№\s*", " ", value).strip())
        parts = re.split(r"\s*[-—–−]\s*", value, maxsplit=1)
        if len(parts) == 2:
            left, right = parts
            if left and right:
                aliases.add(f"{left} № {right}".strip())

    _add_variants(base)
    no_brackets = _BRACKETS_REGEX.sub("", base).strip()
    if no_brackets and no_brackets != base:
        aliases.add(no_brackets)
        _add_variants(no_brackets)

    aliases.discard(base)
    return sorted(aliases)
