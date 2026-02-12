from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from uuid import UUID

from django.db import connections
from django.utils import timezone

from apps.portaldb.sql_registry import get_sql_registry

from .dtos import EventDTO, OffenderDTO, PuDTO, SubdivisionDTO


def _ensure_utc(dt: datetime) -> datetime:
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


class SQLPortalGateway:
    alias = "portal"

    def __init__(self, sql_registry=None):
        self.sql_registry = sql_registry

    def _fetchall(self, query_name: str, params: dict) -> list[dict]:
        registry = self.sql_registry or get_sql_registry()
        sql = registry.get_sql(query_name)
        with connections[self.alias].cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

    def list_pus(self) -> list[PuDTO]:
        return [PuDTO(**row) for row in self._fetchall("list_pus", {})]

    def list_subdivisions(self, pu_id: UUID | None = None) -> list[SubdivisionDTO]:
        return [SubdivisionDTO(**row) for row in self._fetchall("list_subdivisions", {"pu_id": pu_id})]

    def search_events_by_subdivision_time(
        self,
        subdivision_id: UUID,
        dt_from: datetime,
        dt_to: datetime,
        limit: int,
    ) -> list[EventDTO]:
        rows = self._fetchall(
            "search_by_subdivision_time",
            {
                "subdivision_id": subdivision_id,
                "from_ts": _ensure_utc(dt_from),
                "to_ts": _ensure_utc(dt_to),
                "limit": limit,
            },
        )
        return [EventDTO(**row) for row in rows]

    def search_events_by_time(
        self,
        dt_from: datetime,
        dt_to: datetime,
        limit: int,
    ) -> list[EventDTO]:
        rows = self._fetchall(
            "search_by_time",
            {"from_ts": _ensure_utc(dt_from), "to_ts": _ensure_utc(dt_to), "limit": limit},
        )
        return [EventDTO(**row) for row in rows]

    def get_offenders_by_event_ids(self, event_ids: list[UUID]) -> list[OffenderDTO]:
        if not event_ids:
            return []
        rows = self._fetchall("event_offenders", {"event_ids": event_ids})
        return [OffenderDTO(**row) for row in rows]

    def get_event_by_id(self, event_id: UUID) -> EventDTO | None:
        rows = self._fetchall("event_snapshot", {"event_id": event_id})
        return EventDTO(**rows[0]) if rows else None
