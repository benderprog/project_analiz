from datetime import date, datetime, timezone as dt_timezone

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.analysis_app.utils.dt_display import format_date_dmy, format_dt_dmy_hm, format_run_started_at


class DtDisplayFormatTests(SimpleTestCase):
    def test_dt_filter_dmy_formats_date(self):
        self.assertEqual(format_date_dmy(date(2026, 2, 2)), "02-02-2026")

    def test_dt_filter_dmyhm_formats_datetime(self):
        self.assertEqual(format_dt_dmy_hm(datetime(2026, 2, 2, 8, 40, 33)), "02-02-2026 08:40")

    @override_settings(USE_TZ=True, TIME_ZONE="Europe/Moscow")
    def test_dt_filter_dmyhm_converts_aware_datetime_to_current_tz(self):
        aware_utc = datetime(2026, 2, 2, 5, 40, tzinfo=dt_timezone.utc)
        with timezone.override("Europe/Moscow"):
            self.assertEqual(format_dt_dmy_hm(aware_utc), "02-02-2026 08:40")

    def test_formatters_return_dash_for_none(self):
        self.assertEqual(format_date_dmy(None), "—")
        self.assertEqual(format_dt_dmy_hm(None), "—")


@override_settings(USE_TZ=True, TIME_ZONE="Europe/Moscow")
class RunStartedAtFormatTests(SimpleTestCase):
    def test_today_datetime_is_formatted_as_time_only(self):
        dt = datetime(2026, 2, 2, 8, 5, tzinfo=dt_timezone.utc)
        with timezone.override("Europe/Moscow"), patch("django.utils.timezone.localdate", return_value=date(2026, 2, 2)):
            self.assertEqual(format_run_started_at(dt), "11:05")

    def test_older_datetime_is_formatted_as_date_and_time(self):
        dt = datetime(2026, 2, 1, 20, 45, tzinfo=dt_timezone.utc)
        with timezone.override("Europe/Moscow"), patch("django.utils.timezone.localdate", return_value=date(2026, 2, 2)):
            self.assertEqual(format_run_started_at(dt), "01.02.2026 23:45")

    def test_none_returns_dash(self):
        self.assertEqual(format_run_started_at(None), "—")
