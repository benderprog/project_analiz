from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
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

        def pipeline_stub(run_obj, *, selected_pu_id=None, progress_callback=None, stage_callback=None, debug_enabled=False):
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


    def test_run_docx_analysis_does_not_store_debug_pipeline_when_debug_mode_off(self):
        run = AnalysisRun.objects.create(
            original_filename="pipeline-off.docx",
            file="uploads/pipeline-off.docx",
            status=AnalysisRun.Status.QUEUED,
            queued_at=timezone.now(),
        )
        flags = FeatureFlags.get_solo()
        flags.debug_mode = False
        flags.save(update_fields=["debug_mode", "updated_at"])

        with patch("apps.analysis_app.tasks.run_analysis_pipeline", return_value=0):
            run_docx_analysis.run(str(run.run_id), selected_pu_id=None)

        run.refresh_from_db()
        self.assertEqual(run.debug_pipeline, {})
        self.assertIsNone(run.debug_pipeline_updated_at)

    def test_run_docx_analysis_stores_debug_pipeline_when_debug_mode_on(self):
        run = AnalysisRun.objects.create(
            original_filename="pipeline-on.docx",
            file="uploads/pipeline-on.docx",
            status=AnalysisRun.Status.QUEUED,
            queued_at=timezone.now(),
        )
        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])

        def pipeline_stub(run_obj, *, selected_pu_id=None, progress_callback=None, stage_callback=None, debug_enabled=False):
            self.assertTrue(debug_enabled)
            if stage_callback:
                stage_callback(stage_name="parsing", stage_ms=120, current_stage="extraction", force=True)
                stage_callback(stage_name="extraction", stage_ms=330, current_stage="matching", force=True)
                stage_callback(stage_name="matching", stage_ms=450, current_stage="classification", force=True)
                stage_callback(stage_name="classification", stage_ms=90, current_stage="done", force=True)
            if progress_callback:
                progress_callback(1, 1, force=True)
            return 1

        with (
            patch("apps.analysis_app.tasks.run_analysis_pipeline", side_effect=pipeline_stub),
            patch("apps.analysis_app.tasks.build_debug_zip_bytes", return_value=b"zip"),
            patch("apps.analysis_app.tasks.prune_debug_packages_for_owner"),
        ):
            run_docx_analysis.run(str(run.run_id), selected_pu_id=None)

        run.refresh_from_db()
        self.assertIsNotNone(run.debug_pipeline_updated_at)
        self.assertEqual(run.debug_pipeline.get("current_stage"), "done")
        stage_names = [item.get("name") for item in run.debug_pipeline.get("stages", [])]
        self.assertEqual(stage_names, ["parsing", "extraction", "matching", "classification"])

    def test_run_docx_analysis_soft_timeout_sets_human_error(self):
        run = AnalysisRun.objects.create(
            original_filename="timeout.docx",
            file="uploads/timeout.docx",
            status=AnalysisRun.Status.QUEUED,
            queued_at=timezone.now(),
        )

        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])

        def pipeline_stub(run_obj, *, selected_pu_id=None, progress_callback=None, stage_callback=None, debug_enabled=False):
            if stage_callback:
                stage_callback(current_stage="matching", force=True)
            raise SoftTimeLimitExceeded()

        with (
            patch("apps.analysis_app.tasks.run_analysis_pipeline", side_effect=pipeline_stub),
            patch("apps.analysis_app.tasks.build_debug_zip_bytes", return_value=b"zip"),
            patch("apps.analysis_app.tasks.prune_debug_packages_for_owner"),
        ):
            with self.assertRaises(SoftTimeLimitExceeded):
                run_docx_analysis.run(str(run.run_id), selected_pu_id=None)

        run.refresh_from_db()
        self.assertEqual(run.status, AnalysisRun.Status.FAILED)
        self.assertIn("Превышен лимит времени", run.error_message)
        self.assertIn("matching", run.error_message)
        self.assertEqual(run.debug_pipeline.get("current_stage"), "timeout:matching")
