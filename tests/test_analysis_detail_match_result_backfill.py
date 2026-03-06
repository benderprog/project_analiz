from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun
from apps.classifier.models import EventType, EventTypePattern


class AnalysisDetailMatchResultBackfillTests(TestCase):
    def _session_key(self):
        session = self.client.session
        session["analysis"] = True
        session.save()
        return session.session_key

    def test_detail_view_backfills_legacy_match_result_and_statuses(self):
        run = AnalysisRun.objects.create(
            created_session_key=self._session_key(),
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
        extract_mock.assert_called_once()
        self.assertEqual(extract_mock.call_args.args[0], "Текст абзаца")
        match_mock.assert_called_once_with(attrs, "Текст абзаца")

        selected_event = response.context["selected_event"]
        self.assertEqual(selected_event["idx"], 5)

    def test_detail_view_backfills_missing_classifier_candidates(self):
        phrase = "вещество растительного происхождения"
        t1 = EventType.objects.create(event_type="Внос/вынос")
        t2 = EventType.objects.create(event_type="Специальные действия (СД)")
        EventTypePattern.objects.create(event_type=t1, pattern=phrase, article_of_law="18.3 ч. 1")
        EventTypePattern.objects.create(event_type=t2, pattern=phrase)

        run = AnalysisRun.objects.create(
            created_session_key=self._session_key(),
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


    def test_detail_view_shows_safe_slicing_preview_with_anchor_labels(self):
        run = AnalysisRun.objects.create(
            created_session_key=self._session_key(),
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            slicing_meta={
                "analyzed_text": "line0\n<script>alert(1)</script>\nline2",
                "template_anchors": [
                    {
                        "segment_index": 0,
                        "template_anchor_start": "start template",
                        "template_anchor_end": "end template",
                        "threshold": 0.6,
                        "start": {"idx": 0, "score": 0.99, "matched_line": "line0"},
                        "end": {"idx": 2, "score": 0.88, "matched_line": "line2"},
                        "slice_text": "line1\n<script>alert(1)</script>",
                        "accepted": True,
                        "reasons": [],
                    }
                ],
                "fallback_to_full_report": True,
                "method": "none",
                "anchors_missing": True,
            },
        )
        paragraph = AnalysisParagraph.objects.create(run=run, idx=1, text="Текст абзаца")
        AnalysisResult.objects.create(paragraph=paragraph, extracted_attributes={}, match_result={"matched": False})

        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Предпросмотр обрезки / якорей", content)
        self.assertNotIn('<details class="slicing-preview" open>', content)
        self.assertIn("Fallback: анализ всей сводки", content)
        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", content)




    def test_detail_view_shows_two_inline_segments_with_anchor_lines(self):
        run = AnalysisRun.objects.create(
            created_session_key=self._session_key(),
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            slicing_meta={
                "analyzed_text": "unused",
                "template_anchors": [
                    {
                        "segment_index": 0,
                        "template_anchor_start": "start 1",
                        "template_anchor_end": "end 1",
                        "threshold_used": 0.5,
                        "start": {"idx": 0, "score": 0.91, "matched_line": "start 1"},
                        "end": {"idx": 2, "score": 0.9, "matched_line": "end 1"},
                        "slice_text": "segment one text",
                    },
                    {
                        "segment_index": 1,
                        "template_anchor_start": "start 2",
                        "template_anchor_end": "end 2",
                        "threshold_used": 0.5,
                        "start": {"idx": 3, "score": 0.88, "matched_line": "start 2"},
                        "end": {"idx": 5, "score": 0.86, "matched_line": "end 2"},
                        "slice_text": "segment two text",
                    },
                ],
                "fallback_to_full_report": False,
            },
        )
        paragraph = AnalysisParagraph.objects.create(run=run, idx=1, text="Текст абзаца")
        AnalysisResult.objects.create(paragraph=paragraph, extracted_attributes={}, match_result={"matched": False})

        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertEqual(content.count("anchor-line anchor-start"), 2)
        self.assertEqual(content.count("anchor-line anchor-end"), 2)
        self.assertIn("Якорь начала (в сводке): start 1 (score=0.9100, threshold=0.50)", content)
        self.assertIn("Якорь конца (в сводке): end 1 (score=0.9000, threshold=0.50)", content)
        self.assertIn("(score=0.8800, threshold=0.50)", content)
        self.assertLess(content.index("segment one text"), content.index("segment two text"))


    def test_detail_view_shows_open_ended_anchor_segment(self):
        run = AnalysisRun.objects.create(
            created_session_key=self._session_key(),
            file=SimpleUploadedFile(
                "report.docx",
                b"dummy",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            slicing_meta={
                "analyzed_text": "line0\nline1\nline2",
                "template_anchors": [
                    {
                        "segment_index": 1,
                        "template_anchor_start": "open start",
                        "template_anchor_end": None,
                        "threshold": 0.6,
                        "start": {"idx": 1, "score": 0.73, "matched_line": "line1"},
                        "end": {"idx": None, "score": None, "matched_line": None},
                        "slice_text": "line2",
                        "accepted": False,
                        "reasons": ["below_threshold"],
                    }
                ],
                "fallback_to_full_report": False,
                "method": "none",
                "anchors_missing": True,
            },
        )
        paragraph = AnalysisParagraph.objects.create(run=run, idx=1, text="Текст абзаца")
        AnalysisResult.objects.create(paragraph=paragraph, extracted_attributes={}, match_result={"matched": False})

        response = self.client.get(reverse("analysis-detail", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Якорь конца: отсутствует (сегмент до конца документа)", content)
        self.assertIn("line2", content)
