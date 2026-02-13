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
    HydratedEvent,
    dob_matches,
    get_event_candidates,
    match_event,
    match_offenders,
)
from apps.analysis_app.views import _build_offender_report, _format_offenders
from apps.portaldb.gateway.dtos import EventDTO, OffenderDTO
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

class StagedCandidateDebugTests(TestCase):
    def test_uses_default_score_threshold_without_config(self):
        attributes = ExtractedAttributes(
            date_time=None,
            time_found=False,
            subdivision_id=None,
            offenders=[],
            subdivision_name=None,
        )

        _, meta = get_event_candidates(attributes, text="")

        self.assertEqual(meta["score_threshold"], settings.MATCH_STAGE_MIN_SCORE_THRESHOLD)
        self.assertIsInstance(meta["score_threshold"], float)

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


class Stage4OffenderFallbackTests(TestCase):
    databases = {"default", "portal"}

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
