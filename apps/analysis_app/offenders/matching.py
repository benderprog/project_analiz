from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date
from difflib import SequenceMatcher

from apps.analysis_app.utils.json_safe import offender_to_json
from apps.analysis_app.utils.offender_format import format_offender_dob
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
    "мичман",
    "старший",
    "старший мичман",
    "ст м н",
    "ст.м-н",
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
    last_close_before = text.rfind(")", 0, start)
    if open_idx == -1 or last_close_before > open_idx:
        return False
    close_idx = text.find(")", start)
    if close_idx == -1:
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
    content = re.sub(r"\+\d+\b", "", content)
    content_tokens = {_norm(token) for token in _TOKEN_RE.findall(content)}
    normalized_markers = {_norm(marker) for marker in EMPLOYEE_MARKERS}
    if content_tokens & normalized_markers:
        return True

    normalized_content = _norm(content)
    if "старшиймичман" in normalized_content or "стмн" in normalized_content:
        return True

    return "ст" in content_tokens and "мн" in content_tokens


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


def _is_year_only_dob(value: date | None) -> bool:
    return bool(value and value.day == 1 and value.month == 1)


def _format_dob(value: date | None, *, prefer_year: bool = False) -> str:
    if not value:
        return "—"
    if prefer_year or _is_year_only_dob(value):
        return str(value.year)
    return format_offender_dob(value)


def _portal_offender_key(portal: PortalOffender) -> tuple[str, str, str, str, date | None]:
    return (
        _norm(portal.second_name),
        _norm(portal.first_name),
        _norm(portal.patronymic_name),
        _norm(portal.full_name),
        portal.birth_date,
    )


def _dob_discrepancy(mention: OffenderMention, portal: PortalOffender) -> str | None:
    if not mention.birth_date or not portal.birth_date:
        return None
    if mention.birth_date == portal.birth_date:
        return None
    if _is_year_only_dob(mention.birth_date) and mention.birth_date.year == portal.birth_date.year:
        return None
    return None


def _nominative_variants(value: str, *, part: str) -> set[str]:
    variants = {value}
    if not value:
        return variants

    if part == "last" and value.endswith(("а", "я")) and len(value) > 3:
        variants.add(value[:-1])

    if part == "first":
        if value.endswith("ия") and len(value) > 3:
            variants.add(value[:-2] + "ий")
        if value.endswith("ия") and len(value) > 3:
            variants.add(value[:-1])
        if value.endswith("я") and len(value) > 2:
            variants.add(value[:-1] + "й")
        if value.endswith("и") and len(value) > 2:
            variants.add(value[:-1] + "я")
        if value.endswith("а") and len(value) > 2:
            variants.add(value[:-1])

    if part == "middle":
        if value.endswith("ича") and len(value) > 4:
            variants.add(value[:-1])
        if value.endswith("ича") and len(value) > 4:
            variants.add(value[:-3] + "ич")
        if value.endswith("овича") and len(value) > 6:
            variants.add(value[:-1])
        if value.endswith("евича") and len(value) > 6:
            variants.add(value[:-1])

    return {item for item in variants if item}


def _component_match(
    summary: str,
    portal: str,
    *,
    threshold: float,
    part: str,
    label: str,
) -> tuple[bool, str | None]:
    if not summary:
        return True, f"{label} отсутствует в сводке"
    if _is_initial(summary):
        if portal.startswith(summary):
            if summary != portal:
                return True, f"{label} в сводке указан инициалом"
            return True, None
        return False, None

    variants = _nominative_variants(summary, part=part)
    if portal in variants:
        if summary != portal:
            return True, f"{label} в сводке указан в косвенном падеже"
        return True, None

    ratio = _ratio(summary, portal)
    if ratio >= threshold:
        return True, f"{label} отличается"
    return False, None


def _fio_match_details(mention: OffenderMention, portal: PortalOffender) -> tuple[bool, str, str | None]:
    s_last = _norm(mention.second_name)
    p_last = _norm(portal.second_name)
    s_first = _norm(mention.first_name)
    p_first = _norm(portal.first_name)
    s_middle = _norm(mention.patronymic_name)
    p_middle = _norm(portal.patronymic_name)

    if not s_last:
        return False, "none", None

    surname_ok, surname_note = _component_match(
        s_last,
        p_last,
        threshold=SURNAME_THRESHOLD,
        part="last",
        label="фамилия",
    )
    if not surname_ok:
        return False, "none", None

    notes: list[str] = []
    if surname_note and "отсутствует" not in surname_note:
        notes.append(surname_note)

    first_ok, first_note = _component_match(
        s_first,
        p_first,
        threshold=NAME_THRESHOLD,
        part="first",
        label="имя",
    )
    if not first_ok:
        return False, "none", None
    if first_note:
        notes.append(first_note)

    middle_ok, middle_note = _component_match(
        s_middle,
        p_middle,
        threshold=PATRONYMIC_THRESHOLD,
        part="middle",
        label="отчество",
    )
    if not middle_ok:
        return False, "none", None
    if middle_note:
        notes.append(middle_note)

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
    accounted_portal: set[int] = set()

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

            dob_discrepancy = _dob_discrepancy(mention, portal)
            if dob_discrepancy:
                discrepancy = dob_discrepancy if not discrepancy else f"{discrepancy}; {dob_discrepancy}"

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
            accounted_portal.add(matched_portal_idx)
            result.matched_pairs.append(best[1])
            continue

        if best_possible is not None:
            result.possible_matches.append(best_possible)
            used_summary.add(i)
            possible_portal_idx = portal_offenders.index(best_possible.portal)
            accounted_portal.add(possible_portal_idx)
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

    seen_missing_portal_keys: set[tuple[str, str, str, str, date | None]] = set()
    for j, portal in enumerate(portal_offenders):
        if j in accounted_portal:
            continue
        portal_key = _portal_offender_key(portal)
        if portal_key in seen_missing_portal_keys:
            continue
        seen_missing_portal_keys.add(portal_key)
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
