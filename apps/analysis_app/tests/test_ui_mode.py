from django.contrib.auth import get_user_model
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun, FeatureFlags, PortalDbConnectionSettings
from apps.analysis_app.ui_mode import _version_label


class UiModeTests(TestCase):
    def _create_staff_run(self):
        owner = get_user_model().objects.create_user(username="owner", password="pass")
        return AnalysisRun.objects.create(
            uploaded_by=owner,
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            status=AnalysisRun.Status.DONE,
            slicing_meta={"analyzed_text": "line0", "fallback_to_full_report": True},
        )

    def test_non_staff_cannot_set_admin_mode(self):
        user = get_user_model().objects.create_user(username="user", password="pass")
        self.client.force_login(user)

        response = self.client.post(reverse("analysis-ui-mode"), {"mode": "admin"}, HTTP_REFERER=reverse("analysis-upload"))

        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get("ui_mode"), "user")

    def test_staff_can_set_admin_mode_and_see_admin_block(self):
        staff = get_user_model().objects.create_user(username="staff", password="pass", is_staff=True)
        self.client.force_login(staff)
        run = self._create_staff_run()
        AnalysisParagraph.objects.create(run=run, idx=1, text="text")
        AnalysisResult.objects.create(paragraph=run.paragraphs.first(), extracted_attributes={}, match_result={"matched": False})

        self.client.post(reverse("analysis-ui-mode"), {"mode": "admin"}, HTTP_REFERER=reverse("analysis-upload"))
        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertContains(response, "Debug tools")
        self.assertContains(response, "Диагностическая панель")
        self.assertContains(response, '<details class="slicing-preview" open>', html=False)


    def test_top_status_bar_renders_with_runtime_indicators(self):
        staff = get_user_model().objects.create_user(username="staff3", password="pass", is_staff=True)
        self.client.force_login(staff)
        self.client.post(reverse("analysis-ui-mode"), {"mode": "admin"}, HTTP_REFERER=reverse("analysis-upload"))

        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])

        with patch.dict("os.environ", {"PORTAL_MODE": "local", "VERSION": "1.2.3"}, clear=False):
            _version_label.cache_clear()
            run = self._create_staff_run()
            AnalysisParagraph.objects.create(run=run, idx=1, text="text")
            AnalysisResult.objects.create(paragraph=run.paragraphs.first(), extracted_attributes={}, match_result={"matched": False})
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
            run = self._create_staff_run()
            AnalysisParagraph.objects.create(run=run, idx=1, text="text")
            AnalysisResult.objects.create(paragraph=run.paragraphs.first(), extracted_attributes={}, match_result={"matched": False})
            response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertContains(response, "PORTAL: PROD RO")

    def test_debug_mode_off_shows_admin_warning(self):
        staff = get_user_model().objects.create_user(username="staff2", password="pass", is_staff=True)
        self.client.force_login(staff)
        run = self._create_staff_run()
        AnalysisParagraph.objects.create(run=run, idx=1, text="text")
        AnalysisResult.objects.create(paragraph=run.paragraphs.first(), extracted_attributes={}, match_result={"matched": False})
        flags = FeatureFlags.get_solo()
        flags.debug_mode = False
        flags.save(update_fields=["debug_mode", "updated_at"])

        self.client.post(reverse("analysis-ui-mode"), {"mode": "admin"}, HTTP_REFERER=reverse("analysis-upload"))
        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertContains(response, "Debug отключен администратором")
        self.assertNotContains(response, "Скачать debug.zip")
