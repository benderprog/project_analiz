import json
import zipfile
from io import BytesIO
import os
from pathlib import PurePath

from django.conf import settings
from django.db.models import F, Q

from apps.analysis_app.models import AnalysisResult, AnalysisRun


def _display_filename(file_name: str | None) -> str:
    if not file_name:
        return ""
    normalized = str(file_name).replace("\\", "/")
    return PurePath(normalized).name


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


def build_debug_zip_bytes(run: AnalysisRun) -> bytes:
    results_qs = AnalysisResult.objects.filter(paragraph__run_id=run.run_id).select_related(
        "paragraph"
    ).order_by("paragraph__idx")

    meta_payload = {
        "run_id": str(run.run_id),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "status": run.status,
        "selected_pu_id": run.selected_pu_id,
        "selected_pu_name": run.selected_pu_name,
        "original_filename": run.original_filename or _display_filename(run.file.name),
        "debug_mode": True,
        "app": _app_version_payload(),
    }

    slicing_payload = _build_slicing_payload(results_qs)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("meta.json", json.dumps(meta_payload, ensure_ascii=False, indent=2))
        archive.writestr("run.json", json.dumps(_safe_run_payload(run), ensure_ascii=False, indent=2))
        archive.writestr(
            "slicing_meta.json",
            json.dumps(run.slicing_meta if isinstance(run.slicing_meta, dict) else {}, ensure_ascii=False, indent=2),
        )

        if slicing_payload.get("template") or slicing_payload.get("items"):
            archive.writestr(
                "slicing.json",
                json.dumps(slicing_payload, ensure_ascii=False, indent=2),
            )

        for event_idx, result in enumerate(results_qs, start=1):
            paragraph = result.paragraph
            payload = {
                "idx": paragraph.idx,
                "title": f"Событие {paragraph.idx}",
                "preview": (paragraph.text or "")[:200],
                "source_kind": paragraph.source_kind,
                "source_cells": paragraph.source_cells,
                "source_table_header_cells": paragraph.source_table_header_cells,
                "full_text": paragraph.text,
                "extracted_attributes": result.extracted_attributes or {},
                "match_result": result.match_result or {},
            }
            archive.writestr(
                f"events/event_{event_idx:04d}.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )

    return buffer.getvalue()


def prune_debug_packages_for_owner(run: AnalysisRun, keep: int = 10) -> None:
    owner_filter = Q()
    if run.uploaded_by_id:
        owner_filter = Q(uploaded_by_id=run.uploaded_by_id)
    elif run.created_session_key:
        owner_filter = Q(created_session_key=run.created_session_key)
    else:
        return

    cached_runs = list(
        AnalysisRun.objects.filter(owner_filter, status__in=[AnalysisRun.Status.DONE, AnalysisRun.Status.FAILED])
        .exclude(Q(debug_package_file__isnull=True) | Q(debug_package_file=""))
        .order_by(F("finished_at").desc(nulls_last=True), "-created_at")
    )

    for stale_run in cached_runs[keep:]:
        stale_run.debug_package_file.delete(save=False)
        stale_run.debug_package_file = None
        stale_run.debug_package_created_at = None
        stale_run.save(update_fields=["debug_package_file", "debug_package_created_at"])
