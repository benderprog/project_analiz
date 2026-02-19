import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from apps.classifier.models import EventType, EventTypePattern
from apps.analysis_app.services import (
    DEFAULT_DOB,
    ExtractedAttributes,
    dob_matches,
    get_event_candidates,
    match_event,
    match_offenders,
)
from apps.analysis_app.views import _build_highlighted_html, _build_offender_report, _format_offenders
from apps.portaldb.gateway.dtos import EventDTO
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
        self.assertEqual(result["offenders_counts"]["svodka_total"], 2)
        self.assertEqual(result["offenders_counts"]["portal_total"], 1)

    def test_match_event_sets_event_type_and_article_flags_separately(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="Отдел ET", parent_pu=pu
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
            date_time=event_time,
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

        with patch("apps.analysis_app.services._classify_event_type", return_value=("Тип", "12.1", None)):
            result_ok = match_event(attributes, "Тестовый текст")
        self.assertTrue(result_ok["event_type_ok"])
        self.assertTrue(result_ok["article_ok"])

        with patch("apps.analysis_app.services._classify_event_type", return_value=("Тип", "99.9", None)):
            result_article_bad = match_event(attributes, "Тестовый текст")
        self.assertTrue(result_article_bad["event_type_ok"])
        self.assertFalse(result_article_bad["article_ok"])
        self.assertNotIn("event_type", result_article_bad["diffs"])
        self.assertIn("article_of_law", result_article_bad["diffs"])

        with patch("apps.analysis_app.services._classify_event_type", return_value=("Другой тип", "12.1", None)):
            result_type_bad = match_event(attributes, "Тестовый текст")
        self.assertFalse(result_type_bad["event_type_ok"])


    def test_match_event_type_matches_when_portal_article_is_null(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="Отдел NULL", parent_pu=pu
        )
        event_time = timezone.now()
        event = Event.objects.using("portal").create(
            date_detection=event_time,
            find_subdivision_unit=subdivision,
            event_type="Курил в неустановленном месте",
            article_of_law="NULL",
        )
        Offender.objects.using("portal").create(
            first_name="Иван",
            second_name="Иванов",
            patronymic_name="Иванович",
            date_of_birth=timezone.datetime(1990, 1, 1).date(),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=event_time,
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

        with patch(
            "apps.analysis_app.services._classify_event_type",
            return_value=("Курил в неустановленном месте", "18.4 ч.2", None),
        ):
            result = match_event(attributes, "Тестовый текст")

        self.assertTrue(result["event_type_ok"])
        self.assertFalse(result["article_ok"])

    def test_match_event_normalizes_article_when_comparing(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="Отдел ART", parent_pu=pu
        )
        event_time = timezone.now()
        event = Event.objects.using("portal").create(
            date_detection=event_time,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="18.1ч1",
        )
        Offender.objects.using("portal").create(
            first_name="Иван",
            second_name="Иванов",
            patronymic_name="Иванович",
            date_of_birth=timezone.datetime(1990, 1, 1).date(),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=event_time,
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

        with patch("apps.analysis_app.services._classify_event_type", return_value=("Тип", "18.1 ч. 1", None)):
            result = match_event(attributes, "Тестовый текст")

        self.assertTrue(result["event_type_ok"])
        self.assertTrue(result["article_ok"])

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

    def test_match_event_time_and_offenders_when_subdivision_wrong(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="Отдел 3", parent_pu=pu
        )
        other_subdivision = Subdivision.objects.using("portal").create(
            name="Отдел 4", parent_pu=pu
        )
        event_time = timezone.now()
        event = Event.objects.using("portal").create(
            date_detection=event_time,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Андрей",
            second_name="Климов",
            patronymic_name="Олегович",
            date_of_birth=timezone.datetime(1990, 3, 3).date(),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=event_time,
            time_found=True,
            subdivision_id=str(other_subdivision.subdivision_id),
            offenders=[
                {
                    "full_name": "Климов Андрей Олегович",
                    "birth_year": 1990,
                }
            ],
            subdivision_name=other_subdivision.name,
        )

        result = match_event(attributes, "Тестовый текст")

        self.assertTrue(result["matched"])
        self.assertEqual(result["matched_event_id"], str(event.event_id))
        self.assertEqual(result["match_method"], "time+offenders")
        self.assertTrue(result["subdivision_mismatch"])

    def test_match_event_subdivision_and_offenders_when_date_mismatch(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="КПП-2", parent_pu=pu
        )
        event_dt = datetime(2020, 4, 5, 7, 35)
        if settings.USE_TZ:
            event_dt = timezone.make_aware(event_dt, timezone.get_current_timezone())
        event = Event.objects.using("portal").create(
            date_detection=event_dt,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Андрей",
            second_name="Климов",
            patronymic_name="Олегович",
            date_of_birth=timezone.datetime(1990, 3, 3).date(),
            event=event,
        )

        extracted_dt = datetime(2026, 2, 12, 10, 35)
        attributes = ExtractedAttributes(
            date_time=extracted_dt,
            time_found=True,
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[
                {
                    "full_name": "Климов Андрей Олегович",
                    "birth_year": 1990,
                }
            ],
            subdivision_name=subdivision.name,
        )

        result = match_event(attributes, "Тестовый текст")

        self.assertTrue(result["matched"])
        self.assertEqual(result["matched_event_id"], str(event.event_id))
        self.assertEqual(result["match_method"], "subdivision+offenders")
        self.assertTrue(result["time_mismatch"])



    def test_staff_surname_in_db_offenders_is_overridden_to_offender(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(name="Отдел 5", parent_pu=pu)
        event_time = timezone.now()
        event = Event.objects.using("portal").create(
            date_detection=event_time,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Андрей",
            second_name="Васильев",
            patronymic_name="Алексеевич",
            date_of_birth=timezone.datetime(1990, 1, 1).date(),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=event_time,
            time_found=True,
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[],
            subdivision_name=subdivision.name,
            staff=[
                {
                    "rank_raw": "ст. л-т",
                    "rank_norm": "ст. л-т",
                    "surname": "Васильев",
                    "initials": "А.А.",
                    "display": "ст. л-т Васильев А.А.",
                }
            ],
        )

        result = match_event(attributes, "пн (ст. л-т Васильев А.А.)")

        self.assertTrue(result["matched"])
        self.assertEqual(attributes.staff, [])
        self.assertEqual(len(attributes.offenders), 1)
        self.assertEqual(attributes.offenders[0]["second_name"], "Васильев")
        self.assertTrue(attributes.offenders[0]["staff_override_is_offender"])

    def test_staff_surname_not_in_db_offenders_stays_in_staff(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(name="Отдел 6", parent_pu=pu)
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
            date_time=event_time,
            time_found=True,
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[
                {
                    "full_name": "Иванов Иван Иванович",
                    "second_name": "Иванов",
                    "first_name": "Иван",
                    "patronymic_name": "Иванович",
                    "birth_year": 1990,
                }
            ],
            subdivision_name=subdivision.name,
            staff=[
                {
                    "rank_raw": "ст. л-т",
                    "rank_norm": "ст. л-т",
                    "surname": "Васильев",
                    "initials": "А.А.",
                    "display": "ст. л-т Васильев А.А.",
                }
            ],
        )

        result = match_event(attributes, "пн (ст. л-т Васильев А.А.)")

        self.assertTrue(result["matched"])
        self.assertEqual(len(attributes.staff), 1)
        self.assertEqual(attributes.staff[0]["display"], "ст. л-т Васильев А.А.")
        self.assertEqual(len(attributes.offenders), 1)
        self.assertEqual(attributes.offenders[0]["second_name"], "Иванов")


    def test_match_event_wrong_time_found_by_subdivision_and_offenders_with_staged_search(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name='КПП-1 "Ухтомское"', parent_pu=pu
        )
        event_dt = datetime(2026, 2, 10, 8, 30)
        if settings.USE_TZ:
            event_dt = timezone.make_aware(event_dt, timezone.get_current_timezone())
        event = Event.objects.using("portal").create(
            date_detection=event_dt,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Андрей",
            second_name="Климов",
            patronymic_name="Олегович",
            date_of_birth=timezone.datetime(1990, 3, 3).date(),
            event=event,
        )

        extracted_dt = datetime(2026, 2, 12, 10, 35)
        attributes = ExtractedAttributes(
            date_time=extracted_dt,
            time_found=True,
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[
                {
                    "full_name": "Климов Андрей Олегович",
                    "birth_year": 1990,
                }
            ],
            subdivision_name=subdivision.name,
            subdivision_candidates=[{"score": 1.0, "lexical_strength": "strong"}],
        )

        result = match_event(attributes, "Тестовый текст")

        self.assertTrue(result["matched"])
        self.assertEqual(result["matched_event_id"], str(event.event_id))
        self.assertEqual(result["match_method"], "subdivision+offenders")
        self.assertTrue(result["time_mismatch"])
        self.assertIn("date_time", result["diffs"])
        self.assertIn("дата/время не совпадают", result["diffs"]["date_time"]["message"])
        self.assertGreater(result["time_delta_minutes"], 24 * 60)

class OffenderOverlapTests(TestCase):
    databases = {"default", "portal"}

    def test_overlap_uses_year_only_dob(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(
            name="Отдел 5", parent_pu=pu
        )
        event = Event.objects.using("portal").create(
            date_detection=timezone.now(),
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        offender = Offender.objects.using("portal").create(
            first_name="Иван",
            second_name="Иванов",
            patronymic_name="Иванович",
            date_of_birth=timezone.datetime(1990, 3, 3).date(),
            event=event,
        )

        extracted = [
            {
                "full_name": "Иванов Иван Иванович",
                "birth_year": 1990,
            }
        ]

        score, counts, matches = match_offenders(
            extracted, list(event.offenders.using("portal").all())
        )

        self.assertGreater(score, 0)
        self.assertEqual(counts["matched"], 1)
        self.assertTrue(matches["matched_pairs"])


class OffenderDisplayTests(TestCase):
    def test_format_offenders_uses_full_portal_dob(self):
        formatted = _format_offenders(
            [
                {
                    "full_name": "Климов Андрей Олегович",
                    "birth_date": "1990-03-03",
                }
            ],
            source="portal",
        )
        self.assertEqual(formatted, ["Климов Андрей Олегович (03.03.1990)"])


class DobMatchingTests(TestCase):
    def test_dob_matches_year_only_to_full_date(self):
        self.assertTrue(dob_matches(date(1990, 1, 1), date(1990, 3, 3)))

    def test_dob_matches_year_only_to_other_year(self):
        self.assertFalse(dob_matches(date(1990, 1, 1), date(1991, 3, 3)))

    def test_dob_matches_full_dates_mismatch(self):
        self.assertFalse(dob_matches(date(1990, 5, 6), date(1990, 3, 3)))

    def test_dob_matches_default_dob_ignored(self):
        self.assertFalse(dob_matches(DEFAULT_DOB, date(1990, 3, 3)))


class OffenderMatchingRulesTests(TestCase):
    databases = {"default", "portal"}

    def test_offender_full_dob_mismatch_not_matched(self):
        extracted = [
            {
                "full_name": "Тарасов Илья Петрович",
                "birth_date": date(1993, 4, 12),
            }
        ]
        portal = [
            Offender(
                first_name="Илья",
                second_name="Тарасов",
                patronymic_name="Петрович",
                date_of_birth=date(1994, 4, 4),
            )
        ]

        score, counts, matches = match_offenders(extracted, portal)

        self.assertEqual(score, 0)
        self.assertEqual(counts["matched"], 0)
        self.assertEqual(counts["dob_mismatch"], 1)
        self.assertEqual(len(matches["dob_mismatch_pairs"]), 1)

    def test_offender_missing_in_portal_detected(self):
        extracted = [
            {
                "full_name": "Смирнова Мария Сергеевна",
                "birth_year": 1996,
            }
        ]
        score, counts, matches = match_offenders(extracted, [])

        self.assertEqual(score, 0)
        self.assertEqual(counts["missing_in_portal"], 1)
        self.assertEqual(len(matches["missing_in_portal"]), 1)



    def test_per_offender_status_map_contains_err_warn_ok(self):
        extracted = [
            {
                "full_name": "Смирнова Мария Сергеевна",
                "second_name": "Смирнова",
                "first_name": "Мария",
                "patronymic_name": "Сергеевна",
                "birth_year": 1996,
                "span": (0, 24),
            },
            {
                "full_name": "Климов Андрей Олегович",
                "second_name": "Климов",
                "first_name": "Андрей",
                "patronymic_name": "Олегович",
                "birth_date": date(1990, 1, 1),
                "span": (30, 52),
            },
            {
                "full_name": "Иванов Иван Иванович",
                "second_name": "Иванов",
                "first_name": "Иван",
                "patronymic_name": "Иванович",
                "birth_date": date(1985, 5, 6),
                "span": (60, 80),
            },
        ]
        portal = [
            Offender(
                first_name="Андрей",
                second_name="Климов",
                patronymic_name="Олегович",
                date_of_birth=date(1990, 3, 3),
            ),
            Offender(
                first_name="Иван",
                second_name="Иванов",
                patronymic_name="Иванович",
                date_of_birth=date(1985, 5, 6),
            ),
        ]

        _, _, matches = match_offenders(extracted, portal)

        self.assertEqual(matches["svodka_status_by_span"]["0:24"], "err")
        self.assertEqual(matches["svodka_status_by_span"]["30:52"], "warn")
        self.assertEqual(matches["svodka_status_by_span"]["60:80"], "ok")


    def test_year_only_match_is_green_and_not_warn(self):
        extracted = [
            {
                "full_name": "Орлов Дмитрий Игоревич",
                "second_name": "Орлов",
                "first_name": "Дмитрий",
                "patronymic_name": "Игоревич",
                "birth_date": date(1992, 1, 1),
                "span": (0, 21),
            }
        ]
        portal = [
            Offender(
                first_name="Дмитрий",
                second_name="Орлов",
                patronymic_name="Игоревич",
                date_of_birth=date(1992, 12, 12),
            )
        ]

        _, counts, matches = match_offenders(extracted, portal)

        self.assertEqual(counts["matched"], 1)
        self.assertEqual(counts["dob_mismatch"], 0)
        self.assertEqual(matches["svodka_status_by_span"]["0:21"], "ok")

    def test_dob_mismatch_pair_not_duplicated_in_missing_in_svodka(self):
        extracted = [
            {
                "full_name": "Тарасов Илья Петрович",
                "second_name": "Тарасов",
                "first_name": "Илья",
                "patronymic_name": "Петрович",
                "birth_date": date(1993, 4, 12),
                "span": (0, 21),
            },
            {
                "full_name": "Смирнова Мария Сергеевна",
                "second_name": "Смирнова",
                "first_name": "Мария",
                "patronymic_name": "Сергеевна",
                "birth_year": 1996,
                "span": (30, 54),
            },
        ]
        portal = [
            Offender(
                first_name="Илья",
                second_name="Тарасов",
                patronymic_name="Петрович",
                date_of_birth=date(1994, 4, 4),
            )
        ]

        _, counts, matches = match_offenders(extracted, portal)

        self.assertEqual(counts["dob_mismatch"], 1)
        self.assertEqual(counts["missing_in_portal"], 1)
        self.assertEqual(counts["missing_in_svodka"], 0)
        self.assertEqual(matches["svodka_status_by_span"]["0:21"], "warn")
        self.assertEqual(matches["svodka_status_by_span"]["30:54"], "err")
        self.assertEqual(len(matches["missing_in_svodka"]), 0)

    def test_offender_year_only_matches_full_date_same_year(self):
        extracted = [
            {
                "full_name": "Климов Андрей Олегович",
                "birth_date": date(1990, 1, 1),
            }
        ]
        portal = [
            Offender(
                first_name="Андрей",
                second_name="Климов",
                patronymic_name="Олегович",
                date_of_birth=date(1990, 3, 3),
            )
        ]

        score, counts, matches = match_offenders(extracted, portal)

        self.assertGreater(score, 0)
        self.assertEqual(counts["matched"], 1)
        self.assertEqual(len(matches["matched_pairs"]), 1)


class TemplateRenderingTests(TestCase):
    def test_detail_template_has_no_raw_offender_counts_markup(self):
        event = {
            "idx": 1,
            "preview": "preview",
            "highlighted_html": "text",
            "extracted_timestamp_display": "—",
            "portal_timestamp_display": "—",
            "extracted": {
                "subdivision_name": None,
                "subdivision_candidates": [],
                "offenders": [],
            },
            "portal": {
                "subdivision_name": None,
                "offenders": [],
                "event_type": None,
                "article_of_law": None,
            },
            "predicted": {"event_type": None, "article_of_law": None},
            "status": {"timestamp": "red", "subdivision": "red", "offenders": "green"},
            "match": {
                "matched": True,
                "time_delta_minutes": None,
                "subdivision_match_percent": None,
                "offenders_summary": "Совпало нарушителей: 0 из 0",
                "offenders_details": [],
                "offenders_counts": {
                    "matched": 0,
                    "portal_total": 0,
                    "svodka_total": 0,
                    "dob_mismatch": 0,
                    "missing_in_portal": 0,
                    "missing_in_svodka": 0,
                },
            },
            "comments": [],
        }
        run = SimpleNamespace(run_id="run-1", status="done")
        html = render_to_string(
            "analysis_app/detail.html",
            {
                "run": run,
                "events": [event],
                "selected_event": event,
            },
        )

        self.assertNotIn("{{ selected_event.match.offenders_counts", html)
        self.assertNotIn("Совпадение", html)


    def test_detail_template_renders_exactly_two_event_type_badges(self):
        event = {
            "idx": 1,
            "preview": "preview",
            "highlighted_html": "text",
            "extracted_timestamp_display": "—",
            "portal_timestamp_display": "—",
            "extracted": {
                "subdivision_name": None,
                "subdivision_candidates": [],
                "offenders": [],
                "staff": [],
            },
            "portal": {
                "subdivision_name": None,
                "offenders": [],
                "event_type": "Курил в неустановленном месте",
                "article_of_law": "NULL",
            },
            "predicted": {
                "event_type": "Курил в неустановленном месте",
                "article_of_law": "18.4 ч.2",
            },
            "status": {
                "timestamp": "green",
                "subdivision": "green",
                "offenders": "green",
                "event_type": "green",
                "article": "red",
            },
            "match": {
                "matched": True,
                "time_delta_minutes": 0,
                "subdivision_match_percent": 100,
                "offenders_summary": "Совпало нарушителей: 0 из 0",
                "offenders_details": [],
                "offenders_counts": {
                    "matched": 0,
                    "portal_total": 0,
                    "svodka_total": 0,
                    "dob_mismatch": 0,
                    "missing_in_portal": 0,
                    "missing_in_svodka": 0,
                },
            },
            "comments": ["Статья закона отличается от классификации."],
        }
        run = SimpleNamespace(run_id="run-1", status="done")
        html = render_to_string(
            "analysis_app/detail.html",
            {
                "run": run,
                "events": [event],
                "selected_event": event,
            },
        )

        self.assertEqual(html.count('data-badge="event-type"'), 1)
        self.assertEqual(html.count('data-badge="article"'), 1)



class OffenderReportDeduplicationTests(TestCase):
    def test_missing_in_svodka_report_is_deduplicated(self):
        match_result = {
            "offenders_counts": {"matched": 0, "portal_total": 1},
            "offender_matches": {
                "missing_in_svodka": [
                    {
                        "full_name": "Зайцев Павел",
                        "birth_date": "1980-12-12",
                    },
                    {
                        "full_name": "Зайцев Павел",
                        "birth_date": "1980-12-12",
                    },
                ]
            },
        }

        report = _build_offender_report(match_result)

        self.assertEqual(len(report["details"]), 1)
        self.assertEqual(report["details"][0].count("Зайцев Павел"), 1)

    def test_year_only_dob_match_does_not_include_refinement_text(self):
        match_result = {
            "offenders_counts": {"matched": 1, "portal_total": 1},
            "offender_matches": {
                "matched_pairs": [
                    {
                        "svodka_offender": {
                            "full_name": "Климов Андрей Олегович",
                            "birth_date": "1990-01-01",
                        },
                        "portal_offender": {
                            "full_name": "Климов Андрей Олегович",
                            "birth_date": "1990-03-03",
                        },
                        "match_type": "exact",
                        "discrepancy": None,
                    }
                ]
            },
        }

        report = _build_offender_report(match_result)

        self.assertEqual(len(report["details"]), 0)
        output = " ".join(report["details"])
        self.assertNotIn("01-01", output)
        self.assertNotIn("↔", output)
        self.assertNotIn("с учётом падежа", output)
        self.assertNotIn("уточнено", output)

    def test_report_has_no_partial_or_case_note_for_inflection_only_match(self):
        match_result = {
            "offenders_counts": {"matched": 1, "portal_total": 1},
            "offender_matches": {
                "matched_pairs": [
                    {
                        "svodka_offender": {
                            "full_name": "Орлов Дмитрий Игоревич",
                            "birth_date": "1992-01-01",
                        },
                        "portal_offender": {
                            "full_name": "Орлов Дмитрий Игоревич",
                            "birth_date": "1992-12-12",
                        },
                        "match_type": "exact",
                        "discrepancy": None,
                    }
                ]
            },
        }

        report = _build_offender_report(match_result)

        details = " ".join(report["details"])
        self.assertNotIn("частично/с ошибкой", details)
        self.assertNotIn("косвенном падеже", details)

    def test_dob_mismatch_pairs_are_deduplicated(self):
        match_result = {
            "offenders_counts": {"matched": 0, "portal_total": 1},
            "offender_matches": {
                "dob_mismatch_pairs": [
                    {
                        "svodka_offender": {
                            "full_name": "Смирнова Мария Сергеевна",
                            "birth_date": "1996-01-18",
                        },
                        "portal_offender": {
                            "full_name": "Смирнова Мария Сергеевна",
                            "birth_date": "1996-02-01",
                        },
                        "reason": "Возможное совпадение по ФИО, но ДР отличается",
                    },
                    {
                        "svodka_offender": {
                            "full_name": "Смирнова Мария Сергеевна",
                            "birth_date": "1996-01-18",
                        },
                        "portal_offender": {
                            "full_name": "Смирнова Мария Сергеевна",
                            "birth_date": "1996-02-01",
                        },
                        "reason": "Возможное совпадение по ФИО, но ДР отличается",
                    },
                ]
            },
        }

        report = _build_offender_report(match_result)

        self.assertEqual(len(report["details"]), 1)
        self.assertEqual(report["details"][0].count("Смирнова"), 2)

class StagedCandidateDebugTests(TestCase):
    def test_stage3_calls_time_only_branch(self):
        attributes = ExtractedAttributes(
            date_time=timezone.make_aware(datetime(2026, 2, 12, 10, 35), timezone.get_current_timezone()),
            time_found=True,
            subdivision_id=str(uuid.uuid4()),
            offenders=[],
            subdivision_name="КПП",
            subdivision_candidates=[{"score": 1.0, "lexical_strength": "strong"}],
        )

        with patch("apps.analysis_app.services._get_events_for_window", return_value=[]) as mocked_window, patch(
            "apps.analysis_app.services._hydrate_events_with_offenders", return_value=[]
        ):
            _, meta = get_event_candidates(attributes, text="")

        stages = {item["stage"]: item["count"] for item in meta["stages"]}
        self.assertIn("stage3_time", stages)
        self.assertEqual(stages["stage3_time"], 0)
        called_stage3_time = any(call.kwargs.get("stage_name") == "stage3_time" for call in mocked_window.call_args_list)
        self.assertTrue(called_stage3_time)


class Stage4OffenderFallbackQueryBoundsTests(TestCase):
    def test_stage4_offender_only_without_dob_uses_bounded_limit(self):
        attributes = ExtractedAttributes(
            date_time=timezone.make_aware(datetime(2026, 2, 12, 10, 35), timezone.get_current_timezone()),
            time_found=True,
            subdivision_id=str(uuid.uuid4()),
            offenders=[{"full_name": "Иванов Иван Иванович", "second_name": "Иванов"}],
            subdivision_name="КПП",
            subdivision_candidates=[{"score": 0.6, "lexical_strength": "weak"}],
        )

        gateway = SimpleNamespace(
            search_events_by_offender=lambda **kwargs: []
        )

        with patch("apps.analysis_app.services._get_events_for_window", return_value=[]), patch(
            "apps.analysis_app.services.get_portal_gateway", return_value=gateway
        ):
            _, meta = get_event_candidates(attributes, text="Событие")

        stage4_queries = [q for q in meta["stage_queries"] if q.get("stage") == "stage4_offenders"]
        self.assertTrue(stage4_queries)
        self.assertEqual(stage4_queries[0]["method"], "search_events_by_offender")
        self.assertLessEqual(stage4_queries[0]["limit"], 100)
        self.assertIn("dob_missing_limit_reduced", stage4_queries[0]["warnings"])


class Stage4OffenderFallbackTests(TestCase):
    databases = {"default", "portal"}

    def test_stage4_runs_even_when_stage1_to_3_have_candidates_but_no_selection(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        target_subdivision = Subdivision.objects.using("portal").create(name='КПП-цель', parent_pu=pu)
        other_subdivision = Subdivision.objects.using("portal").create(name='КПП-другое', parent_pu=pu)

        target_dt = timezone.make_aware(datetime(2026, 2, 2, 8, 30), timezone.get_current_timezone())
        target_event = Event.objects.using("portal").create(
            date_detection=target_dt,
            find_subdivision_unit=target_subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Иван",
            second_name="Иванов",
            patronymic_name="Иванович",
            date_of_birth=date(1955, 1, 1),
            event=target_event,
        )

        decoy_event = Event.objects.using("portal").create(
            date_detection=timezone.make_aware(datetime(2025, 1, 1, 0, 0), timezone.get_current_timezone()),
            find_subdivision_unit=other_subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )

        attributes = ExtractedAttributes(
            date_time=timezone.make_aware(datetime(2026, 2, 12, 10, 35), timezone.get_current_timezone()),
            time_found=True,
            subdivision_id=str(target_subdivision.subdivision_id),
            offenders=[
                {"full_name": "Иванов Иван Иванович", "second_name": "Иванов", "birth_year": 1955},
            ],
            subdivision_name=target_subdivision.name,
            subdivision_candidates=[{"score": 0.61, "lexical_strength": "weak"}],
        )

        decoy_dto = EventDTO(
            event_id=decoy_event.event_id,
            date_detection=decoy_event.date_detection,
            subdivision_id=decoy_event.find_subdivision_unit_id,
            event_type=decoy_event.event_type,
            article_of_law=decoy_event.article_of_law,
        )

        with patch("apps.analysis_app.services._get_events_for_window", return_value=[decoy_dto]):
            result = match_event(attributes, "Событие 13: пн (ст.м-н Смирнов А.А.+1), Иванов Иван Иванович")

        self.assertTrue(result["matched"])
        self.assertEqual(result["match_method"], "subdivision+offenders")
        self.assertTrue(result["debug"]["stage4_used"])
        self.assertGreater(result["debug"]["pre_stage4_candidate_count"], 0)
        self.assertGreater(result["debug"]["stage4_offenders"], 0)


    def test_stage4_falls_back_to_offender_only_when_subdivision_query_returns_zero(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        target_subdivision = Subdivision.objects.using("portal").create(name='КПП-цель', parent_pu=pu)
        other_subdivision = Subdivision.objects.using("portal").create(name='КПП-другое', parent_pu=pu)

        event = Event.objects.using("portal").create(
            date_detection=timezone.make_aware(datetime(2026, 2, 12, 10, 30), timezone.get_current_timezone()),
            find_subdivision_unit=other_subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Семен",
            second_name="Федоров",
            patronymic_name="Ильич",
            date_of_birth=date(1996, 2, 1),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=timezone.make_aware(datetime(2026, 2, 12, 10, 35), timezone.get_current_timezone()),
            time_found=True,
            subdivision_id=str(target_subdivision.subdivision_id),
            offenders=[
                {"full_name": "Фёдоров Семен Ильич", "birth_year": 1996},
            ],
            subdivision_name=target_subdivision.name,
            subdivision_candidates=[{"score": 1.0, "lexical_strength": "strong"}],
        )

        with patch("apps.analysis_app.services._get_events_for_window", return_value=[]):
            result = match_event(attributes, "Событие 20")

        self.assertTrue(result["matched"])
        self.assertEqual(result["match_method"], "time+offenders")
        self.assertTrue(result["subdivision_mismatch"])
        self.assertTrue(result["debug"]["stage4_executed"])
        self.assertEqual(result["debug"]["stage4_path"], "offender_subdivision_then_only")
        self.assertEqual(result["debug"]["stage4_rows_subdivision"], 0)
        self.assertGreater(result["debug"]["stage4_rows_only"], 0)
        self.assertEqual(result["offenders_counts"]["portal_total"], 1)

    def test_stage4_birth_year_matches_portal_full_birth_date(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(name='КПП-1', parent_pu=pu)

        event = Event.objects.using("portal").create(
            date_detection=timezone.make_aware(datetime(2023, 5, 1, 9, 0), timezone.get_current_timezone()),
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Мария",
            second_name="Смирнова",
            patronymic_name="Игоревна",
            date_of_birth=date(1996, 2, 1),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=timezone.make_aware(datetime(2026, 2, 12, 10, 35), timezone.get_current_timezone()),
            time_found=True,
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[
                {"full_name": "Смирнова Мария Игоревна", "birth_year": 1996},
            ],
            subdivision_name=subdivision.name,
            subdivision_candidates=[{"score": 1.0, "lexical_strength": "strong"}],
        )

        with patch("apps.analysis_app.services._get_events_for_window", return_value=[]):
            result = match_event(attributes, "Событие 20")

        self.assertTrue(result["matched"])
        self.assertEqual(result["debug"]["stage4_path"], "offender_subdivision")
        self.assertGreater(result["debug"]["stage4_rows_subdivision"], 0)
        self.assertEqual(result["debug"]["stage4_rows_only"], 0)
        self.assertEqual(result["offenders_counts"]["portal_total"], 1)

    def test_stage4_finds_event_by_subdivision_and_offenders_when_time_mismatch(self):
        pu = Pu.objects.using("portal").create(full_name="PU", short_name="PU")
        subdivision = Subdivision.objects.using("portal").create(name='КПП-1 "Ухтомское"', parent_pu=pu)
        event_dt = timezone.make_aware(datetime(2026, 2, 2, 8, 30), timezone.get_current_timezone())
        event = Event.objects.using("portal").create(
            date_detection=event_dt,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            first_name="Мария",
            second_name="Смирнова",
            patronymic_name="Игоревна",
            date_of_birth=date(1996, 6, 1),
            event=event,
        )
        Offender.objects.using("portal").create(
            first_name="Андрей",
            second_name="Климов",
            patronymic_name="Олегович",
            date_of_birth=date(1990, 3, 3),
            event=event,
        )

        attributes = ExtractedAttributes(
            date_time=timezone.make_aware(datetime(2026, 2, 12, 10, 35), timezone.get_current_timezone()),
            time_found=True,
            subdivision_id=str(subdivision.subdivision_id),
            offenders=[
                {"full_name": "Смирнова Мария Игоревна", "birth_year": 1996},
                {"full_name": "Климов Андрей Олегович", "birth_year": 1990},
            ],
            subdivision_name=subdivision.name,
            subdivision_candidates=[{"score": 1.0, "lexical_strength": "strong"}],
        )

        with patch("apps.analysis_app.services._get_events_for_window", return_value=[]):
            result = match_event(attributes, "Сводка про нарушение")

        self.assertTrue(result["matched"])
        self.assertEqual(result["match_method"], "subdivision+offenders")
        self.assertTrue(result["time_mismatch"])
        self.assertIn("date_time", result["diffs"])
        self.assertIn("дата/время отличаются", result["diffs"]["date_time"]["message"])
        self.assertEqual(result["offenders_counts"]["portal_total"], 2)
        self.assertGreaterEqual(result["offenders_counts"]["matched"], 1)
        self.assertGreater(result["debug"]["stage4_offenders"], 0)


class HighlightedHtmlOffenderStatusTests(TestCase):

    def test_build_highlighted_html_highlights_date_and_time_word_form(self):
        text = "24 марта 2022 года в 6:00 произошло событие"
        extracted = {
            "date_span": [0, 18],
            "time_span": [19, 25],
            "offenders": [],
        }

        html = _build_highlighted_html(text, extracted, {"matched": True, "time_delta_minutes": 0})

        self.assertIn('<span class="hl hl-green">24 марта 2022 года</span>', html)
        self.assertIn('<span class="hl hl-green">в 6:00</span>', html)

    def test_build_highlighted_html_highlights_date_and_time_numeric_form(self):
        text = "24.03.2022 06.00 произошло событие"
        extracted = {
            "date_span": [0, 10],
            "time_span": [11, 16],
            "offenders": [],
        }

        html = _build_highlighted_html(text, extracted, {"matched": True, "time_delta_minutes": 0})

        self.assertIn('<span class="hl hl-green">24.03.2022</span>', html)
        self.assertIn('<span class="hl hl-green">06.00</span>', html)

    def test_build_highlighted_html_uses_span_status_for_name_and_dob(self):
        text = "Иванов Иван Иванович 1980 г.р.; Петров Петр Петрович 01.01.1990"
        extracted = {
            "offenders": [
                {
                    "full_name": "Иванов Иван Иванович",
                    "span": [0, 20],
                    "dob_span": [21, 31],
                },
                {
                    "full_name": "Петров Петр Петрович",
                    "span": [32, 52],
                    "dob_span": [53, 63],
                },
            ]
        }
        match_result = {
            "offender_matches": {
                "svodka_status_by_span": {
                    "0:20": "warn",
                    "32:52": "err",
                }
            }
        }

        html = _build_highlighted_html(text, extracted, match_result)

        self.assertIn('<span class="hl hl-yellow">Иванов Иван Иванович</span>', html)
        self.assertIn('<span class="hl hl-yellow">1980 г.р.;</span>', html)
        self.assertIn('<span class="hl hl-red">Петров Петр Петрович</span>', html)
        self.assertIn('<span class="hl hl-red">01.01.1990</span>', html)

    def test_build_highlighted_html_highlights_staff_rank_and_name_in_green(self):
        text = "(пр-к Кылосова О.Д.), гражданин РФ Иванов Иван Иванович"
        staff_text = "пр-к Кылосова О.Д."
        staff_start = text.index(staff_text)
        extracted = {
            "staff": [
                {
                    "display": staff_text,
                    "span": [staff_start, staff_start + len(staff_text)],
                }
            ],
            "offenders": [],
        }

        html = _build_highlighted_html(text, extracted, {})

        self.assertIn('<span class="hl hl-green hl-staff">пр-к Кылосова О.Д.</span>', html)

    def test_build_highlighted_html_highlights_event_pattern_matches(self):
        text = "Нарушитель: Иванов Иван Иванович. Составлен протокол. Составлен протокол повторно."
        offender_text = "Иванов Иван Иванович"
        offender_start = text.index(offender_text)
        extracted = {
            "offenders": [
                {
                    "full_name": offender_text,
                    "span": [offender_start, offender_start + len(offender_text)],
                }
            ]
        }
        first_phrase_start = text.index("Составлен протокол")
        second_phrase_start = text.rindex("Составлен протокол")
        match_result = {
            "predicted": {
                "event_pattern": {
                    "spans": [
                        [offender_start, offender_start + 9],
                        [first_phrase_start, first_phrase_start + len("Составлен протокол")],
                        [second_phrase_start, second_phrase_start + len("Составлен протокол")],
                    ]
                }
            }
        }

        html = _build_highlighted_html(text, extracted, match_result)

        self.assertEqual(html.count("hl-eventpattern"), 2)
        self.assertIn('<span class="hl hl-green hl-eventpattern">Составлен протокол</span>', html)
        self.assertIn('<span class="hl hl-yellow">Иванов Иван Иванович</span>', html)
    def test_build_highlighted_html_handles_none_predicted(self):
        html = _build_highlighted_html("текст", {}, {"predicted": None})

        self.assertIsInstance(html, str)

    def test_build_highlighted_html_handles_none_event_pattern(self):
        html = _build_highlighted_html("текст", {}, {"predicted": {"event_pattern": None}})

        self.assertIsInstance(html, str)

    def test_build_highlighted_html_handles_none_event_pattern_spans(self):
        html = _build_highlighted_html("текст", {}, {"predicted": {"event_pattern": {"spans": None}}})

        self.assertIsInstance(html, str)



class EventPatternClassificationTests(TestCase):
    def test_match_event_exposes_pattern_spans_for_predicted_event(self):
        event_type = EventType.objects.create(event_type="Составление протокола")
        EventTypePattern.objects.create(
            event_type=event_type,
            pattern=r"составлен\s+протокол",
            article_of_law="12.1",
        )
        text = "В ходе рейда составлен протокол и затем составлен протокол повторно."

        attributes = ExtractedAttributes(
            date_time=None,
            time_found=False,
            subdivision_id=None,
            offenders=[],
            subdivision_name=None,
        )

        with patch("apps.analysis_app.services.get_event_candidates", return_value=([], {})):
            result = match_event(attributes, text)

        predicted = result["predicted"]
        self.assertEqual(predicted["event_type"], "Составление протокола")
        self.assertEqual(predicted["article_of_law"], "12.1")
        self.assertIsNotNone(predicted["event_pattern"])
        self.assertEqual(len(predicted["event_pattern"]["spans"]), 2)
        self.assertEqual(
            predicted["event_pattern"]["matched_texts"],
            ["составлен протокол", "составлен протокол"],
        )

    def test_semantic_fallback_matches_pattern_with_typo_and_spans(self):
        event_type = EventType.objects.create(event_type="Финансирование ВСУ")
        EventTypePattern.objects.create(
            event_type=event_type,
            pattern="признаки финансирования ВСУ",
            article_of_law="20.3.3",
        )
        text = "В сообщении установлены признаки финансрования ВСУ через третьих лиц."

        class StubSemanticModel:
            def encode(self, texts):
                vectors = []
                for item in texts:
                    lowered = item.lower()
                    vectors.append([
                        1.0 if "признаки" in lowered else 0.0,
                        1.0 if ("финансирован" in lowered or "финансрован" in lowered) else 0.0,
                        1.0 if "всу" in lowered else 0.0,
                    ])
                return vectors

        attributes = ExtractedAttributes(
            date_time=None,
            time_found=False,
            subdivision_id=None,
            offenders=[],
            subdivision_name=None,
        )

        with patch("apps.analysis_app.services.get_sentence_model", return_value=StubSemanticModel()), \
             patch("apps.analysis_app.services.get_event_candidates", return_value=([], {})), \
             self.settings(SKIP_SEMANTIC_MODEL=False):
            from apps.analysis_app import services as services_module
            services_module._get_event_pattern_embedding_cache.cache_clear()
            result = match_event(attributes, text)

        predicted = result["predicted"]
        self.assertEqual(predicted["event_type"], "Финансирование ВСУ")
        self.assertEqual(predicted["article_of_law"], "20.3.3")
        self.assertEqual(predicted["event_pattern"]["method"], "semantic")
        highlighted = [text[start:end].lower() for start, end in predicted["event_pattern"]["spans"]]
        self.assertTrue(any("признаки" in piece for piece in highlighted))
        self.assertTrue(any("всу" in piece for piece in highlighted))

    def test_semantic_fallback_does_not_match_random_text_below_threshold(self):
        event_type = EventType.objects.create(event_type="Контрабанда")
        EventTypePattern.objects.create(
            event_type=event_type,
            pattern="незаконное перемещение товаров через границу",
            article_of_law="201",
        )

        class StubSemanticModel:
            def encode(self, texts):
                return [[0.0, 0.0, 0.0] for _ in texts]

        attributes = ExtractedAttributes(
            date_time=None,
            time_found=False,
            subdivision_id=None,
            offenders=[],
            subdivision_name=None,
        )

        with patch("apps.analysis_app.services.get_sentence_model", return_value=StubSemanticModel()), \
             patch("apps.analysis_app.services.get_event_candidates", return_value=([], {})), \
             self.settings(EVENT_PATTERN_SEMANTIC_THRESHOLD=0.2, SKIP_SEMANTIC_MODEL=False):
            from apps.analysis_app import services as services_module
            services_module._get_event_pattern_embedding_cache.cache_clear()
            result = match_event(attributes, "абсолютно случайный текст без тематических совпадений")

        self.assertIsNone(result["predicted"]["event_pattern"])
        self.assertIsNone(result["predicted"]["event_type"])

    def test_exact_match_has_priority_over_semantic_fallback(self):
        event_type_exact = EventType.objects.create(event_type="Точный тип")
        event_type_semantic = EventType.objects.create(event_type="Семантический тип")
        EventTypePattern.objects.create(
            event_type=event_type_exact,
            pattern="составлен протокол",
            article_of_law="12.1",
        )
        EventTypePattern.objects.create(
            event_type=event_type_semantic,
            pattern="совершенно другой шаблон",
            article_of_law="99.9",
        )

        class StubSemanticModel:
            def encode(self, texts):
                return [[1.0, 1.0, 1.0] for _ in texts]

        attributes = ExtractedAttributes(
            date_time=None,
            time_found=False,
            subdivision_id=None,
            offenders=[],
            subdivision_name=None,
        )

        with patch("apps.analysis_app.services.get_sentence_model", return_value=StubSemanticModel()), \
             patch("apps.analysis_app.services.get_event_candidates", return_value=([], {})), \
             self.settings(SKIP_SEMANTIC_MODEL=False):
            from apps.analysis_app import services as services_module
            services_module._get_event_pattern_embedding_cache.cache_clear()
            result = match_event(attributes, "По делу составлен протокол в отношении нарушителя.")

        self.assertEqual(result["predicted"]["event_type"], "Точный тип")
        self.assertEqual(result["predicted"]["article_of_law"], "12.1")
        self.assertEqual(result["predicted"]["event_pattern"]["method"], "regex_hit")
