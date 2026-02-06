from datetime import datetime, timedelta

from django.db.models import Prefetch, Q

from apps.portaldb.models import Event, Offender, Subdivision


def list_subdivisions():
    """Return all subdivisions for lookups in matching logic."""
    return Subdivision.objects.using("portal").all()


def find_candidate_events(
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    subdivision_id: str | None = None,
):
    """Find events by optional date range and subdivision in portal DB."""
    queryset = Event.objects.using("portal").all()
    if date_from and date_to:
        queryset = queryset.filter(date_detection__range=(date_from, date_to))
    if subdivision_id:
        queryset = queryset.filter(find_subdivision_unit_id=subdivision_id)
    return queryset


def get_event_with_offenders(event_id):
    """Fetch a portal event with offenders prefetched."""
    return (
        Event.objects.using("portal")
        .prefetch_related(Prefetch("offenders", queryset=Offender.objects.using("portal")))
        .get(event_id=event_id)
    )


def find_close_events_by_date(target_dt: datetime, window_hours: int = 24):
    """Search events within a +/- window in hours."""
    date_from = target_dt - timedelta(hours=window_hours)
    date_to = target_dt + timedelta(hours=window_hours)
    return find_candidate_events(date_from=date_from, date_to=date_to)


def search_events_by_text(query: str):
    """Simple text search fallback for event type or article."""
    return Event.objects.using("portal").filter(
        Q(event_type__icontains=query) | Q(article_of_law__icontains=query)
    )
