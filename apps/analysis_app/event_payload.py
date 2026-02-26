from __future__ import annotations

from apps.analysis_app.subdivision_matcher import (
    SUBDIVISION_GREEN_THRESHOLD,
    SUBDIVISION_YELLOW_THRESHOLD,
)


DEFAULT_STATUS = "neutral"


def status_from_flag(flag: bool | None) -> str:
    if flag is True:
        return "green"
    if flag is False:
        return "red"
    return DEFAULT_STATUS


def status_for_timestamp(match_result: dict, *, time_error_minutes: int) -> str:
    if not match_result.get("matched"):
        return "red"
    delta = match_result.get("time_delta_minutes")
    if delta is None:
        return "red"
    delta_abs = abs(delta)
    if delta_abs == 0:
        return "green"
    if delta_abs <= time_error_minutes:
        return "yellow"
    return "red"


def status_for_subdivision(match_result: dict) -> str:
    score = match_result.get("subdivision_match_percent")
    if score is None:
        return "red"
    if match_result.get("subdivision_locality_mismatch") or match_result.get(
        "subdivision_unit_type_conflict"
    ):
        return "yellow" if score >= SUBDIVISION_YELLOW_THRESHOLD * 100 else "red"
    if score >= SUBDIVISION_GREEN_THRESHOLD * 100:
        return "green"
    if score >= SUBDIVISION_YELLOW_THRESHOLD * 100:
        return "yellow"
    return "red"


def status_for_offenders(match_result: dict) -> str:
    if not match_result.get("matched"):
        return "red"
    counts = match_result.get("offenders_counts") or {}
    matched = counts.get("matched", 0)
    portal_total = counts.get("portal_total", 0)
    has_issues = any(
        (
            counts.get("dob_mismatch", 0),
            counts.get("missing_in_portal", 0),
            counts.get("missing_in_svodka", 0),
        )
    )
    if matched == portal_total and not has_issues:
        return "green"
    if matched == 0 and (portal_total > 0 or has_issues):
        return "red"
    return "yellow"


def compute_status_fields(match_result: dict, *, time_error_minutes: int) -> dict[str, str]:
    return {
        "timestamp": status_for_timestamp(match_result, time_error_minutes=time_error_minutes),
        "subdivision": status_for_subdivision(match_result),
        "offenders": status_for_offenders(match_result),
        "event_type": status_from_flag(match_result.get("event_type_ok")),
        "article": match_result.get("article_status") or status_from_flag(match_result.get("article_ok")),
    }


def build_title_preview(idx: int, text: str, matched: bool) -> tuple[str, str]:
    title = f"Событие {idx}" + ("" if matched else " — в базе данных не найдено")
    normalized_text = text or ""
    preview = normalized_text[:80] + ("…" if len(normalized_text) > 80 else "")
    return title, preview


def build_event_detail_payload(paragraph, *, builder):
    return builder(paragraph)
