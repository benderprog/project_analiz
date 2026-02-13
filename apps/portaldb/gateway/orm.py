from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from django.conf import settings

from apps.portaldb.models import Event, Offender, Pu, Subdivision

from .dtos import EventDTO, OffenderDTO, PuDTO, SubdivisionDTO


class ORMPortalGateway:
    def __init__(self, alias: str | None = None):
        self.alias = alias or settings.PORTAL_DB_ALIAS

    def list_pus(self) -> list[PuDTO]:
        rows = Pu.objects.using(self.alias).order_by("short_name", "full_name").values(
            "pu_id", "short_name", "full_name"
        )
        return [PuDTO(**row) for row in rows]

    def list_subdivisions(self, pu_id: UUID | None = None) -> list[SubdivisionDTO]:
        queryset = Subdivision.objects.using(self.alias).all()
        if pu_id is not None:
            queryset = queryset.filter(parent_pu_id=pu_id)
        rows = queryset.order_by("name").values(
            "subdivision_id", "name", "short_name", "parent_pu_id"
        )
        return [SubdivisionDTO(**row) for row in rows]

    def search_events_by_subdivision_time(
        self,
        subdivision_id: UUID,
        dt_from: datetime,
        dt_to: datetime,
        limit: int,
    ) -> list[EventDTO]:
        rows = (
            Event.objects.using(self.alias)
            .filter(
                find_subdivision_unit_id=subdivision_id,
                date_detection__range=(dt_from, dt_to),
            )
            .order_by("-date_detection")[:limit]
            .values(
                "event_id",
                "date_detection",
                "find_subdivision_unit_id",
                "event_type",
                "article_of_law",
            )
        )
        return [
            EventDTO(
                event_id=row["event_id"],
                date_detection=row["date_detection"],
                subdivision_id=row["find_subdivision_unit_id"],
                event_type=row["event_type"],
                article_of_law=row["article_of_law"],
            )
            for row in rows
        ]

    def search_events_by_time(
        self,
        dt_from: datetime,
        dt_to: datetime,
        limit: int,
    ) -> list[EventDTO]:
        rows = (
            Event.objects.using(self.alias)
            .filter(date_detection__range=(dt_from, dt_to))
            .order_by("-date_detection")[:limit]
            .values(
                "event_id",
                "date_detection",
                "find_subdivision_unit_id",
                "event_type",
                "article_of_law",
            )
        )
        return [
            EventDTO(
                event_id=row["event_id"],
                date_detection=row["date_detection"],
                subdivision_id=row["find_subdivision_unit_id"],
                event_type=row["event_type"],
                article_of_law=row["article_of_law"],
            )
            for row in rows
        ]

    def get_offenders_by_event_ids(self, event_ids: list[UUID]) -> list[OffenderDTO]:
        if not event_ids:
            return []
        rows = (
            Offender.objects.using(self.alias)
            .filter(event_id__in=event_ids)
            .order_by("event_id", "offender_id")
            .values(
                "offender_id",
                "event_id",
                "second_name",
                "first_name",
                "patronymic_name",
                "date_of_birth",
            )
        )
        return [OffenderDTO(**row) for row in rows]


    def search_event_ids_by_offender(
        self,
        second_name: str,
        birth_year: int | None,
        birth_date: date | None,
        subdivision_id: UUID | None,
        limit: int,
    ) -> list[UUID]:
        queryset = Offender.objects.using(self.alias).filter(second_name__iexact=second_name)
        if birth_date is not None:
            queryset = queryset.filter(date_of_birth=birth_date)
        elif birth_year is not None:
            queryset = queryset.filter(date_of_birth__year=birth_year)
        if subdivision_id is not None:
            queryset = queryset.filter(event__find_subdivision_unit_id=subdivision_id)
        rows = (
            queryset.order_by('-event__date_detection')
            .values_list('event_id', flat=True)[:limit]
        )
        return list(rows)

    def get_event_by_id(self, event_id: UUID) -> EventDTO | None:
        row = (
            Event.objects.using(self.alias)
            .filter(event_id=event_id)
            .values(
                "event_id",
                "date_detection",
                "find_subdivision_unit_id",
                "event_type",
                "article_of_law",
            )
            .first()
        )
        if not row:
            return None
        return EventDTO(
            event_id=row["event_id"],
            date_detection=row["date_detection"],
            subdivision_id=row["find_subdivision_unit_id"],
            event_type=row["event_type"],
            article_of_law=row["article_of_law"],
        )
