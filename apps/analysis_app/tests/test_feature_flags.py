from django.contrib import admin
from django.test import TestCase

from apps.analysis_app.models import FeatureFlags


class FeatureFlagsTests(TestCase):
    def test_default_false_when_missing_row(self):
        FeatureFlags.objects.all().delete()

        self.assertFalse(FeatureFlags.is_effective_debug_enabled())

    def test_true_when_enabled(self):
        feature_flags = FeatureFlags.get_solo()
        feature_flags.debug_mode = True
        feature_flags.save(update_fields=["debug_mode", "updated_at"])

        self.assertTrue(FeatureFlags.is_effective_debug_enabled())

    def test_feature_flags_not_registered_in_admin(self):
        self.assertNotIn(FeatureFlags, admin.site._registry)
