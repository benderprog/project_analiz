from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.analysis_app.services import ExtractedAttributes, match_event
from apps.portaldb.models import Event, Offender, Pu, Subdivision


class MatchingTests(TestCase):
    databases = {"default", "portal"}

    def test_match_event_with_two_of_three_flags(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="Отдел 1", parent_pu=pu
        )
        event_time = timezone.now()
        event = Event.objects.using("portal").create(
            date_detection=event_time,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Иван",
            second_name="Иванов",
            patronymic_name="Иванович",
            date_of_birth=timezone.datetime(1990, 1, 1).date(),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=event_time + timedelta(minutes=10),
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[
                {
                    "full_name": "Иванов Иван Иванович",
                    "birth_year": 1990,
                }
            ],
            subdivision_name=subdivision.name,
        )

        result = match_event(attributes, "Тестовый текст")

        self.assertTrue(result["matched"])
        self.assertEqual(result["matched_event_id"], str(event.event_id))
        self.assertLessEqual(result["time_delta_minutes"], 30)
