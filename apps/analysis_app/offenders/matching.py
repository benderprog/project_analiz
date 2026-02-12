from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date
from difflib import SequenceMatcher

from apps.analysis_app.utils.json_safe import offender_to_json
from .types import (
    AmbiguousMention,
    MatchPair,
    OffenderMatchResult,
    OffenderMention,
    PortalOffender,
    PossibleMatch,
)

SURNAME_THRESHOLD = 0.90
NAME_THRESHOLD = 0.85
PATRONYMIC_THRESHOLD = 0.85

EMPLOYEE_MARKERS = {
    "пр-к",
    "прапорщик",
    "ст",
    "л-т",
    "лейтенант",
    "мл",
    "сержант",
    "капитан",
    "инспектор",
    "оперуполномоченный",
    "дежурный",
    "начальник",
    "майор",
    "подполковник",
}

_TOKEN_RE = re.compile(r"[а-яёa-z-]+", re.IGNORECASE)


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^а-яё]", "", value.lower()).replace("ё", "е")


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _is_initial(value: str) -> bool:
    return len(value) == 1


def _tokenize_with_spans(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).lower(), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def _is_inside_parentheses(text: str, span: tuple[int, int] | None) -> bool:
    if not span:
        return False
    start, end = span
    open_idx = text.rfind("(", 0, start)
    close_idx = text.find(")", end)
    if open_idx == -1 or close_idx == -1:
        return False
    return open_idx < start < end <= close_idx


def _has_rank_in_parentheses(text: str, span: tuple[int, int] | None) -> bool:
    if not _is_inside_parentheses(text, span):
        return False
    start, end = span
    open_idx = text.rfind("(", 0, start)
    close_idx = text.find(")", end)
    if open_idx == -1 or close_idx == -1:
        return False
    content = text[open_idx + 1 : close_idx].lower()
    content_tokens = {_norm(token) for token in _TOKEN_RE.findall(content)}
    normalized_markers = {_norm(marker) for marker in EMPLOYEE_MARKERS}
    return bool(content_tokens & normalized_markers)


def is_employee_context(text: str, mention_span: tuple[int, int] | None) -> bool:
    if not mention_span:
        return False
    tokens = _tokenize_with_spans(text)
    start = mention_span[0]
    prior_tokens = [token for token in tokens if token[2] <= start]
    lookback = prior_tokens[-3:]
    normalized_markers = {_norm(marker) for marker in EMPLOYEE_MARKERS}

    for token, _, _ in lookback:
        if _norm(token) in normalized_markers:
            return True

    return _has_rank_in_parentheses(text, mention_span)


def split_mentions_by_employee_context(
    text: str,
    mentions: list[OffenderMention],
) -> tuple[list[OffenderMention], list[OffenderMention]]:
    eligible: list[OffenderMention] = []
    excluded: list[OffenderMention] = []
    for mention in mentions:
        employee_context = is_employee_context(text, mention.span)
        marked = OffenderMention(**{**asdict(mention), "employee_context": employee_context})
        if employee_context:
            excluded.append(marked)
        else:
            eligible.append(marked)
    return eligible, excluded


def _dob_compatible(summary_dob: date | None, portal_dob: date | None) -> bool:
    if not summary_dob or not portal_dob:
        return True
    if summary_dob == portal_dob:
        return True
    if summary_dob.day == 1 and summary_dob.month == 1 and summary_dob.year == portal_dob.year:
        return True
    if portal_dob.day == 1 and portal_dob.month == 1 and portal_dob.year == summary_dob.year:
        return True
    return False


def _fio_match_details(mention: OffenderMention, portal: PortalOffender) -> tuple[bool, str, str | None]:
    s_last = _norm(mention.second_name)
    p_last = _norm(portal.second_name)
    s_first = _norm(mention.first_name)
    p_first = _norm(portal.first_name)
    s_middle = _norm(mention.patronymic_name)
    p_middle = _norm(portal.patronymic_name)

    if not s_last or _ratio(s_last, p_last) < SURNAME_THRESHOLD:
        return False, "none", None

    notes: list[str] = []

    if s_first:
        first_ok = False
        if _is_initial(s_first):
            first_ok = p_first.startswith(s_first)
            if not first_ok:
                return False, "none", None
            if s_first != p_first:
                notes.append("имя в сводке указано инициалом")
        else:
            ratio = _ratio(s_first, p_first)
            first_ok = ratio >= NAME_THRESHOLD
            if not first_ok:
                return False, "none", None
            if s_first != p_first:
                notes.append("имя отличается")
    else:
        notes.append("имя отсутствует в сводке")

    if s_middle:
        middle_ok = False
        if _is_initial(s_middle):
            middle_ok = p_middle.startswith(s_middle)
            if not middle_ok:
                return False, "none", None
            if s_middle != p_middle:
                notes.append("отчество в сводке указано инициалом")
        else:
            ratio = _ratio(s_middle, p_middle)
            middle_ok = ratio >= PATRONYMIC_THRESHOLD
            if not middle_ok:
                return False, "none", None
            if s_middle != p_middle:
                notes.append("отчество отличается")
    else:
        notes.append("отчество отсутствует в сводке")

    if not s_first and not s_middle:
        return True, "partial", "; ".join(notes)
    if notes:
        return True, "fuzzy", "; ".join(notes)
    return True, "exact", None


def match_offenders_with_details(
    summary_mentions: list[OffenderMention],
    excluded_mentions: list[OffenderMention],
    portal_offenders: list[PortalOffender],
) -> OffenderMatchResult:
    result = OffenderMatchResult()
    used_summary: set[int] = set()
    used_portal: set[int] = set()

    portal_surnames = {_norm(off.second_name) for off in portal_offenders if off.second_name}
    all_mentions = list(summary_mentions)
    for mention in excluded_mentions:
        if _norm(mention.second_name) in portal_surnames:
            all_mentions.append(mention)

    for i, mention in enumerate(all_mentions):
        best: tuple[int, MatchPair] | None = None
        best_possible: PossibleMatch | None = None

        for j, portal in enumerate(portal_offenders):
            if j in used_portal:
                continue
            fio_ok, match_type, discrepancy = _fio_match_details(mention, portal)
            if not fio_ok:
                continue
            if not _dob_compatible(mention.birth_date, portal.birth_date):
                best_possible = PossibleMatch(
                    mention=mention,
                    portal=portal,
                    reason="Возможное совпадение по ФИО, но ДР отличается",
                )
                continue

            rank = {"exact": 3, "fuzzy": 2, "partial": 1}.get(match_type, 0)
            pair = MatchPair(
                mention=mention,
                portal=portal,
                match_type=match_type,
                discrepancy=discrepancy,
            )
            if best is None or rank > best[0]:
                best = (rank, pair)

        if best is not None:
            used_summary.add(i)
            matched_portal_idx = portal_offenders.index(best[1].portal)
            used_portal.add(matched_portal_idx)
            result.matched_pairs.append(best[1])
            continue

        if best_possible is not None:
            result.possible_matches.append(best_possible)
            used_summary.add(i)
            continue

        same_surname = [p for p in portal_offenders if _norm(p.second_name) == _norm(mention.second_name)]
        if mention.first_name == "" and len(same_surname) > 1:
            result.ambiguous_mentions.append(
                AmbiguousMention(
                    mention=mention,
                    reason="Неоднозначно: в БД несколько нарушителей с этой фамилией",
                )
            )
            used_summary.add(i)
            continue

    for i, mention in enumerate(all_mentions):
        if i not in used_summary:
            result.missing_in_portal.append(mention)
    for j, portal in enumerate(portal_offenders):
        if j not in used_portal:
            result.missing_in_summary.append(portal)
    return result


def mention_to_dict(mention: OffenderMention) -> dict:
    return offender_to_json(
        {
            "full_name": mention.full_name,
            "second_name": mention.second_name,
            "first_name": mention.first_name,
            "patronymic_name": mention.patronymic_name,
            "birth_date": mention.birth_date,
            "birth_year": mention.birth_year,
            "span": mention.span,
            "source": mention.source,
            "surface_text": mention.surface_text,
            "employee_context": mention.employee_context,
        }
    )


def portal_to_dict(portal: PortalOffender) -> dict:
    return {
        "full_name": portal.full_name,
        "second_name": portal.second_name,
        "first_name": portal.first_name,
        "patronymic_name": portal.patronymic_name,
        "birth_date": portal.birth_date.isoformat() if portal.birth_date else None,
        "birth_year": portal.birth_date.year if portal.birth_date else None,
    }
