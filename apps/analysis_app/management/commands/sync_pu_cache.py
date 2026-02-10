from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.analysis_app.pu_cache import sync_pu_cache


class Command(BaseCommand):
    help = "Sync PU cache data from portal_db into the app cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rebuild-embeddings",
            action="store_true",
            help="Recompute embeddings for cached PUs.",
        )

    def handle(self, *args, **options):
        rebuild_embeddings = options["rebuild_embeddings"]
        count = sync_pu_cache(rebuild_embeddings=rebuild_embeddings)
        self.stdout.write(self.style.SUCCESS(f"Synced {count} PUs."))
