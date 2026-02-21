from unittest.mock import patch

from django.test import TestCase

from apps.analysis_app.models import AnalysisRun
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
