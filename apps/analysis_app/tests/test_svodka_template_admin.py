from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.analysis_app.admin_forms import GENERAL_PU_CHOICE_VALUE, SvodkaTemplateAdminForm
from apps.analysis_app.models import SvodkaTemplate


class SvodkaTemplateAdminFormTests(TestCase):
    def test_general_selection_sets_general_scope_and_empty_pu_id(self):
        form = SvodkaTemplateAdminForm(
            data={
                "pu_select": GENERAL_PU_CHOICE_VALUE,
                "pu_name": "",
                "begin_marker": "[BEGIN]",
                "end_marker": "[END]",
                "is_active": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["scope"], SvodkaTemplate.Scope.GENERAL)
        self.assertEqual(form.cleaned_data["pu_id"], "")

    def test_concrete_pu_selection_sets_pu_scope_and_pu_id(self):
        fake_pu = SimpleNamespace(pu_id="pu-123", full_name="Тестовое ПУ", short_name="ТПУ")
        fake_gateway = SimpleNamespace(list_pus=lambda: [fake_pu])

        with patch("apps.analysis_app.admin_forms.get_portal_gateway", return_value=fake_gateway):
            form = SvodkaTemplateAdminForm(
                data={
                    "pu_select": "pu-123",
                    "pu_name": "",
                    "begin_marker": "[BEGIN]",
                    "end_marker": "[END]",
                    "is_active": "on",
                }
            )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["scope"], SvodkaTemplate.Scope.PU)
        self.assertEqual(form.cleaned_data["pu_id"], "pu-123")


class SvodkaTemplateNormalizationTests(TestCase):
    def test_save_with_empty_pu_id_forces_general_scope(self):
        template = SvodkaTemplate.objects.create(
            scope=SvodkaTemplate.Scope.PU,
            pu_id="",
            pu_name="",
            begin_marker="[BEGIN]",
            end_marker="[END]",
            is_active=False,
        )

        template.refresh_from_db()
        self.assertEqual(template.scope, SvodkaTemplate.Scope.GENERAL)
        self.assertEqual(template.pu_id, "")
