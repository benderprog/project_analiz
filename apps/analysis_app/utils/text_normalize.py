from __future__ import annotations

from typing import Iterable


_QUOTE_CHARS = {"\u00ab", "\u00bb", "\"", "\u201c", "\u201d"}
_DASH_CHARS = {"\u2013", "\u2014", "\u2212"}
_TRAILING_PUNCT = {".", ",", ";", ":", ")", "]", "}"}
_PUNCT_AS_SPACE = {"(", ")", "[", "]", "{", "}", ".", ",", ";", ":", "\u2116"} | _QUOTE_CHARS


def normalize_subdivision_text(value: str) -> str:
    normalized, _ = _normalize_with_mapping(value)
    return normalized


def normalize_subdivision_text_with_mapping(value: str) -> tuple[str, list[int]]:
    return _normalize_with_mapping(value)


def _normalize_with_mapping(value: str) -> tuple[str, list[int]]:
    if not value:
        return "", []

    text = value.strip()
    result: list[str] = []
    mapping: list[int] = []
    last_was_space = False
    index = 0

    while index < len(text):
        ch = text[index]
        lower = ch.lower()
        if lower == "\u0451":
            lower = "\u0435"

        if lower in _DASH_CHARS:
            lower = "-"

        if lower == "n":
            next_index = _match_number_symbol(text, index)
            if next_index is not None:
                index = _append_spacing(text, index, next_index, result, mapping, last_was_space)
                last_was_space = bool(result and result[-1] == " ")
                continue

        if lower.isspace() or lower in _PUNCT_AS_SPACE:
            index = _consume_spacing(
                text,
                index,
                result,
                mapping,
                last_was_space,
            )
            last_was_space = bool(result and result[-1] == " ")
            continue

        result.append(lower)
        mapping.append(index)
        last_was_space = False
        index += 1

    _trim_trailing_punct(result, mapping)
    normalized = "".join(result).strip()
    if normalized:
        leading_spaces = len(normalized) - len(normalized.lstrip(" "))
        if leading_spaces:
            normalized = normalized.lstrip(" ")
            mapping = mapping[leading_spaces:]
    return normalized, mapping


def _consume_spacing(
    text: str,
    index: int,
    result: list[str],
    mapping: list[int],
    last_was_space: bool,
) -> int:
    next_index = index
    while next_index < len(text) and (text[next_index].isspace() or text[next_index] in _PUNCT_AS_SPACE):
        next_index += 1

    if not result:
        return next_index

    next_char = _peek_next_non_space(text, next_index)
    prev_char = result[-1]
    if prev_char.isalnum() and next_char.isdigit():
        result.append("-")
        mapping.append(index)
        return next_index
    if last_was_space:
        return next_index
    result.append(" ")
    mapping.append(index)
    return next_index


def _append_spacing(
    text: str,
    index: int,
    next_index: int,
    result: list[str],
    mapping: list[int],
    last_was_space: bool,
) -> int:
    if not result:
        return next_index
    next_char = _peek_next_non_space(text, next_index)
    prev_char = result[-1]
    if prev_char.isalnum() and next_char.isdigit():
        result.append("-")
        mapping.append(index)
        return next_index
    if prev_char == " " and next_char.isdigit():
        for back_index in range(len(result) - 2, -1, -1):
            if result[back_index] == " ":
                continue
            if result[back_index].isalnum():
                result[-1] = "-"
            break
        return next_index
    if last_was_space:
        return next_index
    result.append(" ")
    mapping.append(index)
    return next_index


def _peek_next_non_space(text: str, start: int) -> str:
    index = start
    while index < len(text) and (text[index].isspace() or text[index] in _PUNCT_AS_SPACE):
        index += 1
    if index >= len(text):
        return ""
    return text[index].lower()


def _match_number_symbol(text: str, index: int) -> int | None:
    next_index = index + 1
    if next_index < len(text) and text[next_index].lower() == "o":
        next_index += 1
    if next_index < len(text) and text[next_index] == ".":
        next_index += 1
    while next_index < len(text) and text[next_index].isspace():
        next_index += 1
    if next_index < len(text) and text[next_index].isdigit():
        return next_index
    return None


def _trim_trailing_punct(result: list[str], mapping: list[int]) -> None:
    while result and result[-1] in _TRAILING_PUNCT | {" "}:
        result.pop()
        if mapping:
            mapping.pop()


__all__: Iterable[str] = [
    "normalize_subdivision_text",
    "normalize_subdivision_text_with_mapping",
]
