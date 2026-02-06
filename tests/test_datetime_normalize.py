from datetime import date, datetime, time

from django.test import SimpleTestCase

from apps.analysis_app.utils.datetime_normalize import to_datetime


class _HasAsDatetime:
    def __init__(self, value):
        self._value = value

    def as_datetime(self):
        return self._value


class _HasAsDate:
    def __init__(self, value):
        self._value = value

    def as_date(self):
        return self._value


class _HasYmd:
    def __init__(self, year, month, day):
        self.year = year
        self.month = month
        self.day = day


class DateTimeNormalizeTests(SimpleTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(to_datetime(None))

    def test_datetime_passthrough(self):
        value = datetime(2024, 5, 6, 7, 8)
        self.assertEqual(to_datetime(value), value)

    def test_date_combines_with_default(self):
        value = date(2024, 5, 6)
        expected = datetime(2024, 5, 6, 9, 30)
        self.assertEqual(to_datetime(value, default_time=time(9, 30)), expected)

    def test_as_datetime_used(self):
        value = _HasAsDatetime(datetime(2025, 1, 2, 3, 4))
        self.assertEqual(to_datetime(value), datetime(2025, 1, 2, 3, 4))

    def test_as_date_used(self):
        value = _HasAsDate(date(2026, 2, 3))
        self.assertEqual(to_datetime(value), datetime(2026, 2, 3, 0, 0))

    def test_year_month_day_attributes(self):
        value = _HasYmd(2027, 3, 4)
        self.assertEqual(to_datetime(value), datetime(2027, 3, 4, 0, 0))
