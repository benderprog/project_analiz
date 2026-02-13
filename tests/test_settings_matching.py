import importlib
import os
from unittest.mock import patch

from django.test import SimpleTestCase


class MatchingSettingsTests(SimpleTestCase):
    def test_match_stage_fallback_days_defaults_to_7_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATCH_STAGE_FALLBACK_DAYS", None)
            settings_module = importlib.reload(importlib.import_module("config.settings"))

        self.assertEqual(settings_module.MATCH_STAGE_FALLBACK_DAYS, 7)

    def test_match_stage_min_score_threshold_defaults_to_0_5_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATCH_STAGE_MIN_SCORE_THRESHOLD", None)
            settings_module = importlib.reload(importlib.import_module("config.settings"))

        self.assertEqual(settings_module.MATCH_STAGE_MIN_SCORE_THRESHOLD, 0.5)
