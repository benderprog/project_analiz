from __future__ import annotations

from datetime import date, datetime, time
from typing import Any


def to_datetime(value: Any, default_time: time | None = None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, default_time or time(0, 0))

    if hasattr(value, "as_datetime"):
        try:
            dt = value.as_datetime()
        except Exception:
            dt = None
        if dt is not None:
            return dt

    if hasattr(value, "as_date"):
        try:
            value_date = value.as_date()
        except Exception:
            value_date = None
        if value_date is not None:
            return datetime.combine(value_date, default_time or time(0, 0))

    year = getattr(value, "year", None)
    month = getattr(value, "month", None)
    day = getattr(value, "day", None)
    if isinstance(year, int) and isinstance(month, int) and isinstance(day, int):
        try:
            return datetime.combine(date(year, month, day), default_time or time(0, 0))
        except ValueError:
            return None

    return None
