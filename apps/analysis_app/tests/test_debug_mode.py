import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun, FeatureFlags


class DebugModeTests(TestCase):
    def _build_run(self) -> AnalysisRun:
        run = AnalysisRun.objects.create(
            file=SimpleUploadedFile(
                "sample.docx",
                b"PK\x03\x04",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )
        paragraph = AnalysisParagraph.objects.create(run=run, idx=1, text="event")
        AnalysisResult.objects.create(
            paragraph=paragraph,
            extracted_attributes={"foo": "bar"},
            match_result={"matched": True},
        )
        return run

    def test_feature_flags_default_false_without_row(self):
        self.assertFalse(FeatureFlags.is_enabled())

    def test_debug_zip_404_when_debug_mode_disabled(self):
        run = self._build_run()
        session = self.client.session
        session["analysis_run_ids"] = [str(run.run_id)]
        session.save()

        response = self.client.get(reverse("analysis-debug-zip", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 404)

    def test_debug_zip_200_when_debug_mode_enabled(self):
        run = self._build_run()
        FeatureFlags.objects.update_or_create(pk=1, defaults={"debug_mode": True})
        session = self.client.session
        session["analysis_run_ids"] = [str(run.run_id)]
        session.save()

        response = self.client.get(reverse("analysis-debug-zip", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.assertIn("meta.json", archive.namelist())
        self.assertIn("events/event_0001.json", archive.namelist())

    def test_upload_context_contains_debug_mode(self):
        response = self.client.get(reverse("analysis-upload"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("debug_mode", response.context)
