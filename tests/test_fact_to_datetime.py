from datetime import datetime, timezone as dt_timezone

from django.test import SimpleTestCase

from apps.analysis_app.services import _fact_to_datetime, _to_utc


class DummyDate:
    year = 2026
    month = 2
    day = 2


class DummyAsDatetime:
    def __init__(self, value):
        self._value = value

    def as_datetime(self):
        return self._value


class FactToDatetimeTests(SimpleTestCase):
    def test_dummy_date_object(self):
        self.assertEqual(_fact_to_datetime(DummyDate()), datetime(2026, 2, 2, 0, 0))

    def test_as_datetime_passthrough(self):
        value = datetime(2025, 1, 2, 3, 4)
        self.assertEqual(_fact_to_datetime(DummyAsDatetime(value)), value)

    def test_to_utc_smoke_uses_stdlib_utc(self):
        converted = _to_utc(datetime(2026, 2, 2, 3, 4))
        self.assertEqual(converted.tzinfo, dt_timezone.utc)
