from datetime import date, datetime, timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.analysis_app.services import DEFAULT_DOB, ExtractedAttributes, dob_matches, match_event
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
            time_found=True,
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

    def test_match_event_prefers_subdivision_and_time(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="Отдел 2", parent_pu=pu
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
            date_time=event_time + timedelta(minutes=5),
            time_found=True,
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[
                {
                    "full_name": "Иванов Иван Иванович",
                    "birth_date": date(1990, 3, 3),
                    "birth_year": 1990,
                },
                {
                    "full_name": "Петров Петр Петрович",
                    "birth_year": 1988,
                },
            ],
            subdivision_name=subdivision.name,
        )

        result = match_event(attributes, "Тестовый текст")

        self.assertTrue(result["matched"])
        self.assertEqual(result["matched_event_id"], str(event.event_id))
        self.assertEqual(result["offenders_counts"]["matched"], 1)
        self.assertEqual(result["offenders_counts"]["extracted"], 2)
        self.assertEqual(result["offenders_counts"]["portal"], 1)

    def test_match_event_local_naive_time_delta(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="КПП-1", parent_pu=pu
        )
        extracted_dt = datetime(2026, 2, 12, 10, 35)
        event_dt = datetime(2026, 2, 12, 10, 36)
        if settings.USE_TZ:
            event_dt = timezone.make_aware(event_dt, timezone.get_current_timezone())
        event = Event.objects.using("portal").create(
            date_detection=event_dt,
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
            date_time=extracted_dt,
            time_found=True,
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


class DobMatchingTests(TestCase):
    def test_dob_matches_year_only_to_full_date(self):
        self.assertTrue(dob_matches(date(1990, 1, 1), date(1990, 3, 3)))

    def test_dob_matches_year_only_to_other_year(self):
        self.assertFalse(dob_matches(date(1990, 1, 1), date(1991, 3, 3)))

    def test_dob_matches_full_dates_mismatch(self):
        self.assertFalse(dob_matches(date(1990, 5, 6), date(1990, 3, 3)))

    def test_dob_matches_default_dob_ignored(self):
        self.assertFalse(dob_matches(DEFAULT_DOB, date(1990, 3, 3)))
