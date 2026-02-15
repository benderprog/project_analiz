from __future__ import annotations

from django.test import SimpleTestCase

from apps.analysis_app.services import _calc_article_status, extract_article_of_law, normalize_article


class ArticleStatusTest(SimpleTestCase):
    def test_normalize_article_equivalent_formats(self):
        self.assertEqual(normalize_article("ч. 1 ст. 18.1"), normalize_article("18.1 ч. 1"))

    def test_extract_article_requires_marker(self):
        self.assertIsNone(extract_article_of_law("в тексте только 18.1 ч.1 без маркеров"))

    def test_green_when_matches_classifier_and_db(self):
        result = _calc_article_status("18.1 ч.1", "18.1 ч.1", "18.1 ч.1")

        self.assertEqual(result["article_status"], "green")
        self.assertTrue(result["article_match_db"])
        self.assertTrue(result["article_match_classifier"])

    def test_yellow_when_matches_db_but_not_classifier(self):
        result = _calc_article_status("18.1 ч.1", "18.1 ч.2", "18.1 ч.1")

        self.assertEqual(result["article_status"], "yellow")
        self.assertTrue(result["article_match_db"])
        self.assertFalse(result["article_match_classifier"])

    def test_red_when_mismatch_with_db(self):
        result = _calc_article_status("18.1 ч.1", "18.1 ч.1", "18.3 ч.1")

        self.assertEqual(result["article_status"], "red")
        self.assertFalse(result["article_match_db"])
        self.assertTrue(result["article_match_classifier"])

    def test_neutral_when_no_portal_article(self):
        for portal_article in ("NULL", "—", None):
            result = _calc_article_status("18.1 ч.1", "18.1 ч.1", portal_article)

            self.assertEqual(result["article_status"], "neutral")
            self.assertIsNone(result["article_match_db"])
            self.assertIsNone(result["article_match_classifier"])

    def test_red_when_text_has_no_article_but_db_has(self):
        result = _calc_article_status(None, "18.1 ч.1", "18.1 ч.1")

        self.assertEqual(result["article_status"], "red")
        self.assertFalse(result["article_match_db"])
        self.assertIsNone(result["article_match_classifier"])
