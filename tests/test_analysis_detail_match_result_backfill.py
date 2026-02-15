from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun


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
