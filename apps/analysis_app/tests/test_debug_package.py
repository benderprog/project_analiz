from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from apps.analysis_app.debug_package import prune_debug_packages_for_owner
from apps.analysis_app.models import AnalysisRun


class DebugPackagePruneTests(TestCase):
    def test_prune_keeps_only_last_ten_for_user(self):
        user = get_user_model().objects.create_user(
            username="prune-owner",
            email="prune-owner@example.com",
            password="pass",
        )
        base_time = timezone.now()
        runs = []

        for idx in range(12):
            run = AnalysisRun.objects.create(
                uploaded_by=user,
                file=ContentFile(b"doc", name=f"input_{idx}.docx"),
                original_filename=f"input_{idx}.docx",
                status=AnalysisRun.Status.DONE,
                finished_at=base_time - timedelta(minutes=idx),
            )
            run.debug_package_file.save(
                f"debug_{run.run_id}.zip",
                ContentFile(f"payload-{idx}".encode("utf-8")),
                save=False,
            )
            run.debug_package_created_at = timezone.now()
            run.save(update_fields=["debug_package_file", "debug_package_created_at"])
            runs.append(run)

        prune_debug_packages_for_owner(runs[0], keep=10)

        with_package = AnalysisRun.objects.exclude(debug_package_file="").filter(
            debug_package_file__isnull=False,
            uploaded_by=user,
        )
        self.assertEqual(with_package.count(), 10)

        stale_runs = AnalysisRun.objects.filter(uploaded_by=user).order_by("-finished_at", "-created_at")[10:]
        for stale_run in stale_runs:
            self.assertFalse(stale_run.debug_package_file)
            self.assertIsNone(stale_run.debug_package_created_at)
