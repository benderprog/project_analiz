from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun


class AnalysisEventsApiTests(TestCase):
    def _make_run(self, *, uploaded_by=None, session_key=None):
        if session_key is None and uploaded_by is None:
            session = self.client.session
            session["analysis"] = True
            session.save()
            session_key = session.session_key
        if session_key is None:
            session_key = ""
        return AnalysisRun.objects.create(
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            uploaded_by=uploaded_by,
            created_session_key=session_key,
            status=AnalysisRun.Status.DONE,
        )

    def _add_paragraph(self, run, idx):
        paragraph = AnalysisParagraph.objects.create(run=run, idx=idx, text=f"Абзац {idx} " + ("текст " * 30))
        matched = idx % 2 == 0
        AnalysisResult.objects.create(
            paragraph=paragraph,
            extracted_attributes={"article_spans": [], "date_span": None, "time_span": None},
            match_result={
                "matched": matched,
                "event_type_ok": True,
                "article_ok": True,
                "article_classifier_ok": True,
                "article_status": "green",
                "portal": {"event_type": f"Тип {idx}", "timestamp": None},
                "predicted": {"event_type": f"Тип {idx}"},
            },
            matched=matched,
            title=f"Событие {idx}" + ("" if matched else " — в базе данных не найдено"),
            preview=f"Превью {idx}",
            status_timestamp="green",
            status_subdivision="yellow",
            status_offenders="red",
            status_event_type="green",
            status_article="green",
        )

    def test_events_list_returns_paginated_items(self):
        run = self._make_run()
        for idx in range(1, 6):
            self._add_paragraph(run, idx)

        response = self.client.get(
            reverse("analysis-events-list", kwargs={"run_id": run.run_id}),
            {"page": 2, "page_size": 2},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 5)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 2)
        self.assertTrue(payload["has_next"])
        self.assertEqual([item["idx"] for item in payload["items"]], [3, 4])

    def test_event_detail_returns_404_for_invalid_idx(self):
        run = self._make_run()
        self._add_paragraph(run, 1)

        response = self.client.get(
            reverse("analysis-event-detail", kwargs={"run_id": run.run_id, "idx": 999})
        )
        self.assertEqual(response.status_code, 404)

    def test_events_endpoints_forbidden_for_other_authenticated_user(self):
        user_model = get_user_model()
        owner = user_model.objects.create_user(username="owner", password="pwd")
        other = user_model.objects.create_user(username="other", password="pwd")
        run = self._make_run(uploaded_by=owner)
        self._add_paragraph(run, 1)

        self.client.force_login(other)
        list_response = self.client.get(reverse("analysis-events-list", kwargs={"run_id": run.run_id}))
        detail_response = self.client.get(
            reverse("analysis-event-detail", kwargs={"run_id": run.run_id, "idx": 1})
        )

        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(detail_response.status_code, 404)

    def test_events_endpoints_forbidden_for_other_session(self):
        run = self._make_run(session_key="allowed-session")
        self._add_paragraph(run, 1)

        session = self.client.session
        session["dummy"] = True
        session.save()

        list_response = self.client.get(reverse("analysis-events-list", kwargs={"run_id": run.run_id}))
        detail_response = self.client.get(
            reverse("analysis-event-detail", kwargs={"run_id": run.run_id, "idx": 1})
        )

        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(detail_response.status_code, 404)

    def test_events_list_uses_denormalized_fields(self):
        run = self._make_run()
        self._add_paragraph(run, 1)

        response = self.client.get(reverse("analysis-events-list", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["title"], "Событие 1 — в базе данных не найдено")
        self.assertEqual(item["preview"], "Превью 1")
        self.assertTrue(item["not_found"])
        self.assertEqual(
            item["status"],
            {
                "timestamp": "green",
                "subdivision": "yellow",
                "offenders": "red",
                "event_type": "green",
                "article": "green",
            },
        )

    def test_event_detail_uses_cache_after_first_call(self):
        run = self._make_run()
        self._add_paragraph(run, 1)
        result = AnalysisResult.objects.select_related("paragraph").get(paragraph__run=run, paragraph__idx=1)
        self.assertEqual(result.detail_payload_cache, {})
        self.assertIsNone(result.detail_payload_cached_at)

        first_response = self.client.get(
            reverse("analysis-event-detail", kwargs={"run_id": run.run_id, "idx": 1})
        )
        self.assertEqual(first_response.status_code, 200)
        result.refresh_from_db()
        first_cached_at = result.detail_payload_cached_at
        first_cache = result.detail_payload_cache
        self.assertIsNotNone(first_cached_at)
        self.assertTrue(first_cache)

        second_response = self.client.get(
            reverse("analysis-event-detail", kwargs={"run_id": run.run_id, "idx": 1})
        )
        self.assertEqual(second_response.status_code, 200)
        result.refresh_from_db()

        self.assertEqual(second_response.json(), first_response.json())
        self.assertEqual(result.detail_payload_cache, first_cache)
        self.assertEqual(result.detail_payload_cached_at, first_cached_at)
