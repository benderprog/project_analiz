import logging

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


@app.task(bind=True)
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

    try:
        total_events = run_analysis_pipeline(
            run,
            selected_pu_id=selected_pu_id,
            progress_callback=progress_callback,
        )
        run.status = AnalysisRun.Status.DONE
        run.finished_at = timezone.now()
        run.progress_done = run.progress_total if run.progress_total is not None else total_events
        run.save(update_fields=["status", "finished_at", "progress_done"])
        if FeatureFlags.is_debug_enabled():
            debug_bytes = build_debug_zip_bytes(run)
            filename = f"debug_{run.run_id}.zip"
            run.debug_package_file.save(filename, ContentFile(debug_bytes), save=False)
            run.debug_package_created_at = timezone.now()
            run.save(update_fields=["debug_package_file", "debug_package_created_at"])
            prune_debug_packages_for_owner(run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("DOCX analysis failed for run %s", run_id)
        run.status = AnalysisRun.Status.FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        if FeatureFlags.is_debug_enabled():
            debug_bytes = build_debug_zip_bytes(run)
            filename = f"debug_{run.run_id}.zip"
            run.debug_package_file.save(filename, ContentFile(debug_bytes), save=False)
            run.debug_package_created_at = timezone.now()
            run.save(update_fields=["debug_package_file", "debug_package_created_at"])
            prune_debug_packages_for_owner(run)
        cleanup_run_upload(run)
        raise
    cleanup_run_upload(run)
