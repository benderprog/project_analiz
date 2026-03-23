import logging
import time as pytime

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.analysis_app.debug_package import build_debug_zip_bytes, prune_debug_packages_for_owner
from apps.analysis_app.models import AnalysisRun, FeatureFlags
from apps.analysis_app.services import run_analysis_pipeline
from config.celery import app

logger = logging.getLogger(__name__)


def cleanup_run_upload(run: AnalysisRun) -> None:
    if not getattr(settings, "ANALYSIS_DELETE_UPLOADS", True):
        return
    if not run.file:
        return
    try:
        run.file.delete(save=False)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to cleanup uploaded file for run %s", run.run_id, exc_info=True)


@app.task(
    bind=True,
    soft_time_limit=getattr(settings, "ANALYSIS_TASK_SOFT_TIME_LIMIT", 1800),
    time_limit=getattr(settings, "ANALYSIS_TASK_TIME_LIMIT", 1860),
)
def run_docx_analysis(self, run_id: str, selected_pu_id: str | None = None) -> None:
    with transaction.atomic():
        run = AnalysisRun.objects.select_for_update().get(run_id=run_id)
        if run.status != AnalysisRun.Status.QUEUED or run.started_at is not None:
            logger.info("skip run_id=%s status=%s", run_id, run.status)
            return

        now = timezone.now()
        run.celery_task_id = self.request.id
        run.queued_at = run.queued_at or now
        run.error_message = ""
        run.status = AnalysisRun.Status.RUNNING
        run.started_at = now
        run.progress_total = None
        run.progress_done = 0
        run.progress_updated_at = now
        run.save(
            update_fields=[
                "celery_task_id",
                "queued_at",
                "error_message",
                "status",
                "started_at",
                "progress_total",
                "progress_done",
                "progress_updated_at",
            ]
        )

    last_db_update = timezone.now()
    debug_enabled = FeatureFlags.is_effective_debug_enabled()
    pipeline_started = pytime.monotonic()
    pipeline_stage = "starting"
    pipeline = {"current_stage": "starting", "stages": [], "total_ms": 0}

    def _save_pipeline(stage_name=None, stage_ms=None, *, current_stage=None, force: bool = False) -> None:
        nonlocal last_db_update, pipeline_stage
        if current_stage:
            pipeline_stage = current_stage
        if not debug_enabled:
            return
        now = timezone.now()
        if stage_name:
            stages = [item for item in pipeline.get("stages", []) if item.get("name") != stage_name]
            stages.append({"name": stage_name, "ms": int(stage_ms or 0)})
            pipeline["stages"] = stages
        if current_stage:
            pipeline["current_stage"] = current_stage
        pipeline["total_ms"] = int((pytime.monotonic() - pipeline_started) * 1000)
        pipeline["updated_at"] = now.isoformat().replace("+00:00", "Z")
        if not force and (now - last_db_update).total_seconds() < 2:
            return
        run.debug_pipeline = pipeline
        run.debug_pipeline_updated_at = now
        run.save(update_fields=["debug_pipeline", "debug_pipeline_updated_at"])
        last_db_update = now

    if debug_enabled:
        _save_pipeline(current_stage="parsing", force=True)

    def progress_callback(processed: int, total: int, *, force: bool = False) -> None:
        nonlocal last_db_update
        now = timezone.now()
        should_flush = force or processed % 5 == 0 or (now - last_db_update).total_seconds() >= 0.5
        run.progress_total = total
        run.progress_done = processed
        run.progress_updated_at = now
        if should_flush:
            run.save(update_fields=["progress_total", "progress_done", "progress_updated_at"])
            last_db_update = now
        if debug_enabled and run.status == AnalysisRun.Status.RUNNING:
            _save_pipeline(current_stage="matching", force=force or processed % 20 == 0)

    try:
        total_events = run_analysis_pipeline(
            run,
            selected_pu_id=selected_pu_id,
            progress_callback=progress_callback,
            stage_callback=_save_pipeline,
            debug_enabled=debug_enabled,
        )
        run.status = AnalysisRun.Status.DONE
        run.finished_at = timezone.now()
        run.progress_done = run.progress_total if run.progress_total is not None else total_events
        run.save(update_fields=["status", "finished_at", "progress_done"])
        if debug_enabled:
            _save_pipeline(current_stage="done", force=True)
        if debug_enabled:
            debug_bytes = build_debug_zip_bytes(run)
            filename = f"debug_{run.run_id}.zip"
            run.debug_package_file.save(filename, ContentFile(debug_bytes), save=False)
            run.debug_package_created_at = timezone.now()
            run.save(update_fields=["debug_package_file", "debug_package_created_at"])
            prune_debug_packages_for_owner(run)
    except SoftTimeLimitExceeded as exc:
        logger.warning("Document analysis soft time limit exceeded for run %s", run_id, exc_info=True)
        run.status = AnalysisRun.Status.FAILED
        timelimit = getattr(self.request, "timelimit", None)
        hard_limit = timelimit[0] if isinstance(timelimit, (list, tuple)) and len(timelimit) > 0 else None
        soft_limit = timelimit[1] if isinstance(timelimit, (list, tuple)) and len(timelimit) > 1 else None
        stage_label = pipeline_stage or "unknown"
        limit_details = ""
        if soft_limit or hard_limit:
            limit_details = f" (soft={soft_limit or '-'}s, hard={hard_limit or '-'}s)"
        run.error_message = (
            "Превышен лимит времени обработки сводки"
            f" на этапе '{stage_label}'{limit_details}."
        )
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        if debug_enabled:
            _save_pipeline(current_stage=f"timeout:{stage_label}", force=True)
            debug_bytes = build_debug_zip_bytes(run)
            filename = f"debug_{run.run_id}.zip"
            run.debug_package_file.save(filename, ContentFile(debug_bytes), save=False)
            run.debug_package_created_at = timezone.now()
            run.save(update_fields=["debug_package_file", "debug_package_created_at"])
            prune_debug_packages_for_owner(run)
        cleanup_run_upload(run)
        raise exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Document analysis failed for run %s", run_id)
        run.status = AnalysisRun.Status.FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        if debug_enabled:
            _save_pipeline(current_stage="failed", force=True)
        if debug_enabled:
            debug_bytes = build_debug_zip_bytes(run)
            filename = f"debug_{run.run_id}.zip"
            run.debug_package_file.save(filename, ContentFile(debug_bytes), save=False)
            run.debug_package_created_at = timezone.now()
            run.save(update_fields=["debug_package_file", "debug_package_created_at"])
            prune_debug_packages_for_owner(run)
        cleanup_run_upload(run)
        raise
    cleanup_run_upload(run)
