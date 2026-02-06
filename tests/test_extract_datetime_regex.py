from django.test import SimpleTestCase

from apps.analysis_app import services


class ExtractDatetimeRegexTests(SimpleTestCase):
    def test_time_before_date_with_dot_separator(self):
        text = "В 08.40 02.02.2026 произошло событие."

        extracted, time_found = services._extract_datetime_regex(text)

        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.date().isoformat(), "2026-02-02")
        self.assertEqual(extracted.time().strftime("%H:%M"), "08:40")
        self.assertTrue(time_found)

    def test_date_before_time_with_colon_separator(self):
        text = "02.02.2026 в 09:05 зафиксировано."

        extracted, time_found = services._extract_datetime_regex(text)

        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.time().strftime("%H:%M"), "09:05")
        self.assertTrue(time_found)

    def test_date_before_time_with_comma(self):
        text = "02.02.2026, 09:50 — событие."

        extracted, time_found = services._extract_datetime_regex(text)

        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.time().strftime("%H:%M"), "09:50")
        self.assertTrue(time_found)
