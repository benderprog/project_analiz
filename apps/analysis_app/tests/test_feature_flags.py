from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from apps.analysis_app.admin import FeatureFlagsAdmin
from apps.analysis_app.models import FeatureFlags


class FeatureFlagsTests(TestCase):
    def test_default_false_when_missing_row(self):
        FeatureFlags.objects.all().delete()

        self.assertFalse(FeatureFlags.is_debug_enabled())

    def test_true_when_enabled(self):
        feature_flags = FeatureFlags.get_solo()
        feature_flags.debug_mode = True
        feature_flags.save(update_fields=["debug_mode", "updated_at"])

        self.assertTrue(FeatureFlags.is_debug_enabled())

    def test_admin_singleton_add_permission(self):
        admin = FeatureFlagsAdmin(FeatureFlags, AdminSite())
        request = RequestFactory().get("/")

        self.assertTrue(admin.has_add_permission(request))

        FeatureFlags.get_solo()

        self.assertFalse(admin.has_add_permission(request))
