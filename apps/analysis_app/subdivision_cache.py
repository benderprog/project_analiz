from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.analysis_app.models import CachedPU, CachedSubdivision
from apps.analysis_app.pu_cache import upsert_pu_cache
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import (
    build_embedding_source_hash,
    build_subdivision_aliases,
    to_py_floats,
)
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text
from apps.portaldb.models import Pu, Subdivision

logger = logging.getLogger(__name__)


def sync_subdivision_cache(rebuild_embeddings: bool = False) -> int:
    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable: %s", exc)
        model = None

    with transaction.atomic():
        portal_pus = list(Pu.objects.using("portal").all())
        cached_pus = _sync_cached_pus(portal_pus)

        portal_subdivisions = list(
            Subdivision.objects.using("portal").select_related("parent_pu")
        )
        for portal_subdivision in portal_subdivisions:
            _upsert_cached_subdivision(
                portal_subdivision,
                cached_pus.get(portal_subdivision.parent_pu_id),
                model=model,
                rebuild_embeddings=rebuild_embeddings,
            )

    return len(portal_subdivisions)


def upsert_subdivision_cache(portal_subdivision: Subdivision, rebuild_embeddings: bool = False) -> None:
    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable: %s", exc)
        model = None

    cached_pu = None
    parent_pu = getattr(portal_subdivision, "parent_pu", None)
    if parent_pu is None and portal_subdivision.parent_pu_id:
        parent_pu = Pu.objects.using("portal").get(pk=portal_subdivision.parent_pu_id)
    if parent_pu is not None:
        cached_pu = upsert_pu_cache(parent_pu)

    _upsert_cached_subdivision(
        portal_subdivision,
        cached_pu,
        model=model,
        rebuild_embeddings=rebuild_embeddings,
    )


def _sync_cached_pus(portal_pus: list[Pu]) -> dict:
    cached_pus: dict[str, CachedPU] = {}
    for portal_pu in portal_pus:
        cached_pu = upsert_pu_cache(portal_pu)
        cached_pus[portal_pu.pu_id] = cached_pu
    return cached_pus


def _upsert_cached_subdivision(
    portal_subdivision: Subdivision,
    cached_pu: CachedPU | None,
    *,
    model=None,
    rebuild_embeddings: bool = False,
) -> CachedSubdivision:
    short_name = (portal_subdivision.short_name or "").strip()
    full_name = portal_subdivision.name.strip()
    embedding_text = short_name or full_name
    normalized_short_name = normalize_subdivision_text(short_name)
    normalized_name = normalize_subdivision_text(full_name)
    normalized_embedding_source = normalize_subdivision_text(embedding_text)
    alias_texts = build_subdivision_aliases(portal_subdivision.name)
    source_hash = build_embedding_source_hash(normalized_embedding_source, alias_texts)

    cached_subdivision, created = CachedSubdivision.objects.get_or_create(
        portal_subdivision_id=portal_subdivision.subdivision_id,
        defaults={
            "name": portal_subdivision.name,
            "pu": cached_pu,
            "parent_pu_id": portal_subdivision.parent_pu_id,
            "normalized_short_name": normalized_short_name,
            "normalized_name": normalized_name,
            "legacy_aliases": alias_texts,
            "embedding_source_hash": source_hash,
        },
    )
    if not created:
        cached_subdivision.name = portal_subdivision.name
        cached_subdivision.pu = cached_pu
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
        else:
            cached_subdivision.embedding = None
            cached_subdivision.embedding_updated_at = None
        cached_subdivision._skip_embedding_rebuild = True

    cached_subdivision.save()
    return cached_subdivision


__all__ = ["sync_subdivision_cache", "upsert_subdivision_cache"]
