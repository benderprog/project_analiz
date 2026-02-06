from __future__ import annotations

from datetime import datetime

from django.utils import timezone


def format_local_naive(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
