from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID


@dataclass
class PortalPURecord:
    pu_id: UUID
    short_name: str
    full_name: str


@dataclass
class PortalSubdivisionRecord:
    subdivision_id: UUID
    name: str
    short_name: str
    parent_pu_id: UUID
    parent_pu: PortalPURecord | None = None


@dataclass
class PortalOffenderRecord:
    offender_id: UUID | None
    event_id: UUID
    second_name: str
    first_name: str
    patronymic_name: str
    date_of_birth: date

    @property
    def fio_surname_first(self) -> str:
        return " ".join(
            part for part in [self.second_name, self.first_name, self.patronymic_name] if part
        ).strip()


@dataclass
class PortalEventRecord:
    event_id: UUID
    date_detection: datetime
    find_subdivision_unit_id: UUID
    event_type: str
    article_of_law: str
    find_subdivision_unit: PortalSubdivisionRecord | None = None
    offenders: list[PortalOffenderRecord] = field(default_factory=list)
