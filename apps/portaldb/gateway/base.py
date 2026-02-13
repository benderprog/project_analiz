from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from .dtos import EventDTO, OffenderDTO, PuDTO, SubdivisionDTO


class PortalGateway(Protocol):
    def list_pus(self) -> list[PuDTO]: ...

    def list_subdivisions(self, pu_id: UUID | None = None) -> list[SubdivisionDTO]: ...

    def search_events_by_subdivision_time(
        self,
        subdivision_id: UUID,
        dt_from: datetime,
        dt_to: datetime,
        limit: int,
    ) -> list[EventDTO]: ...

    def search_events_by_time(
        self,
        dt_from: datetime,
        dt_to: datetime,
        limit: int,
    ) -> list[EventDTO]: ...

    def get_offenders_by_event_ids(self, event_ids: list[UUID]) -> list[OffenderDTO]: ...

    def search_events_by_offender(
        self,
        second_name: str,
        birth_date: date | None,
        birth_year: int | None,
        subdivision_id: UUID | str | None,
        limit: int,
    ) -> list[EventDTO]: ...

    def get_event_by_id(self, event_id: UUID) -> EventDTO | None: ...
