import json
import logging
import os
from pathlib import PurePath
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.files.storage import default_storage
from django.core.paginator import EmptyPage, Paginator
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View

from apps.analysis_app.forms import (
    GENERAL_SUMMARY_PU_LABEL,
    PuSelectionForm,
    UploadDocxWithPuForm,
    is_general_summary_pu,
)
from apps.analysis_app.debug_package import build_debug_zip_bytes
from apps.analysis_app.event_payload import (
    build_event_detail_payload,
    build_title_preview,
    compute_status_fields,
    status_for_offenders,
    status_for_subdivision,
    status_for_timestamp,
    status_from_flag,
)
from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun, CachedPU, FeatureFlags, SvodkaTemplate
from apps.analysis_app.services import (
    TABLE_ROW_JOINER,
    _find_case_insensitive_span,
    _find_datetime_span,
    ensure_classifier_candidates,
    extract_attributes,
    highlight_text,
    match_event,
)
from apps.analysis_app.template_preview import build_template_preview_context, extract_template_text
from apps.analysis_app.ui_mode import is_admin_ui
from apps.analysis_app.utils.dt_display import format_dt_dmy_hm, format_run_started_at
from apps.analysis_app.utils.offender_format import offender_display
from apps.classifier.models import EventTypePattern

TIME_ERROR_MINUTES = int(getattr(settings, "TIME_ERROR_MINUTES", 30))


logger = logging.getLogger(__name__)


def _display_filename(file_name: str | None) -> str:
    if not file_name:
        return ""
    normalized = str(file_name).replace("\\", "/")
    return PurePath(normalized).name


def compute_elapsed_seconds(run: AnalysisRun) -> int | None:
    if run.started_at:
        end = run.finished_at or timezone.now()
        return max(int((end - run.started_at).total_seconds()), 0)
    return None


def format_elapsed(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    total = max(int(seconds), 0)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _results_url(run: AnalysisRun) -> str:
    if run.status == AnalysisRun.Status.DONE:
        return reverse("analysis-detail", kwargs={"run_id": str(run.run_id)})
    return ""


def _debug_zip_url(run: AnalysisRun) -> str:
    if run.status in [AnalysisRun.Status.DONE, AnalysisRun.Status.FAILED]:
        return reverse("analysis-debug-zip", kwargs={"run_id": str(run.run_id)})
    return ""


def _stage_label(name: str) -> str:
    labels = {
        "parsing": "Парсинг",
        "extraction": "Извлечение",
        "matching": "Матчинг",
        "classification": "Классификация",
        "starting": "Подготовка",
        "done": "Готово",
        "failed": "Ошибка",
    }
    return labels.get(str(name or "").lower(), str(name or "—"))


def _format_stage_ms(ms_value) -> str:
    try:
        ms_int = int(ms_value)
    except (TypeError, ValueError):
        return "—"
    if ms_int >= 1000:
        return f"{ms_int / 1000:.1f}с"
    return f"{ms_int}мс"


def _debug_pipeline_payload(run: AnalysisRun) -> dict:
    data = run.debug_pipeline if isinstance(run.debug_pipeline, dict) else {}
    stages = []
    for item in data.get("stages") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        ms = int(item.get("ms") or 0)
        stages.append({"name": name, "label": _stage_label(name), "ms": ms, "duration": _format_stage_ms(ms)})
    current_stage = str(data.get("current_stage") or "")
    stage_line = ""
    if stages:
        stage_line = " → ".join(f"{item['label']} {item['duration']}" for item in stages)
    elif current_stage:
        stage_line = f"Этап: {_stage_label(current_stage)}…"
    return {
        "current_stage": current_stage,
        "current_stage_label": _stage_label(current_stage) if current_stage else "",
        "stages": stages,
        "total_ms": int(data.get("total_ms") or 0),
        "stage_line": stage_line,
        "updated_at": data.get("updated_at"),
    }




def _slicing_status_payload(run: AnalysisRun) -> dict[str, object]:
    meta = run.slicing_meta if isinstance(run.slicing_meta, dict) else {}
    method = str(meta.get("method") or "none")
    anchors_expected = int(meta.get("anchors_expected") or 0)
    anchors_matched = int(meta.get("anchors_matched") or 0)
    anchors_missing = bool(meta.get("anchors_missing"))
    fallback_to_full_report = bool(meta.get("fallback_to_full_report"))
    reasons = [str(item) for item in (meta.get("reasons") or []) if str(item)]
    threshold = meta.get("threshold")
    segments = meta.get("segments") if isinstance(meta.get("segments"), list) else []

    if method == "report_markers":
        label = "Шаблон: применён"
        warning = False
    elif anchors_missing or fallback_to_full_report:
        label = "Шаблон: не применён — якоря не определены, проанализирована вся сводка"
        warning = True
    elif anchors_matched > 0:
        label = "Шаблон: применён"
        warning = False
    else:
        label = "Шаблон: не применён"
        warning = False

    return {
        "label": label,
        "warning": warning,
        "method": method,
        "anchors_expected": anchors_expected,
        "anchors_matched": anchors_matched,
        "anchors_missing": anchors_missing,
        "fallback_to_full_report": fallback_to_full_report,
        "reasons": reasons,
        "threshold": threshold,
        "segments": segments,
    }


def _slicing_preview_payload(run: AnalysisRun, *, debug_mode: bool) -> dict[str, object] | None:
    del debug_mode
    meta = run.slicing_meta if isinstance(run.slicing_meta, dict) else {}
    raw_text = str(meta.get("analyzed_text") or "").strip()
    if not raw_text:
        return None

    def _format_score(value: object) -> str:
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return "—"

    def _format_threshold(value: object) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "—"

    fallback_to_full_report = bool(meta.get("fallback_to_full_report"))
    anchors = meta.get("template_anchors") if isinstance(meta.get("template_anchors"), list) else []
    segments = [item for item in anchors if isinstance(item, dict)]
    segments.sort(key=lambda item: int(item.get("segment_index") or 0))

    if fallback_to_full_report:
        return {
            "fallback_to_full_report": True,
            "fallback_text": raw_text,
            "inline_segments": [],
        }

    inline_segments: list[dict[str, object]] = []
    for seg in segments:
        start = seg.get("start") if isinstance(seg.get("start"), dict) else {}
        end = seg.get("end") if isinstance(seg.get("end"), dict) else {}
        threshold_raw = seg.get("threshold_used", seg.get("threshold", meta.get("threshold")))
        threshold = _format_threshold(threshold_raw)

        start_matched_line = start.get("matched_line")
        start_score = _format_score(start.get("score"))
        start_best_score = _format_score(start.get("best_score"))
        if start_matched_line:
            start_line = (
                f"Якорь начала (в сводке): {start_matched_line} "
                f"(score={start_score}, threshold={threshold})"
            )
        else:
            start_line = f"Якорь начала: не найден (best_score={start_best_score}, threshold={threshold})"

        is_open_ended = bool(seg.get("open_ended")) or not seg.get("template_anchor_end")
        end_matched_line = end.get("matched_line")
        end_score = _format_score(end.get("score"))
        if is_open_ended:
            end_line = "Якорь конца: отсутствует (сегмент до конца документа)"
        elif end_matched_line:
            end_line = (
                f"Якорь конца (в сводке): {end_matched_line} "
                f"(score={end_score}, threshold={threshold})"
            )
        else:
            end_best_score = _format_score(end.get("best_score"))
            end_line = f"Якорь конца: не найден (best_score={end_best_score}, threshold={threshold})"

        inline_segments.append(
            {
                "segment_index": int(seg.get("segment_index") or 0),
                "start_line": start_line,
                "end_line": end_line,
                "slice_text": str(seg.get("slice_text") or "").strip(),
            }
        )

    return {
        "fallback_to_full_report": False,
        "fallback_text": "",
        "inline_segments": inline_segments,
    }


def _app_version_payload() -> dict[str, str]:
    settings_version = getattr(settings, "VERSION", "")
    git_sha = os.getenv("GIT_SHA") or os.getenv("COMMIT_SHA") or os.getenv("SOURCE_VERSION") or ""
    return {
        "version": str(settings_version or "unknown"),
        "git_sha": str(git_sha or "unknown"),
    }


def _safe_run_payload(run: AnalysisRun) -> dict[str, object]:
    return {
        "run_id": str(run.run_id),
        "uploaded_by_id": run.uploaded_by_id,
        "original_filename": run.original_filename,
        "created_session_key": run.created_session_key,
        "detected_pu_id": run.detected_pu_id,
        "detected_pu_name": run.detected_pu_name,
        "selected_pu_id": run.selected_pu_id,
        "selected_pu_name": run.selected_pu_name,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "status": run.status,
        "queued_at": run.queued_at.isoformat() if run.queued_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error_message": run.error_message,
        "progress_total": run.progress_total,
        "progress_done": run.progress_done,
        "progress_updated_at": run.progress_updated_at.isoformat() if run.progress_updated_at else None,
        "slicing_meta": run.slicing_meta if isinstance(run.slicing_meta, dict) else {},
    }


def _build_slicing_payload(results_qs) -> dict[str, object]:
    slicing: dict[str, object] = {"template": None, "items": []}
    for result in results_qs:
        match_result = result.match_result or {}
        debug_data = match_result.get("debug") or {}
        template_info = debug_data.get("template") or {}
        if not slicing["template"] and template_info:
            slicing["template"] = {
                "template_id": template_info.get("template_id"),
                "scope": template_info.get("scope"),
                "pu_id": template_info.get("pu_id"),
                "begin": template_info.get("begin"),
                "end": template_info.get("end"),
            }
        if debug_data:
            slicing["items"].append({"idx": result.paragraph.idx, "debug": debug_data})
    return slicing




def _compute_progress_percent(done: int | None, total: int | None) -> int:
    if total is None or total <= 0:
        return 0
    safe_done = max(min(int(done or 0), int(total)), 0)
    return int(round(100 * safe_done / int(total)))


def _progress_payload(run: AnalysisRun) -> dict[str, int | str | None]:
    total = run.progress_total
    done = run.progress_done

    if run.status == AnalysisRun.Status.DONE and total is not None:
        done = total

    percent = _compute_progress_percent(done, total)

    if run.status == AnalysisRun.Status.QUEUED and total in [None, 0]:
        label = "В очереди"
    elif total is not None and total > 0:
        label = f"{max(min(int(done or 0), int(total)), 0)} / {int(total)} ({percent}%)"
    elif run.status in [AnalysisRun.Status.QUEUED, AnalysisRun.Status.RUNNING]:
        label = "В очереди"
    else:
        label = ""

    return {
        "progress_total": total,
        "progress_done": done,
        "progress_percent": percent,
        "progress_label": label,
    }


def _queue_started_at_display(run: AnalysisRun) -> str:
    if run.started_at is not None:
        return format_run_started_at(run.started_at)
    if run.queued_at is not None:
        return format_run_started_at(run.queued_at)
    return "—"

def _cached_pu_full_name_map(request) -> dict[str, str]:
    cached = getattr(request, "_pu_full_name_map", None)
    if cached is not None:
        return cached

    pu_map: dict[str, str] = {}
    for pu in CachedPU.objects.all().only("portal_pu_id", "full_name", "short_name"):
        pu_map[str(pu.portal_pu_id)] = str(pu.full_name or pu.short_name or "")

    if not pu_map:
        from apps.portaldb.gateway import get_portal_gateway

        gateway = get_portal_gateway()
        for pu in gateway.list_pus():
            pu_map[str(pu.pu_id)] = str(pu.full_name or pu.short_name or "")

    setattr(request, "_pu_full_name_map", pu_map)
    return pu_map


def _resolve_selected_pu_name(request, selected_pu_id: str | None) -> str:
    if is_general_summary_pu(selected_pu_id):
        return GENERAL_SUMMARY_PU_LABEL

    selected_value = str(selected_pu_id)
    pu_map = _cached_pu_full_name_map(request)
    resolved_name = pu_map.get(selected_value)
    if resolved_name:
        return resolved_name

    return ""


def _format_offenders(offenders: list[dict], *, source: str) -> list[str]:
    return [offender_display(offender, source=source) for offender in offenders or []]


def _status_key_for_offender(offender: dict | None) -> str:
    offender = offender or {}
    span = offender.get("span")
    if isinstance(span, list) and len(span) == 2:
        return f"{int(span[0])}:{int(span[1])}"
    if isinstance(span, tuple) and len(span) == 2:
        return f"{int(span[0])}:{int(span[1])}"
    full_name = " ".join(str(offender.get("full_name") or "").lower().split())
    birth_year = offender.get("birth_year")
    birth_date = offender.get("birth_date")
    if not birth_year and isinstance(birth_date, str) and len(birth_date) >= 4:
        birth_year = birth_date[:4]
    elif not birth_year and hasattr(birth_date, "year"):
        birth_year = birth_date.year
    return f"fio:{full_name}|year:{birth_year or ''}"


def _format_offenders_with_status(offenders: list[dict], *, match_result: dict, source: str) -> list[dict]:
    status_map = (match_result.get("offender_matches") or {}).get("svodka_status_by_span") or {}
    formatted = []
    status_to_css = {
        "ok": "hl-green",
        "warn": "hl-yellow",
        "err": "hl-red",
    }
    for offender in offenders or []:
        key = _status_key_for_offender(offender)
        status = status_map.get(key, "warn")
        formatted.append(
            {
                "text": offender_display(offender, source=source),
                "status": status,
                "status_css": status_to_css.get(status, "hl-yellow"),
            }
        )
    return formatted


def _dedupe_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _offender_dedupe_key(offender: dict | None) -> tuple[str, str]:
    offender = offender or {}
    full_name = str(offender.get("full_name") or "").strip().lower()
    birth_date = str(offender.get("birth_date") or offender.get("birth_year") or "")
    return full_name, birth_date


def _dedupe_pairs(pairs: list[dict], *, key_getter) -> list[dict]:
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for pair in pairs:
        key = key_getter(pair)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pair)
    return deduped


def _build_pattern_event_types_map(events: list[dict]) -> dict[str, list[dict]]:
    patterns = {
        str((event.get("predicted") or {}).get("best_pattern_text") or "").strip()
        for event in events
    }
    patterns.discard("")
    if not patterns:
        return {}

    rows = (
        EventTypePattern.objects.filter(
            is_active=True,
            event_type__is_active=True,
            pattern__in=patterns,
        )
        .select_related("event_type")
        .order_by("event_type__event_type", "article_of_law")
    )

    mapping: dict[str, list[dict]] = {}
    seen_by_pattern: dict[str, set[str]] = {}
    for row in rows:
        pattern = str(row.pattern or "").strip()
        if not pattern:
            continue
        event_type_id = str(row.event_type.event_type_id)
        pattern_seen = seen_by_pattern.setdefault(pattern, set())
        if event_type_id in pattern_seen:
            continue
        pattern_seen.add(event_type_id)
        mapping.setdefault(pattern, []).append(
            {
                "event_type_id": event_type_id,
                "event_type_name": row.event_type.event_type,
                "article_of_law": row.article_of_law or None,
            }
        )
    return mapping


def _status_for_timestamp(match_result: dict) -> str:
    return status_for_timestamp(match_result, time_error_minutes=TIME_ERROR_MINUTES)


def _status_for_subdivision(match_result: dict) -> str:
    return status_for_subdivision(match_result)


def _status_for_offenders(match_result: dict) -> str:
    return status_for_offenders(match_result)


def _build_offender_report(match_result: dict) -> dict:
    counts = match_result.get("offenders_counts") or {}
    summary = None
    if counts:
        summary = (
            "Совпало нарушителей: "
            f"{counts.get('matched', 0)} из {counts.get('portal_total', 0)}"
        )

    details = []
    matches = match_result.get("offender_matches") or {}

    matched_pairs = _dedupe_pairs(
        matches.get("matched_pairs") or [],
        key_getter=lambda pair: (
            _offender_dedupe_key(pair.get("svodka_offender")),
            _offender_dedupe_key(pair.get("portal_offender")),
            pair.get("match_type"),
            pair.get("discrepancy"),
        ),
    )
    for pair in matched_pairs:
        discrepancy = pair.get("discrepancy")
        if not discrepancy:
            continue
        svodka_display = _format_offenders([pair.get("svodka_offender")], source="svodka")[0]
        portal_display = _format_offenders([pair.get("portal_offender")], source="portal")[0]
        details.append(
            f"ФИО совпало частично/с ошибкой: {svodka_display} / {portal_display} ({discrepancy})"
        )

    dob_mismatch_pairs = _dedupe_pairs(
        matches.get("dob_mismatch_pairs") or [],
        key_getter=lambda pair: (
            _offender_dedupe_key(pair.get("svodka_offender")),
            _offender_dedupe_key(pair.get("portal_offender")),
            pair.get("reason"),
        ),
    )
    for pair in dob_mismatch_pairs:
        svodka_display = _format_offenders([pair.get("svodka_offender")], source="svodka")[0]
        portal_display = _format_offenders([pair.get("portal_offender")], source="portal")[0]
        details.append(
            f"Возможное совпадение по ФИО, но ДР отличается: {svodka_display} / {portal_display}"
        )

    ambiguous = matches.get("ambiguous") or []
    for item in ambiguous:
        svodka_display = _format_offenders([item.get("svodka_offender")], source="svodka")[0]
        details.append(f"Неоднозначное совпадение: {svodka_display}")

    missing_in_portal = _format_offenders(
        matches.get("missing_in_portal") or [], source="svodka"
    )
    missing_in_portal = _dedupe_items(missing_in_portal)
    if missing_in_portal:
        details.append(
            "В сводке есть, в БД нет: " + ", ".join(missing_in_portal)
        )

    missing_in_svodka = _format_offenders(
        matches.get("missing_in_svodka") or [], source="portal"
    )
    missing_in_svodka = _dedupe_items(missing_in_svodka)
    if missing_in_svodka:
        details.append(
            "В БД есть, в сводке нет: " + ", ".join(missing_in_svodka)
        )

    return {"summary": summary, "details": details}


def collect_highlight_spans(text: str, extracted: dict, match_result: dict) -> list[dict]:
    spans: list[dict] = []
    strong_spans: list[tuple[int, int]] = []

    def _add_span(start: int, end: int, css_class: str, *, is_strong: bool = True) -> None:
        if end <= start:
            return
        spans.append({"start": start, "end": end, "css": css_class})
        if is_strong:
            strong_spans.append((start, end))

    timestamp_css = f"hl-{_status_for_timestamp(match_result)}"
    date_span = extracted.get("date_span")
    time_span = extracted.get("time_span")
    if isinstance(date_span, (list, tuple)) and len(date_span) == 2:
        _add_span(int(date_span[0]), int(date_span[1]), timestamp_css)
    else:
        fallback_date_span = _find_datetime_span(text)
        if fallback_date_span:
            _add_span(int(fallback_date_span[0]), int(fallback_date_span[1]), timestamp_css)
    if isinstance(time_span, (list, tuple)) and len(time_span) == 2:
        time_span_tuple = (int(time_span[0]), int(time_span[1]))
        _add_span(time_span_tuple[0], time_span_tuple[1], timestamp_css)
        logger.debug("time highlight applied span=%s", time_span_tuple)
    else:
        logger.debug("time highlight skipped (no time span)")


    subdivision_span = extracted.get("subdivision_span")
    if subdivision_span:
        _add_span(
            subdivision_span[0],
            subdivision_span[1],
            f"hl-{_status_for_subdivision(match_result)}",
        )
    else:
        subdivision = extracted.get("subdivision_name")
        subdivision_span = _find_case_insensitive_span(text, subdivision) if subdivision else None
        if subdivision_span:
            _add_span(
                subdivision_span[0],
                subdivision_span[1],
                f"hl-{_status_for_subdivision(match_result)}",
            )

    safe_match_result = match_result or {}
    article_status = safe_match_result.get("article_status") or _status_from_flag(safe_match_result.get("article_ok"))
    article_css = {
        "green": "hl-green",
        "yellow": "hl-yellow",
        "red": "hl-red",
    }.get(article_status)
    article_spans = extracted.get("article_spans") or []
    if article_css:
        for span in article_spans:
            if isinstance(span, (list, tuple)) and len(span) == 2:
                _add_span(int(span[0]), int(span[1]), article_css)

    offenders = extracted.get("offenders") or []
    status_map = (match_result.get("offender_matches") or {}).get("svodka_status_by_span") or {}
    status_to_css = {
        "ok": "hl-green",
        "warn": "hl-yellow",
        "err": "hl-red",
    }
    offender_spans: list[tuple[int, int]] = []
    for offender in offenders:
        offender_status = status_to_css.get(status_map.get(_status_key_for_offender(offender), "warn"), "hl-yellow")
        full_name = offender.get("full_name")
        offender_span = offender.get("span")
        if offender_span and len(offender_span) == 2:
            offender_span = (int(offender_span[0]), int(offender_span[1]))
        else:
            offender_span = _find_case_insensitive_span(text, full_name) if full_name else None
        if offender_span:
            offender_spans.append(offender_span)
            _add_span(offender_span[0], offender_span[1], offender_status)
        dob_span = offender.get("dob_span")
        if dob_span and len(dob_span) == 2:
            _add_span(int(dob_span[0]), int(dob_span[1]), offender_status)

    for staff_item in extracted.get("staff") or []:
        staff_span = staff_item.get("span") if isinstance(staff_item, dict) else None
        if not (staff_span and len(staff_span) == 2):
            continue
        staff_span = (int(staff_span[0]), int(staff_span[1]))
        overlaps_offender = any(
            min(staff_span[1], offender_span[1]) - max(staff_span[0], offender_span[0]) > 0
            for offender_span in offender_spans
        )
        if overlaps_offender:
            continue
        _add_span(staff_span[0], staff_span[1], "hl-green hl-staff")

    predicted = (match_result or {}).get("predicted")
    if not isinstance(predicted, dict):
        predicted = {}
    event_match = predicted.get("event_type_match") or predicted.get("event_pattern")
    if not isinstance(event_match, dict):
        event_match = {}
    span = event_match.get("span")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        event_span = (int(span[0]), int(span[1]))
        overlaps_strong = any(
            min(event_span[1], strong_span[1]) - max(event_span[0], strong_span[0]) > 0
            for strong_span in strong_spans
        )
        if not overlaps_strong:
            _add_span(event_span[0], event_span[1], "hl-green hl-eventpattern", is_strong=False)

    return spans


def apply_spans(text: str, spans: list[dict]) -> str:
    safe_html = str(highlight_text(
        text,
        [
            (int(span.get("start", 0)), int(span.get("end", 0)), str(span.get("css", "")))
            for span in (spans or [])
        ],
    ))
    return safe_html.replace("\n", "<br>")


def _build_highlighted_html(text: str, extracted: dict, match_result: dict) -> str:
    spans = collect_highlight_spans(text, extracted, match_result)
    return apply_spans(text, spans)


def _build_table_row_highlighted_cells(source_cells: list[str], extracted: dict, match_result: dict) -> list[str]:
    joined_text = TABLE_ROW_JOINER.join(source_cells)
    spans = collect_highlight_spans(joined_text, extracted, match_result)
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for index, cell in enumerate(source_cells):
        start = cursor
        end = start + len(cell)
        offsets.append((start, end))
        cursor = end + (len(TABLE_ROW_JOINER) if index < len(source_cells) - 1 else 0)

    highlighted_cells: list[str] = []
    for cell_text, (cell_start, cell_end) in zip(source_cells, offsets):
        local_spans: list[dict] = []
        for span in spans:
            span_start = int(span.get("start", 0))
            span_end = int(span.get("end", 0))
            if span_end <= cell_start or span_start >= cell_end:
                continue
            local_spans.append(
                {
                    "start": max(span_start, cell_start) - cell_start,
                    "end": min(span_end, cell_end) - cell_start,
                    "css": span.get("css", ""),
                }
            )
        highlighted_cells.append(apply_spans(cell_text, local_spans))

    return highlighted_cells


def _format_locality_label(locality: dict | None) -> str:
    if not locality:
        return "—"
    name = locality.get("name")
    if not name:
        return "—"
    locality_type = locality.get("type")
    display_name = str(name).replace("-", " ").title()
    if locality_type:
        return f"{locality_type}. {display_name}"
    return display_name


def _locality_mismatch_comment(match_result: dict) -> str:
    query_locality = _format_locality_label(match_result.get("subdivision_locality_query"))
    candidate_locality = _format_locality_label(match_result.get("subdivision_locality_candidate"))
    return (
        "Населённый пункт не совпадает: "
        f"в тексте '({query_locality})', в БД '({candidate_locality})'."
    )


def _build_comments(match_result: dict) -> list[str]:
    comments = []
    extracted_subdivision_name = match_result.get("extracted_subdivision_name")
    if not match_result.get("matched"):
        message = match_result.get("diffs", {}).get("message") or "Событие не найдено."
        comments.append(message)
        if match_result.get("date_time_present") and not match_result.get("time_found"):
            comments.append("Не определилось время (использована только дата).")
        if extracted_subdivision_name is None:
            comments.append("Подразделение не определено в сводке.")
        if match_result.get("subdivision_locality_mismatch"):
            comments.append(_locality_mismatch_comment(match_result))
        debug_meta = match_result.get("debug") or {}
        if debug_meta:
            stage_counts = ", ".join(
                f"{item.get('stage')}={item.get('count', 0)}"
                for item in (debug_meta.get("candidate_stages") or [])
            ) or "—"
            comments.append(
                "Отладка подбора: "
                f"candidates={debug_meta.get('candidates_total', 0)}; "
                "subdivision candidates "
                f"total={debug_meta.get('subdivision_candidates_total', 0)}, "
                f"after PU={debug_meta.get('subdivision_candidates_after_pu_filter', 0)}, "
                f"fallback={debug_meta.get('pu_filter_fallback_used', False)}, "
                f"pu={debug_meta.get('selected_pu_id') or '—'}; "
                f"stage1 score={debug_meta.get('stage1_best_score', 0)}/"
                f"{debug_meta.get('score_threshold', 2)}, "
                f"high_conf={debug_meta.get('subdivision_confidence_high', False)}, "
                f"stages: {stage_counts}; "
                f"method={debug_meta.get('chosen_method') or '—'}."
            )
        return comments

    diffs = match_result.get("diffs", {})
    if not diffs:
        comments.append("Расхождений не обнаружено.")
    if "subdivision" in diffs and extracted_subdivision_name:
        comments.append("Подразделение не совпадает с БД.")
    elif extracted_subdivision_name is None:
        comments.append("Подразделение не определено в сводке.")
    if match_result.get("subdivision_locality_mismatch"):
        comments.append(_locality_mismatch_comment(match_result))
    if "offenders" in diffs:
        comments.append("Нарушители отличаются от данных БД.")
    if match_result.get("event_type_ok") is False:
        comments.append("Тип события отличается от классификации.")
    article_status = match_result.get("article_status")
    article_ok = match_result.get("article_ok")
    article_classifier_ok = match_result.get("article_classifier_ok")
    if article_ok is False:
        comments.append("Статья закона отличается от данных БД.")
    elif article_ok is True and article_classifier_ok is False:
        comments.append("Статья закона отличается от классификации.")

    classifier_article_raw = (
        match_result.get("classifier_article_of_law")
        or (match_result.get("predicted") or {}).get("classifier_article_of_law")
    )
    if article_classifier_ok is False:
        classifier_article = _display_article(classifier_article_raw)
        if classifier_article:
            comments.append(f"По классификатору ожидается: {classifier_article}.")
    if match_result.get("svodka_article_of_law") is None and article_status in {"red", "yellow"}:
        comments.append("Статья закона не определена в тексте сводки.")
    if match_result.get("time_mismatch"):
        date_diff = (diffs.get("date_time") or {})
        if date_diff.get("message"):
            comments.append(date_diff["message"])
        if date_diff.get("delta_minutes") is not None:
            comments.append(
                f"Δ времени: {date_diff['delta_minutes']} мин. "
                f"Извлечено: {date_diff.get('extracted') or '—'}, "
                f"портал: {date_diff.get('portal') or '—'}."
            )
    delta_minutes = match_result.get("time_delta_minutes")
    if delta_minutes is not None and abs(delta_minutes) > TIME_ERROR_MINUTES:
        comments.append(
            "Ошибка: расхождение даты/времени на "
            f"{delta_minutes} мин (более {TIME_ERROR_MINUTES} мин)."
        )
    offender_report = _build_offender_report(match_result)
    if offender_report.get("summary"):
        comments.append(f"{offender_report['summary']}.")
    if match_result.get("date_time_present") and not match_result.get("time_found"):
        comments.append("Не определилось время (использована только дата).")
    return comments


def _status_from_flag(flag: bool | None) -> str:
    return status_from_flag(flag)



def _score_to_percent(score: object) -> int:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0
    return int(round(max(0.0, min(1.0, value)) * 100))

def _display_article(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null" or text in {"-", "—"}:
        return None
    return text


def _build_event_card(paragraph: AnalysisParagraph) -> dict:
    result = paragraph.result
    extracted = result.extracted_attributes or {}
    match_result = result.match_result or {}
    text = paragraph.text

    needs_backfill = (
        not match_result
        or "event_type_ok" not in match_result
        or "article_ok" not in match_result
        or "article_classifier_ok" not in match_result
        or "article_status" not in match_result
        or "article_spans" not in extracted
        or "date_span" not in extracted
        or "time_span" not in extracted
        or (
            match_result.get("matched") is True
            and (
                not isinstance(match_result.get("predicted"), dict)
                or match_result.get("predicted", {}).get("event_type") is None
                or match_result.get("predicted", {}).get("classifier_article_of_law") is None
            )
        )
    )
    if needs_backfill:
        try:
            paragraph_run = getattr(paragraph, "run", None)
            selected_pu_id = getattr(paragraph_run, "selected_pu_id", None)
            extracted_attrs = extract_attributes(text, selected_pu_id=selected_pu_id)
            new_match_result = match_event(extracted_attrs, text)
            extracted = {
                "date_time": format_local_naive(extracted_attrs.date_time),
                "time_found": extracted_attrs.time_found,
                "date_span": list(extracted_attrs.date_span) if extracted_attrs.date_span else None,
                "time_span": list(extracted_attrs.time_span) if extracted_attrs.time_span else None,
                "subdivision_id": extracted_attrs.subdivision_id,
                "subdivision_name": extracted_attrs.subdivision_name,
                "subdivision_candidates": extracted_attrs.subdivision_candidates,
                "subdivision_span": extracted_attrs.subdivision_span,
                "article_spans": [list(span) for span in extracted_attrs.article_spans],
                "offenders": [offender_to_json(offender) for offender in extracted_attrs.offenders],
                "staff": extracted_attrs.staff,
            }
            match_result = new_match_result
            result.extracted_attributes = extracted
            result.match_result = new_match_result
            refreshed_matched = bool(new_match_result.get("matched"))
            refreshed_title, refreshed_preview = build_title_preview(paragraph.idx, text, refreshed_matched)
            refreshed_status = compute_status_fields(new_match_result, time_error_minutes=TIME_ERROR_MINUTES)
            result.matched = refreshed_matched
            result.title = refreshed_title
            result.preview = refreshed_preview
            result.status_timestamp = refreshed_status["timestamp"]
            result.status_subdivision = refreshed_status["subdivision"]
            result.status_offenders = refreshed_status["offenders"]
            result.status_event_type = refreshed_status["event_type"]
            result.status_article = refreshed_status["article"]
            result.detail_payload_cache = {}
            result.detail_payload_cached_at = None
            result.save(update_fields=["extracted_attributes", "match_result", "matched", "title", "preview", "status_timestamp", "status_subdivision", "status_offenders", "status_event_type", "status_article", "detail_payload_cache", "detail_payload_cached_at"])
        except Exception:  # noqa: BLE001 - page should remain renderable
            match_result = result.match_result or match_result
    matched = bool(match_result.get("matched"))
    title, preview = build_title_preview(paragraph.idx, text, matched)
    portal = match_result.get("portal") or {}
    predicted = match_result.get("predicted") or {}
    best_pattern_text = predicted.get("best_pattern_text")
    if not best_pattern_text and isinstance(predicted.get("event_pattern"), dict):
        best_pattern_text = predicted.get("event_pattern", {}).get("pattern_text")

    classifier_candidates = (
        predicted.get("classifier_pattern_candidates")
        or predicted.get("classifier_candidates")
        or []
    )
    candidates_were_missing = bool(best_pattern_text and not classifier_candidates)
    if candidates_were_missing:
        try:
            predicted = ensure_classifier_candidates(predicted, text)
            classifier_candidates = (
                predicted.get("classifier_pattern_candidates")
                or predicted.get("classifier_candidates")
                or []
            )
            if classifier_candidates:
                match_result["predicted"] = predicted
                predicted_article = predicted.get("classifier_article_of_law")
                if predicted_article:
                    match_result["classifier_article_of_law"] = predicted_article
                result.match_result = match_result
                result.detail_payload_cache = {}
                result.detail_payload_cached_at = None
                result.save(update_fields=["match_result", "detail_payload_cache", "detail_payload_cached_at"])
        except Exception:  # noqa: BLE001 - detail page should remain renderable
            classifier_candidates = []

    classifier_article = (
        match_result.get("classifier_article_of_law")
        or predicted.get("classifier_article_of_law")
    )
    extracted_dt = parse_datetime(extracted.get("date_time") or "")
    portal_dt = parse_datetime(portal.get("timestamp") or "")
    extracted_timestamp_display = match_result.get(
        "extracted_timestamp_display"
    ) or format_dt_dmy_hm(extracted_dt)
    portal_timestamp_display = match_result.get("portal_timestamp_display") or format_dt_dmy_hm(
        portal_dt
    )

    subdivision_candidates = extracted.get("subdivision_candidates") or []
    formatted_candidates = []
    for candidate in subdivision_candidates:
        formatted_candidates.append(
            {
                "portal_subdivision_id": candidate.get("portal_subdivision_id"),
                "name": candidate.get("name"),
                "score": round(candidate.get("score", 0) * 100, 2)
                if candidate.get("score") is not None
                else None,
                "score_percent": candidate.get("score_percent"),
                "semantic_score": round(candidate.get("semantic_score", 0) * 100, 2)
                if candidate.get("semantic_score") is not None
                else None,
                "lexical_factor": candidate.get("lexical_factor"),
                "flags": candidate.get("flags"),
                "query_locality": candidate.get("query_locality"),
                "candidate_locality": candidate.get("candidate_locality"),
                "locality_mismatch": candidate.get("locality_mismatch"),
            }
        )

    offender_report = _build_offender_report(match_result)
    not_found = not matched

    source_kind = getattr(paragraph, "source_kind", "paragraph") or "paragraph"
    source_cells = getattr(paragraph, "source_cells", None)
    source_table_header_cells = getattr(paragraph, "source_table_header_cells", None)
    padded_source_cells = source_cells
    padded_source_table_header_cells = source_table_header_cells
    highlighted_cells = None
    if source_kind == "table_row" and isinstance(source_cells, list):
        header_cells = source_table_header_cells if isinstance(source_table_header_cells, list) else []
        max_cols = max(len(source_cells), len(header_cells))
        padded_source_cells = source_cells + ([""] * (max_cols - len(source_cells)))
        padded_source_table_header_cells = (
            header_cells + ([""] * (max_cols - len(header_cells)))
            if header_cells
            else None
        )
        highlighted_cells = _build_table_row_highlighted_cells(source_cells, extracted, match_result)
        highlighted_cells = highlighted_cells + ([apply_spans("", [])] * (max_cols - len(highlighted_cells)))

    classifier_candidates = predicted.get("classifier_pattern_candidates") or predicted.get("classifier_candidates") or []
    formatted_classifier_candidates = [
        {
            "event_type_id": item.get("event_type_id"),
            "event_type_name": item.get("event_type_name"),
            "score": item.get("score"),
            "score_percent": item.get("score_percent") if item.get("score_percent") is not None else _score_to_percent(item.get("score")),
            "pattern_text": item.get("pattern_text"),
            "matched_fragment": item.get("matched_fragment"),
            "text_article": _display_article(item.get("text_article")) or _display_article(predicted.get("article_of_law")),
            "classifier_article": _display_article(item.get("classifier_article") or item.get("article")),
        }
        for item in classifier_candidates
    ]
    similar_candidates = predicted.get("classifier_similar_candidates") or []
    formatted_similar_candidates = [
        {
            "event_type_id": item.get("event_type_id"),
            "event_type_name": item.get("event_type_name"),
            "pattern_text": item.get("pattern_text"),
            "classifier_article": _display_article(item.get("classifier_article") or item.get("article")),
            "score_percent": item.get("score_percent") if item.get("score_percent") is not None else _score_to_percent(item.get("score")),
        }
        for item in similar_candidates
    ]
    predicted["classifier_candidates"] = formatted_classifier_candidates
    predicted["classifier_pattern_candidates"] = formatted_classifier_candidates
    predicted["classifier_similar_candidates"] = formatted_similar_candidates

    classifier_best = predicted.get("classifier_best") or {}
    classifier_best_payload = None
    if isinstance(classifier_best, dict) and classifier_best:
        classifier_best_payload = {
            "event_type_id": classifier_best.get("event_type_id"),
            "event_type_name": classifier_best.get("event_type_name"),
            "score": classifier_best.get("score"),
            "score_percent": _score_to_percent(classifier_best.get("score")),
            "pattern_text": classifier_best.get("pattern_text"),
            "classifier_article": _display_article(classifier_best.get("classifier_article")),
        }

    return {
        "idx": paragraph.idx,
        "title": title,
        "not_found": not_found,
        "preview": preview,
        "full_text": text,
        "source_kind": source_kind,
        "source_cells": padded_source_cells,
        "source_table_header_cells": padded_source_table_header_cells,
        "highlighted_cells": highlighted_cells,
        "highlighted_html": _build_highlighted_html(text, extracted, match_result),
        "extracted_timestamp_display": extracted_timestamp_display,
        "portal_timestamp_display": portal_timestamp_display,
        "extracted": {
            "date_time": extracted_timestamp_display,
            "subdivision_name": extracted.get("subdivision_name"),
            "subdivision_candidates": formatted_candidates,
            "offenders": _format_offenders_with_status(
                extracted.get("offenders") or [],
                match_result=match_result,
                source="svodka",
            ),
            "staff": [item.get("display") for item in (extracted.get("staff") or []) if item.get("display")],
        },
        "match": {
            "matched": bool(match_result.get("matched")),
            "time_delta_minutes": match_result.get("time_delta_minutes"),
            "offenders_score_percent": match_result.get("offenders_score_percent"),
            "offenders_counts": match_result.get("offenders_counts") or {},
            "offenders_summary": offender_report.get("summary"),
            "offenders_details": offender_report.get("details"),
            "subdivision_match_percent": match_result.get("subdivision_match_percent"),
        },
        "portal": {
            "timestamp": portal_timestamp_display,
            "subdivision_name": portal.get("subdivision_name"),
            "offenders": _format_offenders(portal.get("offenders") or [], source="portal"),
            "event_type": portal.get("event_type"),
            "article_of_law": _display_article(portal.get("article_of_law")),
        },
        "predicted": {
            "event_type": predicted.get("event_type"),
            "article_of_law": _display_article(predicted.get("article_of_law")),
            "classifier_article_of_law": _display_article(classifier_article),
            "classifier_best": classifier_best_payload,
            "best_pattern_text": best_pattern_text,
            "best_pattern_fragment": predicted.get("best_pattern_fragment"),
            "classifier_candidates": formatted_classifier_candidates,
            "classifier_pattern_candidates": formatted_classifier_candidates,
            "classifier_similar_candidates": formatted_similar_candidates,
            "classifier_similar_min_score_used": predicted.get("classifier_similar_min_score_used"),
            "classifier_similar_limit_used": predicted.get("classifier_similar_limit_used"),
            "classifier_min_score_used": predicted.get("classifier_min_score_used"),
        },
        "status": compute_status_fields(match_result, time_error_minutes=TIME_ERROR_MINUTES),
        "comments": _build_comments(match_result),
    }




def _empty_event_payload(idx: int) -> dict:
    return {
        "idx": idx,
        "title": "",
        "preview": "",
        "source_kind": "paragraph",
        "source_cells": [],
        "source_table_header_cells": [],
        "highlighted_cells": [],
        "highlighted_html": "<p>—</p>",
        "extracted_timestamp_display": "—",
        "portal_timestamp_display": "—",
        "extracted": {"subdivision_name": "—", "subdivision_candidates": [], "offenders": [], "staff": []},
        "portal": {"subdivision_name": "—", "offenders": [], "event_type": "—", "article_of_law": "—"},
        "predicted": {
            "event_type": "—",
            "article_of_law": "—",
            "classifier_article_of_law": "—",
            "best_pattern_text": "—",
            "classifier_candidates": [],
            "classifier_pattern_candidates": [],
            "classifier_similar_candidates": [],
            "pattern_event_types": [],
        },
        "match": {
            "matched": False,
            "time_delta_minutes": None,
            "offenders_summary": None,
            "offenders_details": [],
            "subdivision_match_percent": None,
        },
        "status": {"timestamp": "neutral", "subdivision": "neutral", "offenders": "neutral", "event_type": "neutral", "article": "neutral"},
        "comments": [],
    }

class UploadView(View):
    template_name = "analysis_app/upload.html"

    @staticmethod
    def _queue_queryset(request):
        queryset = AnalysisRun.objects.filter(
            status__in=[
                AnalysisRun.Status.QUEUED,
                AnalysisRun.Status.RUNNING,
                AnalysisRun.Status.DONE,
                AnalysisRun.Status.FAILED,
            ]
        )
        if request.user.is_authenticated:
            queryset = queryset.filter(uploaded_by=request.user)
        else:
            queryset = queryset.filter(created_session_key=UploadView._ensure_session_key(request))
        return queryset.order_by("-created_at")

    def _queue_page(self, request, page_size: int = 20):
        paginator = Paginator(self._queue_queryset(request), page_size)
        page_number = request.GET.get("queue_page", "1")
        try:
            page_obj = paginator.page(page_number)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages or 1)
        for run in page_obj.object_list:
            run.elapsed_seconds = compute_elapsed_seconds(run)
            run.elapsed_display = format_elapsed(run.elapsed_seconds)
            run.started_at_display = _queue_started_at_display(run)
            run.results_url = _results_url(run)
            ui_debug_enabled = is_admin_ui(request) and FeatureFlags.is_effective_debug_enabled()
            run.debug_zip_url = _debug_zip_url(run) if ui_debug_enabled else ""
            progress_payload = _progress_payload(run)
            run.progress_total = progress_payload["progress_total"]
            run.progress_done = progress_payload["progress_done"]
            run.progress_percent = progress_payload["progress_percent"]
            run.progress_label = progress_payload["progress_label"]
            run.debug_pipeline_payload = _debug_pipeline_payload(run)
        return paginator, page_obj

    @staticmethod
    def _ensure_session_key(request) -> str:
        if request.session.session_key:
            return request.session.session_key
        request.session.create()
        return str(request.session.session_key or "")

    def _build_context(
        self,
        request,
        *,
        upload_form=None,
        selected_run_id=None,
        pending_selection_forms=None,
    ):
        if pending_selection_forms is None:
            pending_selection_forms = self._build_pending_selection_forms(request)
        queue_paginator, queue_page_obj = self._queue_page(request)
        active_templates = SvodkaTemplate.objects.filter(is_active=True).only("template_id", "scope", "pu_id")
        preview_by_pu: dict[str, str] = {}
        for template in active_templates:
            key = "" if template.scope == SvodkaTemplate.Scope.GENERAL else str(template.pu_id)
            preview_by_pu[key] = reverse("analysis-template-preview", kwargs={"template_id": template.template_id})

        return {
            "upload_form": upload_form or UploadDocxWithPuForm(),
            "queue_page_obj": queue_page_obj,
            "queue_paginator": queue_paginator,
            "queue_page_param_name": "queue_page",
            "pending_selection_forms": pending_selection_forms,
            "selected_run_id": str(selected_run_id) if selected_run_id else "",
            "queue_status_url": redirect("analysis-queue-status").url,
            "debug_mode": is_admin_ui(request) and FeatureFlags.is_effective_debug_enabled(),
            "template_preview_by_pu": preview_by_pu,
            "template_preview_by_pu_json": json.dumps(preview_by_pu),
        }

    def _pending_runs(self, request, limit: int = 20):
        queryset = AnalysisRun.objects.filter(status=AnalysisRun.Status.CREATED)
        if request.user.is_authenticated:
            queryset = queryset.filter(uploaded_by=request.user)
        else:
            queryset = queryset.filter(created_session_key=self._ensure_session_key(request))
        return queryset.order_by("-created_at")[:limit]

    def _build_pending_selection_forms(self, request, *, forms_by_run_id=None):
        pending_forms = []
        forms_by_run_id = forms_by_run_id or {}
        for run in self._pending_runs(request):
            form = forms_by_run_id.get(str(run.run_id))
            if form is None:
                form = PuSelectionForm(
                    initial={
                        "upload_id": run.run_id,
                        "selected_pu_id": run.selected_pu_id or "",
                    }
                )
            pending_forms.append(
                {
                    "run": run,
                    "form": form,
                }
            )
        return pending_forms

    def get(self, request):
        selected_run_id = request.GET.get("run")
        return render(
            request,
            self.template_name,
            self._build_context(request, selected_run_id=selected_run_id),
        )

    def post(self, request):
        if "upload_id" in request.POST:
            return self._enqueue_pending_run(request)

        return self._handle_upload(request)

    def _enqueue_run(self, run: AnalysisRun, *, selected_pu_id: str):
        run.status = AnalysisRun.Status.QUEUED
        run.queued_at = timezone.now()
        run.error_message = ""
        run.save(update_fields=["status", "queued_at", "error_message"])

        if getattr(settings, "ANALYSIS_USE_SYNC_TASKS", False):
            from apps.analysis_app.services import run_analysis_pipeline
            from apps.analysis_app.tasks import cleanup_run_upload

            run.status = AnalysisRun.Status.RUNNING
            run.started_at = timezone.now()
            run.progress_total = None
            run.progress_done = 0
            run.progress_updated_at = timezone.now()
            run.save(update_fields=["status", "started_at", "progress_total", "progress_done", "progress_updated_at"])
            try:
                total_events = run_analysis_pipeline(run, selected_pu_id=selected_pu_id or None)
                run.status = AnalysisRun.Status.DONE
                run.finished_at = timezone.now()
                run.progress_done = run.progress_total if run.progress_total is not None else total_events
                run.save(update_fields=["status", "finished_at", "progress_done"])
            except Exception as exc:  # noqa: BLE001
                run.status = AnalysisRun.Status.FAILED
                run.error_message = str(exc)
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "error_message", "finished_at"])
            cleanup_run_upload(run)
            return

        from apps.analysis_app.tasks import run_docx_analysis

        task = run_docx_analysis.delay(str(run.run_id), selected_pu_id or None)
        logger.debug("Enqueued analysis task run_id=%s task_id=%s", run.run_id, task.id)
        run.celery_task_id = task.id
        run.save(update_fields=["celery_task_id"])

    def _handle_upload(self, request):
        logger.debug(
            "Upload request started user_id=%s files_in_request=%s",
            request.user.id if request.user.is_authenticated else None,
            len(request.FILES.getlist("file")),
        )
        upload_form = UploadDocxWithPuForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            return render(request, self.template_name, self._build_context(request, upload_form=upload_form))

        files = [uploaded_file for uploaded_file in request.FILES.getlist("file") if uploaded_file]
        if not files:
            files = [uploaded_file for uploaded_file in upload_form.cleaned_data["file"] if uploaded_file]

        selected_pu_id = str(upload_form.cleaned_data.get("selected_pu_id") or "")
        selected_pu_name = _resolve_selected_pu_name(request, selected_pu_id)
        created_session_key = self._ensure_session_key(request)

        selected_run_id = None
        for uploaded_file in files:
            run = AnalysisRun.objects.create(
                uploaded_by=request.user if request.user.is_authenticated else None,
                created_session_key=created_session_key,
                file=uploaded_file,
                original_filename=os.path.basename(uploaded_file.name or ""),
                selected_pu_id=selected_pu_id,
                selected_pu_name=selected_pu_name,
                status=AnalysisRun.Status.CREATED,
                error_message="",
            )
            logger.debug("Upload created pending analysis run run_id=%s", run.run_id)
            selected_run_id = selected_run_id or run.run_id

        upload_url = redirect("analysis-upload").url
        if selected_run_id:
            return redirect(f"{upload_url}?run={selected_run_id}")
        return redirect(upload_url)

    def _enqueue_pending_run(self, request):
        selection_form = PuSelectionForm(request.POST)
        if not selection_form.is_valid():
            pending_forms = self._build_pending_selection_forms(
                request,
                forms_by_run_id={str(request.POST.get("upload_id") or ""): selection_form},
            )
            return render(request, self.template_name, self._build_context(request, pending_selection_forms=pending_forms))

        run_id = selection_form.cleaned_data["upload_id"]
        run = get_object_or_404(AnalysisRun, run_id=run_id, status=AnalysisRun.Status.CREATED)

        if request.user.is_authenticated:
            if run.uploaded_by_id != request.user.id:
                return redirect("analysis-upload")
        elif run.created_session_key != self._ensure_session_key(request):
            return redirect("analysis-upload")

        selected_pu_uuid = selection_form.cleaned_data.get("selected_pu_id")
        selected_pu_id = str(selected_pu_uuid or "")
        selected_pu_name = _resolve_selected_pu_name(request, selected_pu_id)

        run.selected_pu_id = selected_pu_id
        run.selected_pu_name = selected_pu_name
        run.save(update_fields=["selected_pu_id", "selected_pu_name"])
        self._enqueue_run(run, selected_pu_id=selected_pu_id)

        upload_url = redirect("analysis-upload").url
        queue_page = request.GET.get("queue_page") or request.POST.get("queue_page")
        query = [f"run={run.run_id}"]
        if queue_page:
            query.append(f"queue_page={queue_page}")
        return redirect(f"{upload_url}?{'&'.join(query)}")


class PendingRunCancelView(View):
    http_method_names = ["post"]

    def post(self, request, run_id):
        run = get_object_or_404(AnalysisRun, run_id=run_id)

        if request.user.is_authenticated:
            if run.uploaded_by_id != request.user.id:
                return redirect("analysis-upload")
        elif run.created_session_key != UploadView._ensure_session_key(request):
            return redirect("analysis-upload")

        if run.status == AnalysisRun.Status.CREATED and not run.celery_task_id:
            run.status = AnalysisRun.Status.CANCELED
            run.error_message = "Canceled by operator"
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])

        next_url = request.POST.get("next")
        if next_url:
            return redirect(next_url)

        upload_url = redirect("analysis-upload").url
        queue_page = request.POST.get("queue_page") or request.GET.get("queue_page")
        if queue_page:
            return redirect(f"{upload_url}?queue_page={queue_page}")
        return redirect(upload_url)


class PendingRunsStartAllView(UploadView):
    http_method_names = ["post"]

    def post(self, request):
        pending_queryset = AnalysisRun.objects.filter(status=AnalysisRun.Status.CREATED)
        if request.user.is_authenticated:
            pending_queryset = pending_queryset.filter(uploaded_by=request.user)
        else:
            pending_queryset = pending_queryset.filter(created_session_key=self._ensure_session_key(request))

        started_count = 0
        for run_id in pending_queryset.values_list("run_id", flat=True):
            with transaction.atomic():
                run = AnalysisRun.objects.select_for_update().get(run_id=run_id)
                if run.status != AnalysisRun.Status.CREATED:
                    continue
                if request.user.is_authenticated:
                    if run.uploaded_by_id != request.user.id:
                        continue
                elif run.created_session_key != self._ensure_session_key(request):
                    continue
                self._enqueue_run(run, selected_pu_id=str(run.selected_pu_id or ""))
                started_count += 1

        messages.success(request, f"Запущено в очередь: {started_count}")
        upload_url = redirect("analysis-upload").url
        queue_page = request.POST.get("queue_page") or request.GET.get("queue_page")
        if queue_page:
            return redirect(f"{upload_url}?queue_page={queue_page}")
        return redirect(upload_url)

class PendingRunsDeleteAllView(View):
    http_method_names = ["post"]

    def post(self, request):
        pending_queryset = AnalysisRun.objects.filter(status=AnalysisRun.Status.CREATED)
        if request.user.is_authenticated:
            pending_queryset = pending_queryset.filter(uploaded_by=request.user)
        else:
            pending_queryset = pending_queryset.filter(created_session_key=UploadView._ensure_session_key(request))

        deleted_count = 0
        for run_id in pending_queryset.values_list("run_id", flat=True):
            run = AnalysisRun.objects.filter(run_id=run_id).first()
            if run is None or not _user_can_manage_run(request, run):
                continue

            upload_name = str(run.file.name or "")
            debug_package_name = str(run.debug_package_file.name or "")
            with transaction.atomic():
                run = AnalysisRun.objects.select_for_update().filter(run_id=run_id).first()
                if run is None or run.status != AnalysisRun.Status.CREATED:
                    continue
                run.status = AnalysisRun.Status.CANCELED
                run.error_message = "Canceled and deleted by operator"
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "error_message", "finished_at"])
                run.delete()
                _delete_run_files_after_commit(upload_name=upload_name, debug_package_name=debug_package_name)
                deleted_count += 1

        messages.success(request, f"Удалено ожидающих запусков: {deleted_count}")
        upload_url = redirect("analysis-upload").url
        queue_page = request.POST.get("queue_page") or request.GET.get("queue_page")
        if queue_page:
            return redirect(f"{upload_url}?queue_page={queue_page}")
        return redirect(upload_url)



def _user_can_manage_run(request, run: AnalysisRun) -> bool:
    if request.user.is_authenticated:
        return bool(request.user.is_staff or run.uploaded_by_id == request.user.id)
    return run.created_session_key == UploadView._ensure_session_key(request)


def _build_delete_action_url(request) -> str:
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return next_url
    upload_url = redirect("analysis-upload").url
    queue_page = request.POST.get("queue_page") or request.GET.get("queue_page")
    if queue_page:
        return f"{upload_url}?queue_page={queue_page}"
    return upload_url


def _delete_run_files_after_commit(*, upload_name: str, debug_package_name: str) -> None:
    def _cleanup() -> None:
        for file_name in [upload_name, debug_package_name]:
            if not file_name:
                continue
            try:
                default_storage.delete(file_name)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to delete run artifact file=%s", file_name, exc_info=True)

    transaction.on_commit(_cleanup)


class AnalysisRunDeleteView(View):
    http_method_names = ["post"]

    def post(self, request, run_id):
        run = get_object_or_404(AnalysisRun, run_id=run_id)
        if not _user_can_manage_run(request, run):
            return redirect("analysis-upload")

        revoke_task_id = run.celery_task_id or ""
        revoke_terminate = run.status == AnalysisRun.Status.RUNNING
        upload_name = str(run.file.name or "")
        debug_package_name = str(run.debug_package_file.name or "")

        if revoke_task_id:
            from config.celery import app as celery_app

            try:
                celery_app.control.revoke(revoke_task_id, terminate=revoke_terminate)
                logger.info(
                    "Revoke requested for run_id=%s task_id=%s terminate=%s",
                    run.run_id,
                    revoke_task_id,
                    revoke_terminate,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to revoke run_id=%s task_id=%s terminate=%s",
                    run.run_id,
                    revoke_task_id,
                    revoke_terminate,
                    exc_info=True,
                )

        with transaction.atomic():
            run = AnalysisRun.objects.select_for_update().get(run_id=run_id)
            if run.status in [AnalysisRun.Status.RUNNING, AnalysisRun.Status.QUEUED, AnalysisRun.Status.CREATED]:
                run.status = AnalysisRun.Status.CANCELED
                run.error_message = "Canceled and deleted by operator"
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "error_message", "finished_at"])
            run.delete()
            _delete_run_files_after_commit(upload_name=upload_name, debug_package_name=debug_package_name)

        return redirect(_build_delete_action_url(request))


class AnalysisQueueView(UploadView):
    template_name = "analysis_app/queue.html"

    def get(self, request):
        context = self._build_context(request)
        return render(request, self.template_name, context)



class AnalysisQueueStatusView(View):
    def get(self, request):
        debug_mode = is_admin_ui(request) and FeatureFlags.is_effective_debug_enabled()
        runs = list(UploadView._queue_queryset(request)[:10])
        payload_runs = []
        for run in runs:
            elapsed_seconds = compute_elapsed_seconds(run)
            progress_payload = _progress_payload(run)
            payload = {
                "run_id": str(run.run_id),
                "original_filename": run.original_filename or _display_filename(run.file.name),
                "selected_pu_name": run.selected_pu_name,
                "status": run.status,
                "queued_at": run.queued_at.isoformat() if run.queued_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "elapsed_seconds": elapsed_seconds,
                "elapsed_display": format_elapsed(elapsed_seconds),
                "started_at_display": _queue_started_at_display(run),
                "queued_at_display": format_run_started_at(run.queued_at),
                "elapsed": format_elapsed(elapsed_seconds),
                "results_url": _results_url(run),
                "has_results": bool(_results_url(run)),
                "debug_zip_url": _debug_zip_url(run) if debug_mode else "",
                "debug_available": bool(_debug_zip_url(run)) if debug_mode else False,
                "error_message": run.error_message if run.status in [AnalysisRun.Status.FAILED, AnalysisRun.Status.CANCELED] else None,
                "position": None,
                "progress_total": progress_payload["progress_total"],
                "progress_done": progress_payload["progress_done"],
                "progress_percent": progress_payload["progress_percent"],
                "percent": progress_payload["progress_percent"],
                "progress_label": progress_payload["progress_label"],
                "updated_at": run.progress_updated_at.isoformat() if run.progress_updated_at else run.updated_at.isoformat(),
            }
            if debug_mode:
                payload["debug_pipeline"] = _debug_pipeline_payload(run)
            if run.status == AnalysisRun.Status.RUNNING:
                payload["position"] = 0
            elif run.status == AnalysisRun.Status.QUEUED:
                queue_base = run.queued_at or run.created_at
                older_count = AnalysisRun.objects.filter(
                    status__in=[AnalysisRun.Status.RUNNING, AnalysisRun.Status.QUEUED],
                    queued_at__lt=queue_base,
                ).count()
                payload["position"] = older_count + 1
            payload_runs.append(payload)

        return JsonResponse({"runs": payload_runs})


class AnalysisStatusView(View):
    def get(self, request, run_id):
        run = get_object_or_404(AnalysisRun, run_id=run_id)

        elapsed_seconds = compute_elapsed_seconds(run)

        if getattr(settings, "ANALYSIS_USE_SYNC_TASKS", False):
            worker_ok = True
        else:
            from config.celery import app as celery_app

            worker_response = celery_app.control.inspect(timeout=1).ping() or {}
            worker_ok = bool(worker_response)

        payload = {
            "status": run.status,
            "queued_at": run.queued_at.isoformat() if run.queued_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_display": format_elapsed(elapsed_seconds),
            "started_at_display": _queue_started_at_display(run),
            "queued_at_display": format_run_started_at(run.queued_at),
            "error_message": run.error_message if run.status in [AnalysisRun.Status.FAILED, AnalysisRun.Status.CANCELED] else None,
            "worker_ok": worker_ok,
            "uploaded_filename": run.original_filename or _display_filename(run.file.name),
            "selected_pu_name": run.selected_pu_name,
            "selected_pu_id": run.selected_pu_id,
        }
        if run.status == AnalysisRun.Status.DONE:
            payload["result_url"] = reverse("analysis-detail", kwargs={"run_id": str(run.run_id)})
        return JsonResponse(payload)


def _get_run_for_request(run_id, request, *, allow_staff: bool = False) -> AnalysisRun:
    run = get_object_or_404(AnalysisRun, run_id=run_id)
    if request.user.is_authenticated:
        if run.uploaded_by_id != request.user.id:
            if not (allow_staff and request.user.is_staff):
                raise Http404
        return run

    session_key = UploadView._ensure_session_key(request)
    if run.created_session_key != session_key:
        raise Http404
    return run


def paragraph_to_event_json(paragraph: AnalysisParagraph) -> dict:
    return build_event_detail_payload(paragraph, builder=_build_event_card)


class AnalysisEventsListView(View):
    def get(self, request, run_id):
        run = _get_run_for_request(run_id, request, allow_staff=True)
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.GET.get("page_size", 50))
        except (TypeError, ValueError):
            page_size = 50
        page_size = max(1, min(page_size, 100))

        results = AnalysisResult.objects.filter(paragraph__run=run).select_related("paragraph").order_by("paragraph__idx")
        paginator = Paginator(results, page_size)
        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages or 1)

        items = []
        for result in page_obj.object_list:
            items.append(
                {
                    "idx": result.paragraph.idx,
                    "title": result.title,
                    "preview": result.preview,
                    "not_found": not result.matched,
                    "status": {
                        "timestamp": result.status_timestamp,
                        "subdivision": result.status_subdivision,
                        "offenders": result.status_offenders,
                        "event_type": result.status_event_type,
                        "article": result.status_article,
                    },
                }
            )

        return JsonResponse(
            {
                "run_id": str(run.run_id),
                "status": run.status,
                "total": paginator.count,
                "page": page_obj.number,
                "page_size": page_size,
                "has_next": page_obj.has_next(),
                "items": items,
            }
        )


class AnalysisEventDetailView(View):
    def get(self, request, run_id, idx):
        run = _get_run_for_request(run_id, request, allow_staff=True)
        paragraph = get_object_or_404(
            AnalysisParagraph.objects.select_related("result", "run"),
            run=run,
            idx=idx,
        )
        result = paragraph.result
        cached_payload = result.detail_payload_cache if isinstance(result.detail_payload_cache, dict) else {}
        if cached_payload:
            payload = cached_payload
        else:
            payload = paragraph_to_event_json(paragraph)
            result.detail_payload_cache = payload
            result.detail_payload_cached_at = timezone.now()
            result.save(update_fields=["detail_payload_cache", "detail_payload_cached_at"])
        pattern_event_types_map = _build_pattern_event_types_map([payload])
        predicted = payload.get("predicted") or {}
        best_pattern_text = str(predicted.get("best_pattern_text") or "").strip()
        predicted["pattern_event_types"] = pattern_event_types_map.get(best_pattern_text, [])
        payload["predicted"] = predicted
        return JsonResponse(payload)


class AnalysisDebugZipView(View):
    def get(self, request, run_id):
        if not FeatureFlags.is_effective_debug_enabled():
            raise Http404

        run = get_object_or_404(AnalysisRun, run_id=run_id)

        if request.user.is_authenticated:
            if run.uploaded_by_id != request.user.id and not request.user.is_staff:
                raise Http404
        else:
            session_key = UploadView._ensure_session_key(request)
            if run.created_session_key != session_key:
                raise Http404

        if run.debug_package_file:
            return FileResponse(
                run.debug_package_file.open("rb"),
                as_attachment=True,
                filename=f"debug_{run.run_id}.zip",
            )

        response = HttpResponse(build_debug_zip_bytes(run), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="debug_{run.run_id}.zip"'
        return response



def _is_staff_owner_or_session_user(*, request, run: AnalysisRun) -> bool:
    if request.user.is_authenticated:
        return bool(request.user.is_staff or run.uploaded_by_id == request.user.id)
    return run.created_session_key == UploadView._ensure_session_key(request)


class TemplatePreviewView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = "analysis_app/template_preview.html"

    def test_func(self):
        return bool(self.request.user and self.request.user.is_staff)

    def _render_preview(self, request, template: SvodkaTemplate):
        template_text = ""
        if template.file:
            with template.file.open("rb") as source:
                template_text = extract_template_text(source)

        preview = build_template_preview_context(template_text, template.begin_marker, template.end_marker)
        return render(
            request,
            self.template_name,
            {
                "svodka_template": template,
                "preview": preview,
            },
        )

    def get(self, request, template_id=None, pu_id=None):
        if template_id is not None:
            template = get_object_or_404(SvodkaTemplate, template_id=template_id)
            return self._render_preview(request, template)

        normalized_pu_id = str(pu_id or "").strip()
        if not normalized_pu_id:
            template = get_object_or_404(
                SvodkaTemplate,
                scope=SvodkaTemplate.Scope.GENERAL,
                pu_id="",
                is_active=True,
            )
            return self._render_preview(request, template)

        template = get_object_or_404(
            SvodkaTemplate,
            scope=SvodkaTemplate.Scope.PU,
            pu_id=normalized_pu_id,
            is_active=True,
        )
        return self._render_preview(request, template)


class AnalysisDetailView(View):
    template_name = "analysis_app/detail.html"

    def get(self, request, run_id):
        run = _get_run_for_request(run_id, request, allow_staff=True)

        selected_idx_param = request.GET.get("event")
        try:
            selected_idx = max(1, int(selected_idx_param))
        except (TypeError, ValueError):
            selected_idx = run.paragraphs.order_by("idx").values_list("idx", flat=True).first() or 1
        selected_paragraph = run.paragraphs.select_related("result", "run").filter(idx=selected_idx).first()
        selected_event = paragraph_to_event_json(selected_paragraph) if selected_paragraph else _empty_event_payload(selected_idx)
        pattern_event_types_map = _build_pattern_event_types_map([selected_event]) if selected_paragraph else {}
        predicted = selected_event.get("predicted") or {}
        best_pattern_text = str(predicted.get("best_pattern_text") or "").strip()
        predicted["pattern_event_types"] = pattern_event_types_map.get(best_pattern_text, [])
        selected_event["predicted"] = predicted

        selected_pu = None
        if run.selected_pu_id:
            selected_pu = CachedPU.objects.filter(
                portal_pu_id=run.selected_pu_id
            ).first()
        pu_label = GENERAL_SUMMARY_PU_LABEL
        if selected_pu:
            pu_label = str(selected_pu.full_name or selected_pu.short_name or pu_label)
        ui_debug_enabled = is_admin_ui(request) and FeatureFlags.is_effective_debug_enabled()
        return render(
            request,
            self.template_name,
            {
                "run": run,
                "selected_idx": selected_idx,
                "selected_event": selected_event,
                "events_list_url": reverse("analysis-events-list", kwargs={"run_id": str(run.run_id)}),
                "event_detail_url_template": reverse(
                    "analysis-event-detail", kwargs={"run_id": str(run.run_id), "idx": 0}
                ).replace("/0/", "/{idx}/"),
                "run_status_url": reverse("analysis-status", kwargs={"run_id": str(run.run_id)}),
                "detail_config": {
                    "run_id": str(run.run_id),
                    "selected_idx": selected_idx,
                    "events_list_url": reverse("analysis-events-list", kwargs={"run_id": str(run.run_id)}),
                    "event_detail_url_template": reverse(
                        "analysis-event-detail", kwargs={"run_id": str(run.run_id), "idx": 0}
                    ).replace("/0/", "/{idx}/"),
                    "status_url": reverse("analysis-status", kwargs={"run_id": str(run.run_id)}),
                    "run_status": run.status,
                },
                "selected_pu_label": pu_label,
                "debug_mode": ui_debug_enabled,
                "debug_zip_url": _debug_zip_url(run),
                "show_debug_zip_link": ui_debug_enabled and run.status in [AnalysisRun.Status.DONE, AnalysisRun.Status.FAILED] and _is_staff_owner_or_session_user(request=request, run=run),
                "debug_pipeline": _debug_pipeline_payload(run),
                "slicing_status": _slicing_status_payload(run),
                "slicing_preview": _slicing_preview_payload(run, debug_mode=ui_debug_enabled),
            },
        )
