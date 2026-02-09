from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal


SourceType = Literal["portal", "svodka"]


def _get_value(offender: Any, key: str) -> Any:
    if isinstance(offender, dict):
        return offender.get(key)
    return getattr(offender, key, None)


def _parse_birth_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def portal_offender_fullname(offender: Any) -> str:
    parts = [
        _get_value(offender, "second_name"),
        _get_value(offender, "first_name"),
        _get_value(offender, "patronymic_name"),
    ]
    full_name = " ".join(part for part in parts if part)
    if not full_name:
        full_name = _get_value(offender, "full_name") or ""
    return full_name.strip()


def svodka_offender_fullname(offender: Any) -> str:
    parts = [
        _get_value(offender, "second_name"),
        _get_value(offender, "first_name"),
        _get_value(offender, "patronymic_name"),
    ]
    full_name = " ".join(part for part in parts if part)
    if not full_name:
        full_name = _get_value(offender, "full_name") or ""
    return full_name.strip()


def normalize_name_key(fullname: str) -> str:
    if not fullname:
        return ""
    cleaned = " ".join(fullname.strip().split())
    return cleaned.lower().replace("ё", "е")


def offender_display(offender: Any, *, source: SourceType) -> str:
    if source == "portal":
        full_name = portal_offender_fullname(offender) or "—"
        birth_date = _parse_birth_date(
            _get_value(offender, "date_of_birth") or _get_value(offender, "birth_date")
        )
        if birth_date and birth_date != date(1900, 1, 1):
            return f"{full_name} ({birth_date.strftime('%d.%m.%Y')})"
        return full_name

    full_name = svodka_offender_fullname(offender) or "—"
    birth_date = _parse_birth_date(_get_value(offender, "birth_date"))
    birth_year = _get_value(offender, "birth_year")
    if birth_date and birth_date != date(1900, 1, 1):
        return f"{full_name} ({birth_date.strftime('%d.%m.%Y')})"
    if birth_year:
        return f"{full_name} ({birth_year})"
    return full_name
