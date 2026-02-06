from django.test import SimpleTestCase

from apps.analysis_app import services


class NatashaExtractorSmokeTests(SimpleTestCase):
    def test_extract_datetime_smoke(self):
        text = "Событие произошло 12.03.2024 в городе."

        extracted, time_found = services._extract_datetime(text)

        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.year, 2024)
        self.assertFalse(time_found)

    def test_extract_names_smoke(self):
        text = "Иванов Иван Иванович находился на месте."

        extracted = services._extract_names(text)

        self.assertTrue(extracted)
        self.assertEqual(extracted[0]["full_name"], "Иванов Иван Иванович")


class MatchEndIndexTests(SimpleTestCase):
    def _extract_year_from_match(self, text, match):
        end_idx = services._match_end_index(match)
        return services._find_birth_year(text, end_idx) if end_idx is not None else None

    def test_match_end_index_with_stop(self):
        class DummyMatch:
            def __init__(self, stop):
                self.stop = stop

        text = "Иванов 1980"
        match = DummyMatch(stop=len("Иванов "))

        year = self._extract_year_from_match(text, match)

        self.assertEqual(year, 1980)

    def test_match_end_index_with_span_method(self):
        class DummyMatch:
            def span(self):
                return (0, len("Иванов "))

        text = "Иванов 1981"
        match = DummyMatch()

        year = self._extract_year_from_match(text, match)

        self.assertEqual(year, 1981)
