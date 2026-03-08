from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun


class UiPagesSmokeTest(TestCase):
    @patch("apps.analysis_app.forms.get_pu_choices", return_value=[])
    def test_upload_and_queue_pages_render(self, _choices_mock):
        self.assertEqual(self.client.get(reverse("analysis-upload")).status_code, 200)
        self.assertEqual(self.client.get(reverse("analysis-queue")).status_code, 200)

    def test_results_page_renders(self):
        session = self.client.session
        if not session.session_key:
            session.save()
        run = AnalysisRun.objects.create(
            file=SimpleUploadedFile("report.docx", b"test"),
            original_filename="report.docx",
            status=AnalysisRun.Status.DONE,
            created_session_key=session.session_key,
        )
        paragraph = AnalysisParagraph.objects.create(run=run, idx=1, text="event text")
        AnalysisResult.objects.create(paragraph=paragraph, match_result={"matched": True}, extracted_attributes={})

        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))
        self.assertEqual(response.status_code, 200)
