from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.analysis_app.models import AnalysisRun, FeatureFlags
from apps.analysis_app.tasks import run_docx_analysis


class AnalysisTasksTests(TestCase):
    def test_run_docx_analysis_skips_canceled_run(self):
        run = AnalysisRun.objects.create(
            original_filename="canceled.docx",
            file="uploads/canceled.docx",
            status=AnalysisRun.Status.CANCELED,
        )

        with patch("apps.analysis_app.tasks.run_analysis_pipeline") as pipeline_mock:
            run_docx_analysis.run(str(run.run_id), selected_pu_id=None)

        run.refresh_from_db()
        pipeline_mock.assert_not_called()
        self.assertEqual(run.status, AnalysisRun.Status.CANCELED)
        self.assertIsNone(run.started_at)

    def test_run_docx_analysis_updates_progress(self):
        run = AnalysisRun.objects.create(
            original_filename="progress.docx",
            file="uploads/progress.docx",
            status=AnalysisRun.Status.QUEUED,
            queued_at=timezone.now(),
        )

        def pipeline_stub(run_obj, *, selected_pu_id=None, progress_callback=None):
            self.assertIsNotNone(progress_callback)
            progress_callback(0, 10, force=True)
            progress_callback(3, 10, force=True)
            progress_callback(10, 10, force=True)
            return 10

        with patch("apps.analysis_app.tasks.run_analysis_pipeline", side_effect=pipeline_stub):
            run_docx_analysis.run(str(run.run_id), selected_pu_id=None)

        run.refresh_from_db()
        self.assertEqual(run.status, AnalysisRun.Status.DONE)
        self.assertEqual(run.progress_total, 10)
        self.assertEqual(run.progress_done, 10)
        self.assertIsNotNone(run.progress_updated_at)

    def test_run_docx_analysis_does_not_build_debug_package_when_debug_mode_off(self):
        run = AnalysisRun.objects.create(
            original_filename="debug-off.docx",
            file="uploads/debug-off.docx",
            status=AnalysisRun.Status.QUEUED,
            queued_at=timezone.now(),
        )
        flags = FeatureFlags.get_solo()
        flags.debug_mode = False
        flags.save(update_fields=["debug_mode", "updated_at"])

        with (
            patch("apps.analysis_app.tasks.run_analysis_pipeline", return_value=0),
            patch("apps.analysis_app.tasks.build_debug_zip_bytes") as build_mock,
        ):
            run_docx_analysis.run(str(run.run_id), selected_pu_id=None)

        run.refresh_from_db()
        self.assertEqual(run.status, AnalysisRun.Status.DONE)
        self.assertFalse(run.debug_package_file)
        self.assertIsNone(run.debug_package_created_at)
        build_mock.assert_not_called()
