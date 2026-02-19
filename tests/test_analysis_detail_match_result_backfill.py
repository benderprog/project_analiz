from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun
from apps.classifier.models import EventType, EventTypePattern


class AnalysisDetailMatchResultBackfillTests(TestCase):
    def test_detail_view_backfills_legacy_match_result_and_statuses(self):
        run = AnalysisRun.objects.create(
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )
        paragraph = AnalysisParagraph.objects.create(run=run, idx=5, text="Текст абзаца")
        AnalysisResult.objects.create(
            paragraph=paragraph,
            extracted_attributes={},
            match_result={"matched": True, "predicted": None},
        )

        attrs = SimpleNamespace()
        rebuilt_match_result = {
            "matched": True,
            "event_type_ok": True,
            "article_ok": False,
            "predicted": {
                "event_type": "Несоблюдение режима",
                "article_of_law": "18.8 ч.1",
                "event_pattern": {"event_type_label": "Несоблюдение режима"},
            },
            "portal": {
                "event_type": "Несоблюдение режима",
                "article_of_law": "18.8 ч.2",
            },
        }

        with (
            patch("apps.analysis_app.views.extract_attributes", return_value=attrs) as extract_mock,
            patch("apps.analysis_app.views.match_event", return_value=rebuilt_match_result) as match_mock,
        ):
            response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 200)
        extract_mock.assert_called_once_with("Текст абзаца", selected_pu_id=None)
        match_mock.assert_called_once_with(attrs, "Текст абзаца")

        paragraph.refresh_from_db()
        saved = paragraph.result.match_result
        self.assertEqual(saved["event_type_ok"], True)
        self.assertEqual(saved["article_ok"], False)
        self.assertEqual(saved["predicted"]["event_type"], "Несоблюдение режима")
        self.assertEqual(saved["predicted"]["article_of_law"], "18.8 ч.1")

        selected_event = response.context["selected_event"]
        self.assertEqual(selected_event["idx"], 5)
        self.assertEqual(selected_event["status"]["event_type"], "green")
        self.assertEqual(selected_event["status"]["article"], "red")

    def test_detail_view_backfills_missing_classifier_candidates(self):
        phrase = "вещество растительного происхождения"
        t1 = EventType.objects.create(event_type="Внос/вынос")
        t2 = EventType.objects.create(event_type="Специальные действия (СД)")
        EventTypePattern.objects.create(event_type=t1, pattern=phrase, article_of_law="18.3 ч. 1")
        EventTypePattern.objects.create(event_type=t2, pattern=phrase)

        run = AnalysisRun.objects.create(
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )
        paragraph = AnalysisParagraph.objects.create(
            run=run,
            idx=1,
            text=f"В сводке указано: {phrase}.",
        )
        AnalysisResult.objects.create(
            paragraph=paragraph,
            extracted_attributes={"article_spans": [], "date_span": None, "time_span": None},
            match_result={
                "matched": False,
                "event_type_ok": None,
                "article_ok": False,
                "article_classifier_ok": False,
                "article_status": "red",
                "predicted": {
                    "event_type": "Внос/вынос",
                    "best_pattern_text": phrase,
                    "classifier_candidates": [],
                    "classifier_pattern_candidates": [],
                },
            },
        )

        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))
        self.assertEqual(response.status_code, 200)

        paragraph.refresh_from_db()
        predicted = (paragraph.result.match_result or {}).get("predicted") or {}
        candidates = predicted.get("classifier_candidates") or []
        self.assertEqual(len(candidates), 2)
        self.assertEqual(predicted.get("classifier_pattern_candidates"), candidates)
        by_type = {item.get("event_type_name"): item for item in candidates}
        self.assertEqual(by_type["Внос/вынос"].get("classifier_article"), "18.3 ч. 1")
