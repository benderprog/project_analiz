from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from apps.analysis_app.services import _stage4_candidates_by_offenders
from apps.portaldb.gateway.dtos import EventDTO


class _FakeGateway:
    def __init__(self, event: EventDTO):
        self.event = event
        self.calls: list[dict] = []

    def search_events_by_offender(self, **kwargs):
        self.calls.append(kwargs)
        return [self.event]


class Stage4OffendersTests(SimpleTestCase):
    def test_stage4_uses_span_based_eligible_offender_filtering(self):
        subdivision_id = uuid4()
        expected_event = EventDTO(
            event_id=uuid4(),
            date_detection=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            subdivision_id=subdivision_id,
            event_type="test",
            article_of_law="test",
        )
        gateway = _FakeGateway(expected_event)

        attributes = SimpleNamespace(
            offenders=[
                {
                    "second_name": "Смирнова",
                    "full_name": "Смирнова Мария Сергеевна",
                    "birth_year": 1996,
                    "birth_date": None,
                    "span": (10, 30),
                }
            ],
            subdivision_id=subdivision_id,
        )

        text = "Доставлена Смирнова Мария Сергеевна 1996 г.р."

        from unittest.mock import patch

        with patch("apps.analysis_app.services.get_portal_gateway", return_value=gateway):
            events, debug = _stage4_candidates_by_offenders(
                attributes,
                text=text,
                subdivision_confidence_high=True,
                limit=50,
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, expected_event.event_id)
        self.assertTrue(debug)
        self.assertGreater(len(gateway.calls), 0)
