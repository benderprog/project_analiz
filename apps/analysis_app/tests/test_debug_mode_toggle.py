from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import FeatureFlags, PortalDbConnectionSettings


class DebugModeToggleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.client.force_login(self.user)

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

    def _post_data(self, settings_obj):
        return {
            "profile": settings_obj.profile,
            "host": settings_obj.host,
            "port": settings_obj.port,
            "db_name": settings_obj.db_name,
            "user": settings_obj.user,
            "password": "",
            "_save": "Save",
        }

    def test_post_without_debug_mode_sets_false(self):
        flags = FeatureFlags.get_solo()
        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])
        settings_obj = self._settings_instance()

        self.client.post(
            reverse("admin:analysis_app_portaldbconnectionsettings_change", args=[settings_obj.pk]),
            data=self._post_data(settings_obj),
            follow=True,
        )

        self.assertFalse(FeatureFlags.get_solo().debug_mode)

    def test_post_with_debug_mode_sets_true(self):
        flags = FeatureFlags.get_solo()
        flags.debug_mode = False
        flags.save(update_fields=["debug_mode", "updated_at"])
        settings_obj = self._settings_instance()
        data = self._post_data(settings_obj)
        data["debug_mode"] = "on"

        self.client.post(
            reverse("admin:analysis_app_portaldbconnectionsettings_change", args=[settings_obj.pk]),
            data=data,
            follow=True,
        )

        self.assertTrue(FeatureFlags.get_solo().debug_mode)
