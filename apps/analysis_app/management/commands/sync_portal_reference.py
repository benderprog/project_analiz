from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.analysis_app.models import CachedPU, CachedSubdivision, CachedSubdivisionAlias
from apps.analysis_app.pu_cache import upsert_pu_cache
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache
from apps.analysis_app.subdivision_utils import (
    build_embedding_source_hash,
    build_subdivision_aliases,
    to_py_floats,
)
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text
from apps.analysis_app.utils.subdivision_norm import normalize_text
from apps.portaldb.models import Pu, Subdivision

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync PU/subdivision reference data from portal_db into the app cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rebuild-embeddings",
            action="store_true",
            help="Recompute embeddings for cached PUs and subdivisions.",
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
            cached_pus = {
                portal_pu.pu_id: upsert_pu_cache(
                    portal_pu, rebuild_embeddings=rebuild_embeddings
                )
                for portal_pu in portal_pus
            }

            portal_subdivisions = list(
                Subdivision.objects.using("portal").select_related("parent_pu")
            )
            for portal_subdivision in portal_subdivisions:
                short_name = (portal_subdivision.short_name or "").strip()
                full_name = portal_subdivision.name.strip()
                embedding_text = short_name or full_name
                normalized_short_name = normalize_subdivision_text(short_name)
                normalized_name = normalize_subdivision_text(full_name)
                normalized_embedding_source = normalize_subdivision_text(embedding_text)
                alias_texts = build_subdivision_aliases(portal_subdivision.name)
                source_hash = build_embedding_source_hash(
                    normalized_embedding_source, alias_texts
                )
                cached_subdivision, created = CachedSubdivision.objects.get_or_create(
                    portal_subdivision_id=portal_subdivision.subdivision_id,
                    defaults={
                        "name": portal_subdivision.name,
                        "pu": cached_pus.get(portal_subdivision.parent_pu_id),
                        "parent_pu_id": portal_subdivision.parent_pu_id,
                        "normalized_short_name": normalized_short_name,
                        "normalized_name": normalized_name,
                        "legacy_aliases": alias_texts,
                        "embedding_source_hash": source_hash,
                    },
                )
                if not created:
                    cached_subdivision.name = portal_subdivision.name
                    cached_subdivision.pu = cached_pus.get(portal_subdivision.parent_pu_id)
                    cached_subdivision.parent_pu_id = portal_subdivision.parent_pu_id
                    cached_subdivision.normalized_short_name = normalized_short_name
                    cached_subdivision.normalized_name = normalized_name
                    cached_subdivision.legacy_aliases = alias_texts
                cached_subdivision.embedding_source_text = embedding_text

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
                        embedding = model.encode([normalized_embedding_source])[0]
                        cached_subdivision.embedding = to_py_floats(embedding)
                        cached_subdivision.embedding_updated_at = timezone.now()
                    elif rebuild_embeddings or cached_subdivision.embedding is None:
                        cached_subdivision.embedding = None
                        cached_subdivision.embedding_updated_at = None
                cached_subdivision._skip_embedding_rebuild = True

                cached_subdivision.save()

                alias_map: dict[str, str] = {}
                for alias_text in alias_texts:
                    normalized_alias = normalize_text(alias_text)
                    if not normalized_alias:
                        continue
                    alias_map.setdefault(normalized_alias, alias_text)

                alias_embeddings: dict[str, list[float] | None] = {}
                if model and not settings.SKIP_SEMANTIC_MODEL:
                    embeddings = model.encode(list(alias_map.values()))
                    for idx, normalized_alias in enumerate(alias_map.keys()):
                        alias_embeddings[normalized_alias] = to_py_floats(embeddings[idx])

                existing_aliases = {
                    alias.normalized_alias: alias
                    for alias in CachedSubdivisionAlias.objects.filter(
                        subdivision=cached_subdivision
                    )
                }
                for normalized_alias, alias_text in alias_map.items():
                    alias_obj = existing_aliases.get(normalized_alias)
                    defaults = {
                        "alias_text": alias_text,
                        "normalized_alias": normalized_alias,
                    }
                    if model and not settings.SKIP_SEMANTIC_MODEL:
                        defaults["embedding"] = alias_embeddings.get(normalized_alias)
                    elif alias_obj is None or rebuild_embeddings:
                        defaults["embedding"] = None

                    CachedSubdivisionAlias.objects.update_or_create(
                        subdivision=cached_subdivision,
                        normalized_alias=normalized_alias,
                        defaults=defaults,
                    )

                CachedSubdivisionAlias.objects.filter(
                    subdivision=cached_subdivision
                ).exclude(normalized_alias__in=alias_map.keys()).delete()

        invalidate_subdivision_cache()
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {len(portal_pus)} PUs and {len(portal_subdivisions)} subdivisions."
            )
        )
