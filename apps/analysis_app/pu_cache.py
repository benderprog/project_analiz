from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.analysis_app.models import CachedPU
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import to_py_floats
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text
from apps.portaldb.models import Pu

logger = logging.getLogger(__name__)


def _build_embedding_text(pu: Pu) -> str:
    short_name = (pu.short_name or "").strip()
    full_name = (pu.full_name or "").strip()
    if short_name and full_name:
        return f"{short_name} {full_name}".strip()
    return short_name or full_name


def upsert_pu_cache(portal_pu: Pu, rebuild_embeddings: bool = False) -> CachedPU:
    normalized_short = normalize_subdivision_text(portal_pu.short_name or "")
    normalized_full = normalize_subdivision_text(portal_pu.full_name or "")
    embedding_text = _build_embedding_text(portal_pu)
    normalized_embedding = normalize_subdivision_text(embedding_text)

    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable: %s", exc)
        model = None

    cached_pu, created = CachedPU.objects.get_or_create(
        portal_pu_id=portal_pu.pu_id,
        defaults={
            "short_name": portal_pu.short_name,
            "full_name": portal_pu.full_name,
            "normalized_short_name": normalized_short,
            "normalized_full_name": normalized_full,
        },
    )
    cached_pu.short_name = portal_pu.short_name
    cached_pu.full_name = portal_pu.full_name
    cached_pu.normalized_short_name = normalized_short
    cached_pu.normalized_full_name = normalized_full

    should_rebuild = (
        created
        or rebuild_embeddings
        or cached_pu.embedding is None
        or cached_pu.normalized_short_name != normalized_short
        or cached_pu.normalized_full_name != normalized_full
    )
    if should_rebuild:
        if model and normalized_embedding:
            embedding = model.encode([normalized_embedding])[0]
            cached_pu.embedding = to_py_floats(embedding)
            cached_pu.embedding_updated_at = timezone.now()
        else:
            cached_pu.embedding = None
            cached_pu.embedding_updated_at = None

    cached_pu.save()
    return cached_pu


def sync_pu_cache(rebuild_embeddings: bool = False) -> int:
    portal_pus = list(Pu.objects.using("portal").all())
    with transaction.atomic():
        for portal_pu in portal_pus:
            upsert_pu_cache(portal_pu, rebuild_embeddings=rebuild_embeddings)
    return len(portal_pus)


__all__ = ["sync_pu_cache", "upsert_pu_cache"]
