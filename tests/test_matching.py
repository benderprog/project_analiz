import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from apps.analysis_app.services import (
    DEFAULT_DOB,
    ExtractedAttributes,
    dob_matches,
    get_event_candidates,
    match_event,
    match_offenders,
)
from apps.analysis_app.views import _build_offender_report, _format_offenders
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
                "score_percent": 0,
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

    def test_year_only_dob_refinement_is_not_partial_error_label(self):
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
                        "discrepancy": "Совпало ФИО (с учётом падежа), ДР уточнено по данным БД: 1990 ↔ 03-03-1990",
                    }
                ]
            },
        }

        report = _build_offender_report(match_result)

        self.assertEqual(len(report["details"]), 1)
        self.assertIn("ДР уточнено по данным БД", report["details"][0])
        self.assertNotIn("ФИО совпало частично/с ошибкой", report["details"][0])

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
