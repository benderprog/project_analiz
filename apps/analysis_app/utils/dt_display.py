from __future__ import annotations

from datetime import date, datetime

from django.conf import settings
from django.utils import timezone


def format_local_naive(dt: datetime | None) -> str | None:
    dt = to_local_naive(dt)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M")


def format_date_dmy(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = to_local_naive(value)
        if value is None:
            return "—"
        return value.strftime("%d-%m-%Y")
    return value.strftime("%d-%m-%Y")


def format_dt_dmy_hm(value: datetime | None) -> str:
    if value is None:
        return "—"
    local_dt = to_local_naive(value)
    if local_dt is None:
        return "—"
    return local_dt.strftime("%d-%m-%Y %H:%M")


def to_local_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if settings.USE_TZ:
        current_tz = timezone.get_current_timezone()
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, current_tz)
        dt = timezone.localtime(dt, current_tz)
        return timezone.make_naive(dt, current_tz)
    return dt
