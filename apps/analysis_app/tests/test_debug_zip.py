from io import BytesIO
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun, FeatureFlags


class AnalysisDebugZipViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pass",
        )

    def _create_run(self, **kwargs):
        run = AnalysisRun.objects.create(
            uploaded_by=self.user,
            file=ContentFile(b"dummy", name="input.docx"),
            original_filename="input.docx",
            status=AnalysisRun.Status.DONE,
            selected_pu_id="pu-1",
            selected_pu_name="ПУ 1",
            **kwargs,
        )
        paragraph = AnalysisParagraph.objects.create(
            run=run,
            idx=1,
            text="event text",
            source_kind=AnalysisParagraph.SourceKind.PARAGRAPH,
        )
        AnalysisResult.objects.create(
            paragraph=paragraph,
            extracted_attributes={"k": "v"},
            match_result={"matched": True},
        )
        return run

    def test_debug_mode_off_returns_404(self):
        run = self._create_run()
        flags = FeatureFlags.get_solo()
        flags.debug_mode = False
        flags.save(update_fields=["debug_mode", "updated_at"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("analysis-debug-zip", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 404)

    def test_debug_mode_on_owner_gets_zip_with_meta(self):
        run = self._create_run()
        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("analysis-debug-zip", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:2], b"PK")

        archive = zipfile.ZipFile(BytesIO(response.content))
        self.assertIn("meta.json", archive.namelist())

    def test_other_user_cannot_access(self):
        run = self._create_run()
        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])
        other_user = get_user_model().objects.create_user(
            username="other",
            email="other@example.com",
            password="pass",
        )

        self.client.force_login(other_user)
        response = self.client.get(reverse("analysis-debug-zip", kwargs={"run_id": run.run_id}))

        self.assertIn(response.status_code, [403, 404])
