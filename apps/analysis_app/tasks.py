import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.analysis_app.models import AnalysisRun
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

        run.celery_task_id = self.request.id
        run.queued_at = run.queued_at or timezone.now()
        run.error_message = ""
        run.status = AnalysisRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["celery_task_id", "queued_at", "error_message", "status", "started_at"])

    try:
        run_analysis_pipeline(run, selected_pu_id=selected_pu_id)
        run.status = AnalysisRun.Status.DONE
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
    except Exception as exc:  # noqa: BLE001
        logger.exception("DOCX analysis failed for run %s", run_id)
        run.status = AnalysisRun.Status.FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        cleanup_run_upload(run)
        raise
    cleanup_run_upload(run)
