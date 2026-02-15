from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.analysis_app.services import ExtractedAttributes, HydratedEvent, match_event
from apps.analysis_app.views import _build_comments
from apps.portaldb.gateway.dtos import EventDTO


class PortalEventTypeObject:
    def __init__(self, event_type: str):
        self.event_type = event_type

    def __str__(self) -> str:
        return "ReferenceEventType object (1)"


class EventTypeFlagsTest(SimpleTestCase):
    def test_event_type_ok_with_classifier_article_mismatch(self):
        predicted_event_type = "Кража"
        portal_event = EventDTO(
            event_id=uuid4(),
            date_detection=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            subdivision_id=uuid4(),
            event_type=predicted_event_type,
            article_of_law="18.1 ч. 1",
        )
        best_candidate = {
            "event": HydratedEvent(event=portal_event, offenders=[]),
            "flags_true": 2,
            "date_ok": True,
            "subdivision_ok": True,
            "offenders_ok": False,
            "delta_minutes": 0,
        }
        attributes = ExtractedAttributes(
            date_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            time_found=True,
            subdivision_id=str(uuid4()),
            offenders=[],
            subdivision_name="Тест",
        )

        with (
            patch("apps.analysis_app.services._classify_event_type", return_value=(predicted_event_type, "20.3.3", {"event_type_label": predicted_event_type})),
            patch("apps.analysis_app.services.get_event_candidates", return_value=([best_candidate], {"stages": [], "stage_queries": []})),
            patch("apps.analysis_app.services._portal_offenders", return_value=[]),
            patch("apps.analysis_app.services.match_offenders", return_value=(1.0, {
                "svodka_total": 0,
                "portal_total": 0,
                "matched": 0,
                "dob_mismatch": 0,
                "missing_in_portal": 0,
                "missing_in_svodka": 0,
            }, {})),
        ):
            result = match_event(attributes, "по ч. 1 ст. 18.1")

        self.assertTrue(result["event_type_ok"])
        self.assertTrue(result["article_ok"])
        self.assertEqual(result["article_status"], "yellow")
        self.assertNotIn("event_type", result["diffs"])
        self.assertNotIn("article_of_law", result["diffs"])

    def test_event_type_object_uses_human_readable_attribute(self):
        predicted_event_type = "Кража"
        portal_event = EventDTO(
            event_id=uuid4(),
            date_detection=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            subdivision_id=uuid4(),
            event_type=PortalEventTypeObject(event_type=predicted_event_type),
            article_of_law="NULL",
        )
        best_candidate = {
            "event": HydratedEvent(event=portal_event, offenders=[]),
            "flags_true": 2,
            "date_ok": True,
            "subdivision_ok": True,
            "offenders_ok": False,
            "delta_minutes": 0,
        }
        attributes = ExtractedAttributes(
            date_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            time_found=True,
            subdivision_id=str(uuid4()),
            offenders=[],
            subdivision_name="Тест",
        )

        with (
            patch("apps.analysis_app.services._classify_event_type", return_value=(predicted_event_type, "18.4 ч.1", {"event_type_label": predicted_event_type})),
            patch("apps.analysis_app.services.get_event_candidates", return_value=([best_candidate], {"stages": [], "stage_queries": []})),
            patch("apps.analysis_app.services._portal_offenders", return_value=[]),
            patch("apps.analysis_app.services.match_offenders", return_value=(1.0, {
                "svodka_total": 0,
                "portal_total": 0,
                "matched": 0,
                "dob_mismatch": 0,
                "missing_in_portal": 0,
                "missing_in_svodka": 0,
            }, {})),
        ):
            result = match_event(attributes, "test")

        self.assertTrue(result["event_type_ok"])
        self.assertTrue(result["article_ok"])
        self.assertEqual(result["article_status"], "yellow")
        self.assertEqual(result["portal"]["event_type"], predicted_event_type)
        self.assertNotIn("event_type", result["diffs"])
        comments = _build_comments(result)
        self.assertNotIn("Тип события отличается от классификации.", comments)
        self.assertIn("Статья закона не совпадает с классификатором, но совпадает с БД.", comments)

    def test_null_portal_article_returns_red_when_article_extracted(self):
        predicted_event_type = "Кража"
        portal_event = EventDTO(
            event_id=uuid4(),
            date_detection=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            subdivision_id=uuid4(),
            event_type=predicted_event_type,
            article_of_law="NULL",
        )
        best_candidate = {
            "event": HydratedEvent(event=portal_event, offenders=[]),
            "flags_true": 2,
            "date_ok": True,
            "subdivision_ok": True,
            "offenders_ok": False,
            "delta_minutes": 0,
        }
        attributes = ExtractedAttributes(
            date_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            time_found=True,
            subdivision_id=str(uuid4()),
            offenders=[],
            subdivision_name="Тест",
        )

        with (
            patch("apps.analysis_app.services._classify_event_type", return_value=(predicted_event_type, "18.4 ч.1", {"event_type_label": predicted_event_type})),
            patch("apps.analysis_app.services.get_event_candidates", return_value=([best_candidate], {"stages": [], "stage_queries": []})),
            patch("apps.analysis_app.services._portal_offenders", return_value=[]),
            patch("apps.analysis_app.services.match_offenders", return_value=(1.0, {
                "svodka_total": 0,
                "portal_total": 0,
                "matched": 0,
                "dob_mismatch": 0,
                "missing_in_portal": 0,
                "missing_in_svodka": 0,
            }, {})),
        ):
            result = match_event(attributes, "по ч. 1 ст. 18.4")

        self.assertTrue(result["event_type_ok"])
        self.assertFalse(result["article_ok"])
        self.assertEqual(result["article_status"], "red")
        self.assertNotIn("event_type", result["diffs"])
        self.assertIn("article_of_law", result["diffs"])

        comments = _build_comments(result)
        self.assertIn("Статья закона отличается от данных БД.", comments)
        self.assertNotIn("Тип события отличается от классификации.", comments)
