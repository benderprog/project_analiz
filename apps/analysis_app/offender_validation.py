from __future__ import annotations

from functools import lru_cache

import pymorphy2

STOPLIST = {
    "рф",
    "мвд",
    "фсб",
    "г",
    "пгт",
    "районе",
    "в",
    "у",
    "на",
    "через",
    "кпп",
    "пу",
}

VERBISH_POS = {"VERB", "INFN", "GRND", "PRTF", "PRTS", "ADVB"}


@lru_cache(maxsize=1)
def _get_morph():
    return pymorphy2.MorphAnalyzer()


def _tokenize(text: str) -> list[str]:
    raw_tokens = text.split()
    cleaned = []
    for token in raw_tokens:
        trimmed = token.strip(".,;:()[]{}\"'«»")
        if not trimmed:
            continue
        cleaned.append(trimmed)
    return cleaned


def _is_initial(token: str) -> bool:
    if len(token) == 1 and token.isalpha() and token.isupper():
        return True
    if len(token) == 2 and token[1] == "." and token[0].isalpha() and token[0].isupper():
        return True
    return False


def _is_title_case(token: str) -> bool:
    parts = token.split("-")
    for part in parts:
        if not part:
            return False
        if not part[0].isupper():
            return False
        if len(part) > 1 and not part[1:].islower():
            return False
    return True


def _is_all_caps_abbrev(token: str) -> bool:
    return len(token) > 1 and token.isalpha() and token.isupper()


def _is_name_like(token: str) -> bool:
    morph = _get_morph()
    for parse in morph.parse(token):
        grams = parse.tag.grammemes
        if "Name" in grams or "Surn" in grams or "Patr" in grams:
            return True
    return False


def is_valid_person_candidate(candidate_text: str) -> bool:
    tokens = _tokenize(candidate_text)
    if not tokens:
        return False

    lowered = [token.lower() for token in tokens]
    if any(token in STOPLIST for token in lowered):
        return False

    name_like_tokens = 0
    titlecase_tokens = []
    verbish_tokens = 0

    for idx, token in enumerate(tokens):
        if _is_all_caps_abbrev(token):
            next_token = tokens[idx + 1] if idx + 1 < len(tokens) else ""
            if idx == 0 and not _is_title_case(next_token):
                return False
            continue

        if _is_title_case(token):
            name_like_tokens += 1
            titlecase_tokens.append(token)
        elif _is_initial(token):
            name_like_tokens += 1

        for parse in _get_morph().parse(token):
            pos = parse.tag.POS
            if pos in VERBISH_POS:
                verbish_tokens += 1
                break

    if name_like_tokens < 2:
        return False

    if titlecase_tokens and not any(_is_name_like(token) for token in titlecase_tokens):
        return False

    if verbish_tokens > len(tokens) / 2:
        return False

    return True
