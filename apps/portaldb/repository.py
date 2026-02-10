from __future__ import annotations

from datetime import datetime, timedelta

from apps.analysis_app.portal_records import PortalEventRecord, PortalOffenderRecord
from apps.portaldb.gateway import get_portal_gateway


def list_subdivisions():
    gateway = get_portal_gateway()
    return gateway.list_subdivisions()


def find_candidate_events(
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    subdivision_id: str | None = None,
):
    gateway = get_portal_gateway()
    if date_from and date_to and subdivision_id:
        events = gateway.search_events_by_subdivision_time(subdivision_id, date_from, date_to, 500)
    elif date_from and date_to:
        events = gateway.search_events_by_time(date_from, date_to, 500)
    else:
        now = datetime.now()
        events = gateway.search_events_by_time(now - timedelta(days=36500), now + timedelta(days=36500), 500)
    if subdivision_id:
        events = [event for event in events if str(event.subdivision_id) == str(subdivision_id)]
    return [
        PortalEventRecord(
            event_id=event.event_id,
            date_detection=event.date_detection,
            find_subdivision_unit_id=event.subdivision_id,
            event_type=event.event_type,
            article_of_law=event.article_of_law,
        )
        for event in events
    ]


def get_event_with_offenders(event_id):
    gateway = get_portal_gateway()
    event = gateway.get_event_by_id(event_id)
    if event is None:
        raise LookupError(f"Event {event_id} not found")
    offenders = [
        PortalOffenderRecord(
            offender_id=offender.offender_id,
            event_id=offender.event_id,
            second_name=offender.second_name,
            first_name=offender.first_name,
            patronymic_name=offender.patronymic_name,
            date_of_birth=offender.date_of_birth,
        )
        for offender in gateway.get_offenders_by_event_ids([event.event_id])
    ]
    return PortalEventRecord(
        event_id=event.event_id,
        date_detection=event.date_detection,
        find_subdivision_unit_id=event.subdivision_id,
        event_type=event.event_type,
        article_of_law=event.article_of_law,
        offenders=offenders,
    )


def find_close_events_by_date(target_dt: datetime, window_hours: int = 24):
    date_from = target_dt - timedelta(hours=window_hours)
    date_to = target_dt + timedelta(hours=window_hours)
    return find_candidate_events(date_from=date_from, date_to=date_to)


def search_events_by_text(query: str):
    # Left for backward compatibility in dev tooling; matching logic does not use it.
    return []
