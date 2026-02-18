import tempfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from docx import Document

from apps.analysis_app.models import AnalysisRun, CachedPU


class UploadAnalysisDocxTests(TestCase):
    databases = {"default", "portal"}


    def test_selection_renders_progress_mode(self):
        docx_bytes = self._make_docx_bytes()
        upload = SimpleUploadedFile(
            "sample.docx",
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                self.client.post(reverse("analysis-upload"), {"file": upload})
                run = AnalysisRun.objects.first()
                response = self.client.post(
                    reverse("analysis-upload"),
                    {"upload_id": run.run_id, "selected_pu_id": ""},
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span id="analysis-filename">sample.docx</span>', html=True)
        self.assertContains(response, 'id="analysis-pu-wrap" style="display:none;"')
        self.assertContains(response, "Смотреть результаты")
        self.assertContains(response, 'target="_blank"')
        status_response = self.client.get(reverse("analysis-status", kwargs={"run_id": run.run_id}))
        self.assertEqual(status_response.status_code, 200)
        payload = status_response.json()
        self.assertIn(payload["status"], {AnalysisRun.Status.DONE, AnalysisRun.Status.RUNNING, AnalysisRun.Status.QUEUED})
        self.assertIn("worker_ok", payload)
        self.assertEqual(payload["uploaded_filename"], "sample.docx")
        self.assertEqual(payload["selected_pu_name"], "Общая сводка")

    def test_upload_stores_original_filename_basename(self):
        docx_bytes = self._make_docx_bytes()
        upload = SimpleUploadedFile(
            "folder/nested/test_big.docx",
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                response = self.client.post(reverse("analysis-upload"), {"file": upload})

        self.assertEqual(response.status_code, 200)
        run = AnalysisRun.objects.first()
        self.assertIsNotNone(run)
        self.assertEqual(run.original_filename, "test_big.docx")

    def _make_docx_bytes(self) -> bytes:
        document = Document()
        document.add_paragraph("Время 08:40 02.02.2026 без имен.")
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def test_upload_docx_runs_analysis(self):
        docx_bytes = self._make_docx_bytes()
        upload = SimpleUploadedFile(
            "sample.docx",
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                response = self.client.post(reverse("analysis-upload"), {"file": upload})

                self.assertEqual(response.status_code, 200)
                run = AnalysisRun.objects.first()
                self.assertIsNotNone(run)

                response = self.client.post(
                    reverse("analysis-upload"),
                    {"upload_id": run.run_id, "selected_pu_id": ""},
                )

        self.assertIn(response.status_code, {200, 302})
        run.refresh_from_db()
        self.assertEqual(run.status, AnalysisRun.Status.DONE)

    def test_progress_includes_selected_pu_name(self):
        from uuid import uuid4

        pu = CachedPU.objects.create(
            portal_pu_id=uuid4(),
            short_name="ПУ Север",
            full_name="Пограничное управление Север",
        )
        docx_bytes = self._make_docx_bytes()
        upload = SimpleUploadedFile(
            "sample.docx",
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                self.client.post(reverse("analysis-upload"), {"file": upload})
                run = AnalysisRun.objects.first()
                response = self.client.post(
                    reverse("analysis-upload"),
                    {"upload_id": run.run_id, "selected_pu_id": str(pu.portal_pu_id)},
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span id="analysis-filename">sample.docx</span>', html=True)
        self.assertContains(response, '<span id="analysis-pu-name">Пограничное управление Север</span>', html=True)
        run.refresh_from_db()
        self.assertEqual(run.selected_pu_name, "Пограничное управление Север")
        status_response = self.client.get(reverse("analysis-status", kwargs={"run_id": run.run_id}))
        payload = status_response.json()
        self.assertEqual(payload["selected_pu_name"], "Пограничное управление Север")

    def test_uploaded_file_is_deleted_after_sync_analysis(self):
        docx_bytes = self._make_docx_bytes()
        upload = SimpleUploadedFile(
            "sample.docx",
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir, ANALYSIS_DELETE_UPLOADS=True):
                self.client.post(reverse("analysis-upload"), {"file": upload})
                run = AnalysisRun.objects.first()
                saved_name = run.file.name
                self.client.post(
                    reverse("analysis-upload"),
                    {"upload_id": run.run_id, "selected_pu_id": ""},
                )
                run.refresh_from_db()
                file_path = Path(tmp_dir) / saved_name

        self.assertEqual(run.status, AnalysisRun.Status.DONE)
        self.assertFalse(file_path.exists())
