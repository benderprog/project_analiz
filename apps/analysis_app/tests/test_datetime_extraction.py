from __future__ import annotations

from datetime import datetime, timezone

from django.test import SimpleTestCase

from apps.analysis_app.services import _extract_datetime


class DateTimeExtractionTest(SimpleTestCase):
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
