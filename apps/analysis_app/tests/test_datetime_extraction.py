from __future__ import annotations

from datetime import datetime, timezone

from django.test import SimpleTestCase

from apps.analysis_app.services import _extract_datetime, _extract_datetime_details, _find_datetime_span


class DateTimeExtractionTest(SimpleTestCase):
    def test_find_datetime_span_returns_match_for_word_date_and_time(self):
        span = _find_datetime_span("24 марта 2022 года в 6:00 произошло событие")

        self.assertIsNotNone(span)
        if span is None:
            self.fail("Expected datetime span for valid RU date/time text")
        self.assertEqual("24 марта 2022 года", "24 марта 2022 года в 6:00 произошло событие"[span[0]:span[1]])


    def test_extract_datetime_details_returns_date_and_time_spans(self):
        text = "24 марта 2022 года в 6:00 произошло событие"

        dt, time_found, date_span, time_span = _extract_datetime_details(text)

        self.assertEqual(dt, datetime(2022, 3, 24, 6, 0, tzinfo=timezone.utc))
        self.assertTrue(time_found)
        self.assertEqual(text[date_span[0]:date_span[1]], "24 марта 2022 года")
        self.assertEqual(text[time_span[0]:time_span[1]], "в 6:00")

    def test_extracts_word_date_and_hhmm_time(self):
        dt, time_found = _extract_datetime("24 марта 2022 года в 6:00 произошло событие")

        self.assertEqual(dt, datetime(2022, 3, 24, 6, 0, tzinfo=timezone.utc))
        self.assertTrue(time_found)

    def test_extracts_numeric_date_and_dot_time(self):
        dt, time_found = _extract_datetime("24.03.2022 в 06.00 правонарушение")

        self.assertEqual(dt, datetime(2022, 3, 24, 6, 0, tzinfo=timezone.utc))
        self.assertTrue(time_found)

    def test_extracts_ch_minute_format(self):
        dt, time_found = _extract_datetime("24-03-2022, в 6 ч 00 мин выявлен факт")

        self.assertEqual(dt, datetime(2022, 3, 24, 6, 0, tzinfo=timezone.utc))
        self.assertTrue(time_found)

    def test_does_not_take_article_number_as_time(self):
        dt, time_found = _extract_datetime("24.03.2022 по статье 18.3 ч. 1 составлен протокол")

        self.assertEqual(dt, datetime(2022, 3, 24, 0, 0, tzinfo=timezone.utc))
        self.assertFalse(time_found)
