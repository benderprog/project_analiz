from __future__ import annotations

from datetime import date, datetime

from apps.analysis_app.utils.dt_display import format_local_naive


def date_to_str(value: date | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d")


def datetime_to_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    return format_local_naive(value)


def offender_to_json(offender: dict) -> dict:
    data = dict(offender or {})
    birth_date = data.get("birth_date")
    if isinstance(birth_date, datetime):
        birth_date = birth_date.date()
    if isinstance(birth_date, date):
        data["birth_date"] = date_to_str(birth_date)

    birth_year = data.get("birth_year")
    if birth_year is not None:
        try:
            data["birth_year"] = int(birth_year)
        except (TypeError, ValueError):
            data["birth_year"] = None

    span = data.get("span")
    if span is not None and len(span) == 2:
        data["span"] = [int(span[0]), int(span[1])]

    return data
