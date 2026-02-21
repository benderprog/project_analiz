import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from docx import Document

from apps.analysis_app.forms import GENERAL_SUMMARY_PU_LABEL
from apps.analysis_app.models import AnalysisRun, CachedPU


class UploadAnalysisDocxTests(TestCase):
    databases = {"default", "portal"}

    def test_upload_form_contains_pu_dropdown(self):
        response = self.client.get(reverse("analysis-upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пограничное управление")
        self.assertContains(response, GENERAL_SUMMARY_PU_LABEL)
        self.assertNotContains(response, "Ожидают выбора ПУ")
        self.assertNotContains(response, "Определено автоматически")

    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_upload_two_files_with_general_summary_enqueues_two_tasks(self):
        docx_a = SimpleUploadedFile(
            "first.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        docx_b = SimpleUploadedFile(
            "second.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
                    delay_mock.side_effect = [
                        type("Task", (), {"id": "task-1"})(),
                        type("Task", (), {"id": "task-2"})(),
                    ]
                    response = self.client.post(
                        reverse("analysis-upload"),
                        {"selected_pu_id": "", "file": [docx_a, docx_b]},
                    )

        self.assertEqual(response.status_code, 302)
        runs = list(AnalysisRun.objects.order_by("original_filename"))
        self.assertEqual(len(runs), 2)
        for run in runs:
            self.assertEqual(run.selected_pu_id, "")
            self.assertEqual(run.selected_pu_name, GENERAL_SUMMARY_PU_LABEL)
            self.assertEqual(run.status, AnalysisRun.Status.QUEUED)
            self.assertIsNotNone(run.queued_at)
        self.assertEqual(delay_mock.call_count, 2)

    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_upload_with_selected_pu_saves_pu_name_and_id(self):
        from uuid import uuid4

        pu = CachedPU.objects.create(
            portal_pu_id=uuid4(),
            short_name="ПУ Север",
            full_name="Пограничное управление Север",
        )
        upload = SimpleUploadedFile(
            "sample.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
                    delay_mock.return_value = type("Task", (), {"id": "task-1"})()
                    response = self.client.post(
                        reverse("analysis-upload"),
                        {"selected_pu_id": str(pu.portal_pu_id), "file": upload},
                    )

        self.assertEqual(response.status_code, 302)
        run = AnalysisRun.objects.get()
        self.assertEqual(run.selected_pu_id, str(pu.portal_pu_id))
        self.assertEqual(run.selected_pu_name, "Пограничное управление Север")
        self.assertEqual(run.status, AnalysisRun.Status.QUEUED)
        delay_mock.assert_called_once_with(str(run.run_id), str(pu.portal_pu_id))

    def test_upload_docx_runs_analysis_in_sync_mode(self):
        upload = SimpleUploadedFile(
            "sample.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                response = self.client.post(
                    reverse("analysis-upload"),
                    {"selected_pu_id": "", "file": upload},
                )

        self.assertEqual(response.status_code, 302)
        run = AnalysisRun.objects.get()
        self.assertEqual(run.status, AnalysisRun.Status.DONE)
        self.assertEqual(run.selected_pu_name, GENERAL_SUMMARY_PU_LABEL)

    def test_upload_stores_original_filename_basename(self):
        upload = SimpleUploadedFile(
            "folder/nested/test_big.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                response = self.client.post(
                    reverse("analysis-upload"),
                    {"selected_pu_id": "", "file": upload},
                )

        self.assertEqual(response.status_code, 302)
        run = AnalysisRun.objects.first()
        self.assertIsNotNone(run)
        self.assertEqual(run.original_filename, "test_big.docx")

    def test_uploaded_file_is_deleted_after_sync_analysis(self):
        upload = SimpleUploadedFile(
            "sample.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir, ANALYSIS_DELETE_UPLOADS=True):
                self.client.post(
                    reverse("analysis-upload"),
                    {"selected_pu_id": "", "file": upload},
                )
                run = AnalysisRun.objects.first()
                saved_name = run.file.name
                run.refresh_from_db()
                file_path = Path(tmp_dir) / saved_name

        self.assertEqual(run.status, AnalysisRun.Status.DONE)
        self.assertFalse(file_path.exists())

    def test_queue_status_endpoint_returns_runs_with_positions(self):
        run_running = AnalysisRun.objects.create(
            original_filename="a.docx",
            file="uploads/a.docx",
            status=AnalysisRun.Status.RUNNING,
            selected_pu_name="ПУ A",
        )
        run_queued = AnalysisRun.objects.create(
            original_filename="b.docx",
            file="uploads/b.docx",
            status=AnalysisRun.Status.QUEUED,
            selected_pu_name="ПУ B",
        )

        response = self.client.get(reverse("analysis-queue-status"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("runs", payload)
        runs = {item["run_id"]: item for item in payload["runs"]}
        self.assertEqual(runs[str(run_running.run_id)]["position"], 0)
        self.assertEqual(runs[str(run_queued.run_id)]["position"], 1)
        self.assertEqual(runs[str(run_running.run_id)]["status"], AnalysisRun.Status.RUNNING)
        self.assertEqual(runs[str(run_queued.run_id)]["status"], AnalysisRun.Status.QUEUED)

    def _make_docx_bytes(self) -> bytes:
        document = Document()
        document.add_paragraph("Время 08:40 02.02.2026 без имен.")
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()
