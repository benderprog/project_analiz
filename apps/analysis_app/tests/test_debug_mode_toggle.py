from django.test import TestCase

from apps.analysis_app.admin_forms import PortalDbConnectionSettingsAdminForm
from apps.analysis_app.models import FeatureFlags, PortalDbConnectionSettings


class DebugModeToggleTests(TestCase):
    def _settings_instance(self):
        settings_obj, _ = PortalDbConnectionSettings.objects.get_or_create(
            id=1,
            defaults={
                "profile": PortalDbConnectionSettings.Profile.TEST,
                "host": "localhost",
                "port": 5432,
                "db_name": "portal",
                "user": "portal",
            },
        )
        return settings_obj

    def _form_data(self, settings_obj):
        return {
            "profile": settings_obj.profile,
            "host": settings_obj.host,
            "port": settings_obj.port,
            "db_name": settings_obj.db_name,
            "user": settings_obj.user,
            "password": "",
        }

    def test_toggle_false_persists(self):
        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])
        settings_obj = self._settings_instance()

        form = PortalDbConnectionSettingsAdminForm(
            data=self._form_data(settings_obj),
            instance=settings_obj,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertFalse(FeatureFlags.is_debug_enabled())

    def test_toggle_true_persists(self):
        flags = FeatureFlags.get_solo()
        flags.debug_mode = False
        flags.save(update_fields=["debug_mode", "updated_at"])
        settings_obj = self._settings_instance()
        data = self._form_data(settings_obj)
        data["debug_mode"] = "on"

        form = PortalDbConnectionSettingsAdminForm(
            data=data,
            instance=settings_obj,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertTrue(FeatureFlags.is_debug_enabled())
