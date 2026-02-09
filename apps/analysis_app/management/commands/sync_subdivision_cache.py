from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.analysis_app.subdivision_cache import sync_subdivision_cache
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache


class Command(BaseCommand):
    help = "Sync subdivision cache data from portal_db into the app cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rebuild-embeddings",
            action="store_true",
            help="Recompute embeddings for cached subdivisions.",
        )

    def handle(self, *args, **options):
        rebuild_embeddings = options["rebuild_embeddings"]
        count = sync_subdivision_cache(rebuild_embeddings=rebuild_embeddings)
        invalidate_subdivision_cache()
        self.stdout.write(self.style.SUCCESS(f"Synced {count} subdivisions."))
