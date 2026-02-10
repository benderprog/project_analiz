from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True)
class PuDTO:
    pu_id: UUID
    short_name: str
    full_name: str


@dataclass(frozen=True)
class SubdivisionDTO:
    subdivision_id: UUID
    name: str
    short_name: str
    parent_pu_id: UUID


@dataclass(frozen=True)
class EventDTO:
    event_id: UUID
    date_detection: datetime
    subdivision_id: UUID
    event_type: str
    article_of_law: str


@dataclass(frozen=True)
class OffenderDTO:
    offender_id: UUID | None
    event_id: UUID
    second_name: str
    first_name: str
    patronymic_name: str
    date_of_birth: date
