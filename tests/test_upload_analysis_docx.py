import tempfile
from io import BytesIO
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from docx import Document

from apps.analysis_app.forms import GENERAL_SUMMARY_PU_LABEL
from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun, CachedPU, FeatureFlags


class UploadAnalysisDocxTests(TestCase):
    databases = {"default", "portal"}

    def test_upload_form_contains_pu_dropdown(self):
        response = self.client.get(reverse("analysis-upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пограничное управление")
        self.assertContains(response, GENERAL_SUMMARY_PU_LABEL)
        self.assertNotContains(response, "Ожидают выбора ПУ")
        self.assertNotContains(response, "Определено автоматически")


    def test_multiple_file_field_clean_handles_list_without_super_typeerror(self):
        from apps.analysis_app.forms import MultipleFileField

        field = MultipleFileField(required=True)
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

        cleaned = field.clean([docx_a, docx_b])

        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0].name, "first.docx")
        self.assertEqual(cleaned[1].name, "second.docx")

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
    def test_upload_with_selected_pu_single_file_creates_pending_run(self):
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
        delay_mock.assert_not_called()

    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_upload_docx_single_file_creates_pending_with_general_summary(self):
        upload = SimpleUploadedFile(
            "sample.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
                    response = self.client.post(
                        reverse("analysis-upload"),
                        {"selected_pu_id": "", "file": upload},
                    )

        self.assertEqual(response.status_code, 302)
        run = AnalysisRun.objects.get()
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)
        self.assertEqual(run.selected_pu_name, GENERAL_SUMMARY_PU_LABEL)
        self.assertFalse(run.celery_task_id)
        delay_mock.assert_not_called()


    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_upload_post_docx_does_not_return_500(self):
        upload = SimpleUploadedFile(
            "smoke.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
                    delay_mock.return_value = type("Task", (), {"id": "task-smoke"})()
                    response = self.client.post(
                        reverse("analysis-upload"),
                        {"selected_pu_id": "", "file": upload},
                    )

        self.assertEqual(response.status_code, 302)

    def test_upload_stores_original_filename_basename(self):
        upload = SimpleUploadedFile(
            "folder/nested/test_big.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
                    delay_mock.return_value = type("Task", (), {"id": "task-name"})()
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
                with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
                    delay_mock.return_value = type("Task", (), {"id": "task-keep-file"})()
                    self.client.post(
                        reverse("analysis-upload"),
                        {"selected_pu_id": "", "file": upload},
                    )
                run = AnalysisRun.objects.first()
                saved_name = run.file.name
                run.refresh_from_db()
                file_path = Path(tmp_dir) / saved_name

        self.assertEqual(run.status, AnalysisRun.Status.QUEUED)
        self.assertTrue(file_path.exists())



    def test_queue_status_excludes_canceled_runs(self):
        queued = AnalysisRun.objects.create(
            original_filename="queued.docx",
            file="uploads/queued.docx",
            status=AnalysisRun.Status.QUEUED,
        )
        AnalysisRun.objects.create(
            original_filename="canceled.docx",
            file="uploads/canceled.docx",
            status=AnalysisRun.Status.CANCELED,
        )

        response = self.client.get(reverse("analysis-queue-status"))

        self.assertEqual(response.status_code, 200)
        run_ids = {item["run_id"] for item in response.json()["runs"]}
        self.assertIn(str(queued.run_id), run_ids)
        self.assertNotIn(
            str(AnalysisRun.objects.get(original_filename="canceled.docx").run_id),
            run_ids,
        )

    def test_upload_page_hides_canceled_runs(self):
        AnalysisRun.objects.create(
            original_filename="visible.docx",
            file="uploads/visible.docx",
            status=AnalysisRun.Status.QUEUED,
        )
        AnalysisRun.objects.create(
            original_filename="hidden.docx",
            file="uploads/hidden.docx",
            status=AnalysisRun.Status.CANCELED,
        )

        response = self.client.get(reverse("analysis-upload"))

        self.assertContains(response, "visible.docx")
        self.assertNotContains(response, "hidden.docx")

    def test_upload_page_shows_delete_action_and_not_queue_reset(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        AnalysisRun.objects.create(
            original_filename="visible.docx",
            file="uploads/visible.docx",
            status=AnalysisRun.Status.QUEUED,
            created_session_key=session_key,
        )

        response = self.client.get(reverse("analysis-upload"))

        self.assertNotContains(response, "Сбросить очередь")
        self.assertContains(response, "Удалить")
        self.assertContains(response, "Удалить все")


    def test_queue_status_elapsed_and_results_url(self):
        now = timezone.now()
        run_running = AnalysisRun.objects.create(
            original_filename="running.docx",
            file="uploads/running.docx",
            status=AnalysisRun.Status.RUNNING,
            started_at=now - timedelta(seconds=75),
        )
        run_done = AnalysisRun.objects.create(
            original_filename="done.docx",
            file="uploads/done.docx",
            status=AnalysisRun.Status.DONE,
            started_at=now - timedelta(seconds=3605),
            finished_at=now,
            progress_total=5,
            progress_done=4,
        )
        run_failed = AnalysisRun.objects.create(
            original_filename="failed.docx",
            file="uploads/failed.docx",
            status=AnalysisRun.Status.FAILED,
            error_message="boom",
        )

        response = self.client.get(reverse("analysis-queue-status"))
        runs = {item["run_id"]: item for item in response.json()["runs"]}

        self.assertGreaterEqual(runs[str(run_running.run_id)]["elapsed_seconds"], 75)
        self.assertTrue(runs[str(run_running.run_id)]["elapsed_display"].startswith("00:01:"))
        self.assertEqual(runs[str(run_done.run_id)]["elapsed_seconds"], 3605)
        self.assertEqual(runs[str(run_done.run_id)]["elapsed_display"], "01:00:05")
        self.assertEqual(
            runs[str(run_done.run_id)]["results_url"],
            reverse("analysis-detail", kwargs={"run_id": run_done.run_id}),
        )
        self.assertEqual(runs[str(run_done.run_id)]["progress_percent"], 100)
        self.assertEqual(runs[str(run_done.run_id)]["progress_label"], "5 / 5 (100%)")
        self.assertTrue(runs[str(run_done.run_id)]["has_results"])
        self.assertFalse(runs[str(run_failed.run_id)]["has_results"])
        self.assertEqual(runs[str(run_failed.run_id)]["results_url"], "")
        self.assertRegex(runs[str(run_running.run_id)]["started_at_display"], r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$")


    @override_settings(USE_TZ=True, TIME_ZONE="Europe/Moscow")
    def test_queue_status_started_at_display_uses_server_local_time(self):
        run = AnalysisRun.objects.create(
            original_filename="tz.docx",
            file="uploads/tz.docx",
            status=AnalysisRun.Status.RUNNING,
            started_at=datetime(2026, 2, 1, 20, 15, tzinfo=dt_timezone.utc),
        )

        with timezone.override("Europe/Moscow"), patch("django.utils.timezone.localdate", return_value=datetime(2026, 2, 2, 0, 0).date()):
            response = self.client.get(reverse("analysis-queue-status"))

        payload = {item["run_id"]: item for item in response.json()["runs"]}
        self.assertEqual(payload[str(run.run_id)]["started_at_display"], "01.02.2026 23:15")
        self.assertNotEqual(payload[str(run.run_id)]["started_at_display"], "20:15")

    def test_queue_status_progress_payload(self):
        run = AnalysisRun.objects.create(
            original_filename="progress.docx",
            file="uploads/progress.docx",
            status=AnalysisRun.Status.RUNNING,
            progress_total=10,
            progress_done=3,
        )

        response = self.client.get(reverse("analysis-queue-status"))

        self.assertEqual(response.status_code, 200)
        payload = {item["run_id"]: item for item in response.json()["runs"]}
        run_payload = payload[str(run.run_id)]
        self.assertEqual(run_payload["progress_total"], 10)
        self.assertEqual(run_payload["progress_done"], 3)
        self.assertEqual(run_payload["progress_percent"], 30)
        self.assertEqual(run_payload["progress_label"], "3 / 10 (30%)")

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


    def test_upload_and_queue_templates_render_started_at_display(self):
        now = timezone.now()
        session = self.client.session
        session.create()
        session_key = session.session_key or ""
        AnalysisRun.objects.create(
            original_filename="started.docx",
            file="uploads/started.docx",
            status=AnalysisRun.Status.RUNNING,
            started_at=now,
            created_session_key=session_key,
        )

        upload_response = self.client.get(reverse("analysis-upload"))
        queue_response = self.client.get(reverse("analysis-queue"))

        self.assertContains(upload_response, "Время запуска")
        self.assertContains(queue_response, "Время запуска")
        self.assertRegex(upload_response.content.decode("utf-8"), r">\d{2}:\d{2}<")
        self.assertRegex(queue_response.content.decode("utf-8"), r">\d{2}:\d{2}<")

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

        upload_2 = SimpleUploadedFile(
            "prefill-2.docx",
            self._make_docx_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                self.client.post(
                    reverse("analysis-upload"),
                    {"selected_pu_id": str(pu.portal_pu_id), "file": [upload, upload_2]},
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

    def test_queue_item_delete_removes_queued_run_and_related_results(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                run = AnalysisRun.objects.create(
                    original_filename="queued.docx",
                    file=SimpleUploadedFile("queued.docx", b"queued"),
                    status=AnalysisRun.Status.QUEUED,
                    created_session_key=session_key,
                )
                paragraph = AnalysisParagraph.objects.create(run=run, idx=0, text="p")
                AnalysisResult.objects.create(paragraph=paragraph, matched=False)
                run.debug_package_file.save("debug_queued.zip", ContentFile(b"dbg"), save=True)

                upload_path = Path(tmp_dir) / run.file.name
                debug_path = Path(tmp_dir) / run.debug_package_file.name
                self.assertTrue(upload_path.exists())
                self.assertTrue(debug_path.exists())

                response = self.client.post(reverse("analysis-run-delete", kwargs={"run_id": run.run_id}))

                self.assertEqual(response.status_code, 302)
                self.assertFalse(AnalysisRun.objects.filter(run_id=run.run_id).exists())
                self.assertFalse(AnalysisParagraph.objects.filter(paragraph_id=paragraph.paragraph_id).exists())
                self.assertFalse(AnalysisResult.objects.filter(paragraph=paragraph).exists())
                self.assertFalse(upload_path.exists())
                self.assertFalse(debug_path.exists())

    def test_queue_item_delete_removes_done_run_and_related_results(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        run = AnalysisRun.objects.create(
            original_filename="done.docx",
            file="uploads/done.docx",
            status=AnalysisRun.Status.DONE,
            created_session_key=session_key,
        )
        paragraph = AnalysisParagraph.objects.create(run=run, idx=0, text="p")
        AnalysisResult.objects.create(paragraph=paragraph, matched=True)

        response = self.client.post(reverse("analysis-run-delete", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AnalysisRun.objects.filter(run_id=run.run_id).exists())
        self.assertFalse(AnalysisParagraph.objects.filter(paragraph_id=paragraph.paragraph_id).exists())

    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_queue_item_delete_revokes_running_task_and_deletes_run(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        run = AnalysisRun.objects.create(
            original_filename="running.docx",
            file="uploads/running.docx",
            status=AnalysisRun.Status.RUNNING,
            celery_task_id="task-running-1",
            started_at=timezone.now(),
            created_session_key=session_key,
        )

        with patch("config.celery.app.control.revoke") as revoke_mock:
            response = self.client.post(reverse("analysis-run-delete", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        revoke_mock.assert_called_once_with("task-running-1", terminate=True)
        self.assertFalse(AnalysisRun.objects.filter(run_id=run.run_id).exists())

    def test_queue_item_delete_denies_other_user_run(self):
        User = get_user_model()
        owner = User.objects.create_user(username="owner-delete", password="test-pass")
        other = User.objects.create_user(username="other-delete", password="test-pass")

        run = AnalysisRun.objects.create(
            original_filename="owner.docx",
            file="uploads/owner.docx",
            status=AnalysisRun.Status.DONE,
            uploaded_by=owner,
        )

        self.client.force_login(other)
        response = self.client.post(reverse("analysis-run-delete", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AnalysisRun.objects.filter(run_id=run.run_id).exists())

    def test_queue_item_delete_allows_staff_for_foreign_run(self):
        User = get_user_model()
        owner = User.objects.create_user(username="owner-staff", password="test-pass")
        staff = User.objects.create_user(username="staff-delete", password="test-pass", is_staff=True)

        run = AnalysisRun.objects.create(
            original_filename="owner-staff.docx",
            file="uploads/owner-staff.docx",
            status=AnalysisRun.Status.DONE,
            uploaded_by=owner,
        )

        self.client.force_login(staff)
        response = self.client.post(reverse("analysis-run-delete", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AnalysisRun.objects.filter(run_id=run.run_id).exists())

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



    def test_upload_dropzone_script_does_not_autosubmit_and_updates_selected_files_hint(self):
        script = Path("static/analysis_app/js/upload_dropzone.js").read_text(encoding="utf-8")

        self.assertNotIn("requestSubmit", script)
        self.assertIn("selected-files-hint", script)
        self.assertIn("Выбрано файлов", script)

    def test_upload_page_layout_moves_pu_under_dropzone_and_hides_parameters_block(self):
        response = self.client.get(reverse("analysis-upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ПУ:")
        self.assertContains(response, "Применяется к новым файлам; для каждого ожидающего можно изменить отдельно.")
        self.assertNotContains(response, "Параметры")

    def test_pending_section_has_start_all_and_delete_buttons(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        AnalysisRun.objects.create(
            original_filename="pending-a.docx",
            file="uploads/pending-a.docx",
            status=AnalysisRun.Status.CREATED,
            created_session_key=session_key,
        )
        AnalysisRun.objects.create(
            original_filename="pending-b.docx",
            file="uploads/pending-b.docx",
            status=AnalysisRun.Status.CREATED,
            created_session_key=session_key,
        )

        response = self.client.get(reverse("analysis-upload"))

        self.assertContains(response, "Запустить все")
        self.assertContains(response, "Запустить в очередь")
        self.assertContains(response, "Удалить")
        self.assertContains(response, "Удалить все")

    @override_settings(ANALYSIS_USE_SYNC_TASKS=False)
    def test_start_all_enqueues_only_current_user_pending_runs(self):
        User = get_user_model()
        owner = User.objects.create_user(username="startall-owner", password="test-pass")
        other = User.objects.create_user(username="startall-other", password="test-pass")

        my_run_1 = AnalysisRun.objects.create(
            original_filename="owner-1.docx",
            file="uploads/owner-1.docx",
            status=AnalysisRun.Status.CREATED,
            uploaded_by=owner,
        )
        my_run_2 = AnalysisRun.objects.create(
            original_filename="owner-2.docx",
            file="uploads/owner-2.docx",
            status=AnalysisRun.Status.CREATED,
            uploaded_by=owner,
        )
        foreign_run = AnalysisRun.objects.create(
            original_filename="other-1.docx",
            file="uploads/other-1.docx",
            status=AnalysisRun.Status.CREATED,
            uploaded_by=other,
        )

        self.client.force_login(owner)
        with patch("apps.analysis_app.tasks.run_docx_analysis.delay") as delay_mock:
            delay_mock.side_effect = [type("Task", (), {"id": "task-startall-1"})(), type("Task", (), {"id": "task-startall-2"})()]
            response = self.client.post(reverse("analysis-pending-start-all"))

        self.assertEqual(response.status_code, 302)
        my_run_1.refresh_from_db()
        my_run_2.refresh_from_db()
        foreign_run.refresh_from_db()
        self.assertEqual(my_run_1.status, AnalysisRun.Status.QUEUED)
        self.assertEqual(my_run_2.status, AnalysisRun.Status.QUEUED)
        self.assertEqual(foreign_run.status, AnalysisRun.Status.CREATED)
        self.assertEqual(delay_mock.call_count, 2)



    def test_pending_delete_all_deletes_only_current_user_pending_runs(self):
        User = get_user_model()
        owner = User.objects.create_user(username="deleteall-owner", password="test-pass")
        other = User.objects.create_user(username="deleteall-other", password="test-pass")

        my_created = AnalysisRun.objects.create(
            original_filename="owner-created.docx",
            file="uploads/owner-created.docx",
            status=AnalysisRun.Status.CREATED,
            uploaded_by=owner,
        )
        my_queued = AnalysisRun.objects.create(
            original_filename="owner-queued.docx",
            file="uploads/owner-queued.docx",
            status=AnalysisRun.Status.QUEUED,
            uploaded_by=owner,
        )
        foreign_created = AnalysisRun.objects.create(
            original_filename="other-created.docx",
            file="uploads/other-created.docx",
            status=AnalysisRun.Status.CREATED,
            uploaded_by=other,
        )

        self.client.force_login(owner)
        response = self.client.post(reverse("analysis-pending-delete-all"))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AnalysisRun.objects.filter(run_id=my_created.run_id).exists())
        self.assertTrue(AnalysisRun.objects.filter(run_id=my_queued.run_id).exists())
        self.assertTrue(AnalysisRun.objects.filter(run_id=foreign_created.run_id).exists())

    def test_pending_delete_all_deletes_only_current_session_pending_runs(self):
        owner_client = self.client_class()
        owner_session = owner_client.session
        owner_session.create()
        owner_key = owner_session.session_key or ""

        outsider_client = self.client_class()
        outsider_session = outsider_client.session
        outsider_session.create()
        outsider_key = outsider_session.session_key or ""

        my_created = AnalysisRun.objects.create(
            original_filename="session-created.docx",
            file="uploads/session-created.docx",
            status=AnalysisRun.Status.CREATED,
            created_session_key=owner_key,
        )
        foreign_created = AnalysisRun.objects.create(
            original_filename="session-foreign.docx",
            file="uploads/session-foreign.docx",
            status=AnalysisRun.Status.CREATED,
            created_session_key=outsider_key,
        )

        response = owner_client.post(reverse("analysis-pending-delete-all"))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AnalysisRun.objects.filter(run_id=my_created.run_id).exists())
        self.assertTrue(AnalysisRun.objects.filter(run_id=foreign_created.run_id).exists())

    def test_queue_page_rows_include_stable_refresh_hooks(self):
        AnalysisRun.objects.create(
            original_filename="queue-hooks.docx",
            file="uploads/queue-hooks.docx",
            status=AnalysisRun.Status.RUNNING,
            progress_total=10,
            progress_done=5,
        )

        response = self.client.get(reverse("analysis-queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-run-id="')
        self.assertContains(response, 'data-role="status-badge"')
        self.assertContains(response, 'data-role="progress-text"')
        self.assertContains(response, 'data-role="progress-bar"')
        self.assertContains(response, 'data-role="elapsed"')

    def test_delete_endpoint_removes_pending_created_run(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        run = AnalysisRun.objects.create(
            original_filename="pending-delete.docx",
            file="uploads/pending-delete.docx",
            status=AnalysisRun.Status.CREATED,
            created_session_key=session_key,
        )

        response = self.client.post(reverse("analysis-run-delete", kwargs={"run_id": run.run_id}))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AnalysisRun.objects.filter(run_id=run.run_id).exists())

    def test_delete_endpoint_redirects_back_to_queue_when_next_is_queue_url(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        run = AnalysisRun.objects.create(
            original_filename="queue-delete.docx",
            file="uploads/queue-delete.docx",
            status=AnalysisRun.Status.DONE,
            created_session_key=session_key,
        )

        response = self.client.post(
            reverse("analysis-run-delete", kwargs={"run_id": run.run_id}),
            {"queue_page": "2", "next": f"{reverse('analysis-queue')}?queue_page=2"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('analysis-queue')}?queue_page=2")
        self.assertFalse(AnalysisRun.objects.filter(run_id=run.run_id).exists())

    def test_queue_page_delete_form_has_next_to_stay_on_queue(self):
        session = self.client.session
        session.create()
        session_key = session.session_key or ""

        AnalysisRun.objects.create(
            original_filename="queue-form.docx",
            file="uploads/queue-form.docx",
            status=AnalysisRun.Status.DONE,
            created_session_key=session_key,
        )

        response = self.client.get(reverse("analysis-queue"), {"queue_page": 2})

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'name="next" value="{reverse("analysis-queue")}?queue_page=2"',
            html=False,
        )

    def _make_docx_bytes(self) -> bytes:
        document = Document()
        document.add_paragraph("Время 08:40 02.02.2026 без имен.")
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()


    def test_queue_status_includes_debug_pipeline_only_when_debug_on(self):
        run = AnalysisRun.objects.create(
            original_filename="debug-pipeline.docx",
            file="uploads/debug-pipeline.docx",
            status=AnalysisRun.Status.RUNNING,
            debug_pipeline={"current_stage": "matching", "stages": [{"name": "parsing", "ms": 200}]},
        )

        flags = FeatureFlags.get_solo()
        flags.debug_mode = False
        flags.save(update_fields=["debug_mode", "updated_at"])
        response_off = self.client.get(reverse("analysis-queue-status"))
        payload_off = {item["run_id"]: item for item in response_off.json()["runs"]}[str(run.run_id)]
        self.assertNotIn("debug_pipeline", payload_off)

        flags.debug_mode = True
        flags.save(update_fields=["debug_mode", "updated_at"])
        response_on = self.client.get(reverse("analysis-queue-status"))
        payload_on = {item["run_id"]: item for item in response_on.json()["runs"]}[str(run.run_id)]
        self.assertIn("debug_pipeline", payload_on)
        self.assertEqual(payload_on["debug_pipeline"]["current_stage"], "matching")
