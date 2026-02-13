from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.analysis_app.views import _build_event_card


class EventCardTitleTests(SimpleTestCase):
    def _paragraph_with_match(self, *, matched: bool):
        return SimpleNamespace(
            idx=13,
            text="Текст события",
            result=SimpleNamespace(
                extracted_attributes={},
                match_result={"matched": matched},
            ),
        )

    def test_unmatched_event_title_contains_not_found_label(self):
        card = _build_event_card(self._paragraph_with_match(matched=False))

        self.assertIn("Событие 13", card["title"])
        self.assertIn("в базе данных не найдено", card["title"])
        self.assertTrue(card["not_found"])

    def test_matched_event_title_has_no_not_found_label(self):
        card = _build_event_card(self._paragraph_with_match(matched=True))

        self.assertEqual(card["title"], "Событие 13")
        self.assertNotIn("в базе данных не найдено", card["title"])
        self.assertFalse(card["not_found"])
