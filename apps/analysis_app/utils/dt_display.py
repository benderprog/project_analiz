from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.utils import timezone


def format_local_naive(dt: datetime | None) -> str | None:
    dt = to_local_naive(dt)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M")


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
