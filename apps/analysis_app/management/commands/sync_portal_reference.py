from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.analysis_app.models import CachedPU, CachedSubdivision
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache
from apps.analysis_app.subdivision_utils import (
    build_embedding_source_hash,
    build_subdivision_aliases,
    normalize_subdivision_name,
    to_py_floats,
)
from apps.portaldb.models import Pu, Subdivision

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync PU/subdivision reference data from portal_db into the app cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rebuild-embeddings",
            action="store_true",
            help="Recompute embeddings for cached subdivisions.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear cached reference data before syncing.",
        )

    def handle(self, *args, **options):
        rebuild_embeddings = options["rebuild_embeddings"]
        reset = options["reset"]

        try:
            model = get_sentence_model()
        except RuntimeError as exc:
            logger.info("Semantic model unavailable: %s", exc)
            model = None

        with transaction.atomic():
            if reset:
                CachedSubdivision.objects.all().delete()
                CachedPU.objects.all().delete()

            portal_pus = list(Pu.objects.using("portal").all())
            cached_pus = {}
            for portal_pu in portal_pus:
                cached_pu, _ = CachedPU.objects.update_or_create(
                    portal_pu_id=portal_pu.pu_id,
                    defaults={
                        "short_name": portal_pu.short_name,
                        "full_name": portal_pu.full_name,
                    },
                )
                cached_pus[portal_pu.pu_id] = cached_pu

            portal_subdivisions = list(
                Subdivision.objects.using("portal").select_related("parent_pu")
            )
            for portal_subdivision in portal_subdivisions:
                normalized_name = normalize_subdivision_name(portal_subdivision.name)
                aliases = build_subdivision_aliases(portal_subdivision.name)
                source_hash = build_embedding_source_hash(normalized_name, aliases)
                cached_subdivision, created = CachedSubdivision.objects.get_or_create(
                    portal_subdivision_id=portal_subdivision.subdivision_id,
                    defaults={
                        "name": portal_subdivision.name,
                        "pu": cached_pus.get(portal_subdivision.parent_pu_id),
                        "normalized_name": normalized_name,
                        "aliases": aliases,
                        "embedding_source_hash": source_hash,
                    },
                )
                if not created:
                    cached_subdivision.name = portal_subdivision.name
                    cached_subdivision.pu = cached_pus.get(portal_subdivision.parent_pu_id)
                    cached_subdivision.normalized_name = normalized_name
                    cached_subdivision.aliases = aliases

                hash_changed = cached_subdivision.embedding_source_hash != source_hash
                should_rebuild = (
                    rebuild_embeddings
                    or cached_subdivision.embedding is None
                    or hash_changed
                    or created
                )
                cached_subdivision.embedding_source_hash = source_hash

                if should_rebuild:
                    if model and not settings.SKIP_SEMANTIC_MODEL:
                        embedding = model.encode([normalized_name])[0]
                        cached_subdivision.embedding = to_py_floats(embedding)
                        cached_subdivision.embedding_updated_at = timezone.now()
                    else:
                        cached_subdivision.embedding = None
                        cached_subdivision.embedding_updated_at = None

                cached_subdivision.save()

        invalidate_subdivision_cache()
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {len(portal_pus)} PUs and {len(portal_subdivisions)} subdivisions."
            )
        )
