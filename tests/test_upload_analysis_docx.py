import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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
    def test_upload_two_files_with_general_summary_creates_pending_runs(self):
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
            self.assertEqual(run.status, AnalysisRun.Status.CREATED)
            self.assertIsNone(run.queued_at)
            self.assertFalse(run.celery_task_id)

    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_upload_with_selected_pu_saves_pu_name_and_id_in_pending_run(self):
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
                response = self.client.post(
                    reverse("analysis-upload"),
                    {"selected_pu_id": str(pu.portal_pu_id), "file": upload},
                )

        self.assertEqual(response.status_code, 302)
        run = AnalysisRun.objects.get()
        self.assertEqual(run.selected_pu_id, str(pu.portal_pu_id))
        self.assertEqual(run.selected_pu_name, "Пограничное управление Север")
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)
        self.assertFalse(run.celery_task_id)

    def test_upload_docx_creates_pending_run_in_sync_mode(self):
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
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)
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

    def test_uploaded_file_is_not_deleted_before_enqueue(self):
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

        self.assertEqual(run.status, AnalysisRun.Status.CREATED)
        self.assertTrue(file_path.exists())

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


    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_pending_block_prefills_selected_pu(self):
        from uuid import uuid4

        pu = CachedPU.objects.create(
            portal_pu_id=uuid4(),
            short_name="ПУ Юг",
            full_name="Пограничное управление Юг",
        )
        upload = SimpleUploadedFile(
            "prefill.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                self.client.post(
                    reverse("analysis-upload"),
                    {"selected_pu_id": str(pu.portal_pu_id), "file": upload},
                )
                response = self.client.get(reverse("analysis-upload"))

        self.assertContains(response, 'value="%s" selected' % pu.portal_pu_id)
        self.assertContains(response, "Запустить в очередь")

    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_submitting_pending_selection_enqueues_only_selected_run(self):
        from uuid import uuid4

        pu = CachedPU.objects.create(
            portal_pu_id=uuid4(),
            short_name="ПУ Запад",
            full_name="Пограничное управление Запад",
        )
        session = self.client.session
        session.create()
        session_key = session.session_key

        run_a = AnalysisRun.objects.create(
            original_filename="a.docx",
            file="uploads/a.docx",
            status=AnalysisRun.Status.CREATED,
            selected_pu_id="",
            selected_pu_name=GENERAL_SUMMARY_PU_LABEL,
            created_session_key=session_key or "",
        )
        run_b = AnalysisRun.objects.create(
            original_filename="b.docx",
            file="uploads/b.docx",
            status=AnalysisRun.Status.CREATED,
            selected_pu_id="",
            selected_pu_name=GENERAL_SUMMARY_PU_LABEL,
            created_session_key=run_a.created_session_key,
        )

        with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
            delay_mock.return_value = type("Task", (), {"id": "task-1"})()
            response = self.client.post(
                reverse("analysis-upload"),
                {"upload_id": str(run_a.run_id), "selected_pu_id": str(pu.portal_pu_id)},
            )

        self.assertEqual(response.status_code, 302)
        run_a.refresh_from_db()
        run_b.refresh_from_db()
        self.assertEqual(run_a.status, AnalysisRun.Status.QUEUED)
        self.assertEqual(run_a.selected_pu_id, str(pu.portal_pu_id))
        self.assertEqual(run_b.status, AnalysisRun.Status.CREATED)
        delay_mock.assert_called_once_with(str(run_a.run_id), str(pu.portal_pu_id))


    def test_upload_queue_pagination_shows_second_page(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        for idx in range(21):
            AnalysisRun.objects.create(
                original_filename=f"queued-{idx}.docx",
                file=f"uploads/queued-{idx}.docx",
                status=AnalysisRun.Status.QUEUED,
                created_session_key=session_key,
            )

        response_page_1 = self.client.get(reverse("analysis-upload"))
        response_page_2 = self.client.get(reverse("analysis-upload"), {"queue_page": 2})

        self.assertEqual(response_page_1.status_code, 200)
        self.assertEqual(response_page_2.status_code, 200)
        self.assertContains(response_page_1, "Страница 1 из 2")
        self.assertContains(response_page_2, "Страница 2 из 2")
        self.assertContains(response_page_2, "queued-0.docx")

    def test_queue_reset_cancels_only_not_started_queued_runs(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        queued_not_started = AnalysisRun.objects.create(
            original_filename="queued.docx",
            file="uploads/queued.docx",
            status=AnalysisRun.Status.QUEUED,
            created_session_key=session_key,
        )
        running = AnalysisRun.objects.create(
            original_filename="running.docx",
            file="uploads/running.docx",
            status=AnalysisRun.Status.RUNNING,
            started_at=timezone.now(),
            created_session_key=session_key,
        )
        queued_started = AnalysisRun.objects.create(
            original_filename="queued-started.docx",
            file="uploads/queued-started.docx",
            status=AnalysisRun.Status.QUEUED,
            started_at=timezone.now(),
            created_session_key=session_key,
        )

        response = self.client.post(reverse("analysis-queue-reset"), {"queue_page": "1"})

        self.assertEqual(response.status_code, 302)
        queued_not_started.refresh_from_db()
        running.refresh_from_db()
        queued_started.refresh_from_db()

        self.assertEqual(queued_not_started.status, AnalysisRun.Status.CANCELED)
        self.assertEqual(queued_not_started.error_message, "Queue reset by operator")
        self.assertIsNotNone(queued_not_started.finished_at)
        self.assertEqual(running.status, AnalysisRun.Status.RUNNING)
        self.assertEqual(queued_started.status, AnalysisRun.Status.QUEUED)

    def test_queue_reset_is_scoped_to_current_authenticated_user(self):
        User = get_user_model()
        user_a = User.objects.create_user(username="user-a", password="test-pass")
        user_b = User.objects.create_user(username="user-b", password="test-pass")

        run_a = AnalysisRun.objects.create(
            original_filename="a.docx",
            file="uploads/a.docx",
            status=AnalysisRun.Status.QUEUED,
            uploaded_by=user_a,
        )
        run_b = AnalysisRun.objects.create(
            original_filename="b.docx",
            file="uploads/b.docx",
            status=AnalysisRun.Status.QUEUED,
            uploaded_by=user_b,
        )

        self.client.force_login(user_a)
        response = self.client.post(reverse("analysis-queue-reset"), {"queue_page": "1"})
        self.assertEqual(response.status_code, 302)

        run_a.refresh_from_db()
        run_b.refresh_from_db()
        self.assertEqual(run_a.status, AnalysisRun.Status.CANCELED)
        self.assertEqual(run_b.status, AnalysisRun.Status.QUEUED)


    def test_pending_run_cancel_changes_status_to_canceled(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        run = AnalysisRun.objects.create(
            original_filename="cancel-me.docx",
            file="uploads/cancel-me.docx",
            status=AnalysisRun.Status.CREATED,
            created_session_key=session_key,
        )

        response = self.client.post(reverse("analysis-run-cancel", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        run.refresh_from_db()
        self.assertEqual(run.status, AnalysisRun.Status.CANCELED)
        self.assertEqual(run.error_message, "Canceled by operator")
        self.assertIsNotNone(run.finished_at)

    def test_pending_run_cancel_denies_other_user_run(self):
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="test-pass")
        other = User.objects.create_user(username="other", password="test-pass")

        run = AnalysisRun.objects.create(
            original_filename="owner.docx",
            file="uploads/owner.docx",
            status=AnalysisRun.Status.CREATED,
            uploaded_by=owner,
        )

        self.client.force_login(other)
        response = self.client.post(reverse("analysis-run-cancel", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        run.refresh_from_db()
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)


    def test_pending_run_cancel_denies_other_session_run(self):
        owner_client = self.client_class()
        owner_session = owner_client.session
        owner_session.create()
        owner_session_key = owner_session.session_key or ""

        run = AnalysisRun.objects.create(
            original_filename="session-owner.docx",
            file="uploads/session-owner.docx",
            status=AnalysisRun.Status.CREATED,
            created_session_key=owner_session_key,
        )

        outsider_client = self.client_class()
        outsider_session = outsider_client.session
        outsider_session.create()

        response = outsider_client.post(reverse("analysis-run-cancel", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        run.refresh_from_db()
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)

    def test_pending_run_cancel_rejects_non_created_statuses(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        for status in [AnalysisRun.Status.QUEUED, AnalysisRun.Status.RUNNING, AnalysisRun.Status.DONE]:
            run = AnalysisRun.objects.create(
                original_filename=f"{status}.docx",
                file=f"uploads/{status}.docx",
                status=status,
                created_session_key=session_key,
            )

            response = self.client.post(reverse("analysis-run-cancel", kwargs={"run_id": run.run_id}))
            self.assertEqual(response.status_code, 302)
            run.refresh_from_db()
            self.assertEqual(run.status, status)

    def _make_docx_bytes(self) -> bytes:
        document = Document()
        document.add_paragraph("Время 08:40 02.02.2026 без имен.")
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()
