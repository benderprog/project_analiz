from datetime import date, datetime
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.analysis_app.services import _hydrate_events_with_offenders
from apps.portaldb.gateway.dtos import EventDTO, OffenderDTO


class HydrateEventsWithOffendersTests(SimpleTestCase):
    def test_hydrate_events_groups_offenders_by_event_id(self):
        event1_id = uuid4()
        event2_id = uuid4()
        events = [
            EventDTO(
                event_id=event1_id,
                date_detection=datetime(2024, 1, 1, 10, 0),
                subdivision_id=uuid4(),
                event_type="Type A",
                article_of_law="1.1",
            ),
            EventDTO(
                event_id=event2_id,
                date_detection=datetime(2024, 1, 1, 11, 0),
                subdivision_id=uuid4(),
                event_type="Type B",
                article_of_law="2.2",
            ),
        ]

        offenders = [
            OffenderDTO(
                offender_id=uuid4(),
                event_id=event1_id,
                second_name="Иванов",
                first_name="Иван",
                patronymic_name="Иванович",
                date_of_birth=date(1990, 1, 1),
            ),
            OffenderDTO(
                offender_id=uuid4(),
                event_id=event1_id,
                second_name="Петров",
                first_name="Петр",
                patronymic_name="Петрович",
                date_of_birth=date(1991, 2, 2),
            ),
            OffenderDTO(
                offender_id=uuid4(),
                event_id=uuid4(),
                second_name="Сидоров",
                first_name="Сидор",
                patronymic_name="Сидорович",
                date_of_birth=date(1992, 3, 3),
            ),
        ]

        class FakeGateway:
            def get_offenders_by_event_ids(self, event_ids):
                self.event_ids = event_ids
                return offenders

        fake_gateway = FakeGateway()

        with patch("apps.analysis_app.services.get_portal_gateway", return_value=fake_gateway):
            hydrated = _hydrate_events_with_offenders(events)

        self.assertEqual(len(hydrated), 2)
        self.assertEqual([item.event.event_id for item in hydrated], [event1_id, event2_id])
        self.assertEqual(len(hydrated[0].offenders), 2)
        self.assertEqual(hydrated[0].offenders[0].event_id, event1_id)
        self.assertEqual(hydrated[1].offenders, [])
        self.assertEqual(fake_gateway.event_ids, [event1_id, event2_id])
