from __future__ import annotations

from django.test import SimpleTestCase

from apps.analysis_app.services import _calc_article_status


class ArticleStatusTest(SimpleTestCase):
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

    def test_yellow_when_missing_in_text_and_db_is_null_like(self):
        for portal_article in ("NULL", "—", None):
            result = _calc_article_status(None, "18.1 ч.1", portal_article)

            self.assertEqual(result["article_status"], "yellow")
            self.assertTrue(result["article_match_db"])
            self.assertFalse(result["article_match_classifier"])

    def test_neutral_when_all_are_none(self):
        result = _calc_article_status(None, None, None)

        self.assertEqual(result["article_status"], "neutral")
        self.assertTrue(result["article_match_db"])
        self.assertTrue(result["article_match_classifier"])

    def test_red_when_text_has_article_and_db_is_none(self):
        result = _calc_article_status("18.1 ч.1", "18.1 ч.1", None)

        self.assertEqual(result["article_status"], "red")
        self.assertFalse(result["article_match_db"])
        self.assertTrue(result["article_match_classifier"])
