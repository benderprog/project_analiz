from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun, FeatureFlags, PortalDbConnectionSettings
from apps.analysis_app.ui_mode import _version_label


class UiModeTests(TestCase):
    def _create_run(self, owner):
        run = AnalysisRun.objects.create(
            uploaded_by=owner,
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            status=AnalysisRun.Status.DONE,
            slicing_meta={"analyzed_text": "line0", "fallback_to_full_report": True},
        )
        AnalysisParagraph.objects.create(run=run, idx=1, text="text")
        AnalysisResult.objects.create(paragraph=run.paragraphs.first(), extracted_attributes={}, match_result={"matched": False})
        return run

    def test_toggle_endpoint_removed(self):
        response = self.client.post("/ui/mode/")
        self.assertEqual(response.status_code, 404)

    def test_staff_gets_admin_diagnostic_layout_by_default(self):
        staff = get_user_model().objects.create_user(username="staff", password="pass", is_staff=True)
        self.client.force_login(staff)
        run = self._create_run(staff)

        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])

        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertContains(response, '<body class="ui-admin">', html=False)
        self.assertContains(response, '>Debug<', html=False)
        self.assertContains(response, '<details class="slicing-preview" open>', html=False)
        self.assertNotContains(response, "Режим:")

    def test_non_staff_gets_minimal_layout_without_debug_tools(self):
        user = get_user_model().objects.create_user(username="user", password="pass")
        self.client.force_login(user)
        run = self._create_run(user)

        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])

        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertContains(response, '<body class="ui-user">', html=False)
        self.assertNotContains(response, "Debug tools")
        self.assertContains(response, '<section class="card tab-panel" data-panel="svodka" hidden>', html=False)
        self.assertContains(response, '<details class="slicing-preview"', html=False)

    def test_top_status_bar_renders_with_runtime_indicators(self):
        staff = get_user_model().objects.create_user(username="staff3", password="pass", is_staff=True)
        self.client.force_login(staff)

        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])

        with patch.dict("os.environ", {"PORTAL_MODE": "local", "VERSION": "1.2.3"}, clear=False):
            _version_label.cache_clear()
            run = self._create_run(staff)
            response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertContains(response, "UI: Admin")
        self.assertContains(response, "PORTAL: LOCAL")
        self.assertContains(response, "DEBUG: ON")
        self.assertContains(response, "v1.2.3")

    def test_top_status_bar_shows_prod_ro_for_prod_profile(self):
        staff = get_user_model().objects.create_user(username="staff4", password="pass", is_staff=True)
        self.client.force_login(staff)

        settings_obj = PortalDbConnectionSettings.objects.order_by("id").first()
        if settings_obj is None:
            settings_obj = PortalDbConnectionSettings.objects.create(
                profile=PortalDbConnectionSettings.Profile.PROD,
                host="localhost",
                port=5432,
                db_name="portal",
                user="portal",
            )
        settings_obj.profile = PortalDbConnectionSettings.Profile.PROD
        settings_obj.save(update_fields=["profile", "updated_at"])

        with patch.dict("os.environ", {"PORTAL_MODE": "remote"}, clear=False):
            _version_label.cache_clear()
            run = self._create_run(staff)
            response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertContains(response, "PORTAL: PROD RO")
