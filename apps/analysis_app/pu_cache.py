from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.db import transaction

from apps.analysis_app.models import CachedPU
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import to_py_floats
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text
from apps.analysis_app.portal_records import PortalPURecord
from apps.portaldb.gateway import get_portal_gateway

logger = logging.getLogger(__name__)


def _normalize_pu_text(pu_text: str) -> str:
    return normalize_subdivision_text((pu_text or "").strip())


def compute_pu_embeddings(pu: PortalPURecord, model=None) -> tuple[list[float] | None, list[float] | None]:
    short_source = (pu.short_name or "").strip() or (pu.full_name or "").strip()
    full_source = (pu.full_name or "").strip() or (pu.short_name or "").strip()
    short_text = _normalize_pu_text(short_source)
    full_text = _normalize_pu_text(full_source)

    if not model or settings.SKIP_SEMANTIC_MODEL:
        return (None, None)

    embeddings: list[list[float] | None] = [None, None]
    texts_to_encode = []
    text_map = []
    if short_text:
        texts_to_encode.append(short_text)
        text_map.append(0)
    if full_text:
        texts_to_encode.append(full_text)
        text_map.append(1)

    if texts_to_encode:
        encoded = model.encode(texts_to_encode)
        for idx, encoded_vec in enumerate(encoded):
            embeddings[text_map[idx]] = to_py_floats(encoded_vec)

    return embeddings[0], embeddings[1]


def compute_pu_embeddings_batch(
    portal_pus: list[PortalPURecord], model=None
) -> dict[uuid.UUID, tuple[list[float] | None, list[float] | None]]:
    if not model or settings.SKIP_SEMANTIC_MODEL:
        return {portal_pu.pu_id: (None, None) for portal_pu in portal_pus}

    short_texts: list[str] = []
    short_map: list[uuid.UUID] = []
    full_texts: list[str] = []
    full_map: list[uuid.UUID] = []
    for portal_pu in portal_pus:
        short_source = (portal_pu.short_name or "").strip() or (portal_pu.full_name or "").strip()
        full_source = (portal_pu.full_name or "").strip() or (portal_pu.short_name or "").strip()
        short_text = _normalize_pu_text(short_source)
        full_text = _normalize_pu_text(full_source)
        if short_text:
            short_map.append(portal_pu.pu_id)
            short_texts.append(short_text)
        if full_text:
            full_map.append(portal_pu.pu_id)
            full_texts.append(full_text)

    short_embeddings: dict[uuid.UUID, list[float]] = {}
    full_embeddings: dict[uuid.UUID, list[float]] = {}
    if short_texts:
        encoded = model.encode(short_texts)
        for idx, portal_pu_id in enumerate(short_map):
            short_embeddings[portal_pu_id] = to_py_floats(encoded[idx])
    if full_texts:
        encoded = model.encode(full_texts)
        for idx, portal_pu_id in enumerate(full_map):
            full_embeddings[portal_pu_id] = to_py_floats(encoded[idx])

    return {
        portal_pu.pu_id: (
            short_embeddings.get(portal_pu.pu_id),
            full_embeddings.get(portal_pu.pu_id),
        )
        for portal_pu in portal_pus
    }


def upsert_pu_cache(
    portal_pu: PortalPURecord,
    rebuild_embeddings: bool = False,
    *,
    embeddings: tuple[list[float] | None, list[float] | None] | None = None,
    model=None,
) -> CachedPU:
    normalized_short = normalize_subdivision_text(portal_pu.short_name or "")
    normalized_full = normalize_subdivision_text(portal_pu.full_name or "")

    if model is None:
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
        or cached_pu.embedding_short is None
        or cached_pu.embedding_full is None
        or cached_pu.normalized_short_name != normalized_short
        or cached_pu.normalized_full_name != normalized_full
    )
    if should_rebuild:
        if embeddings is None:
            embeddings = compute_pu_embeddings(portal_pu, model=model)
        cached_pu.embedding_short, cached_pu.embedding_full = embeddings

    cached_pu.save()
    return cached_pu


def sync_pu_cache(rebuild_embeddings: bool = False) -> int:
    gateway = get_portal_gateway()
    portal_pus = [
        PortalPURecord(pu_id=pu.pu_id, short_name=pu.short_name, full_name=pu.full_name)
        for pu in gateway.list_pus()
    ]
    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable: %s", exc)
        model = None

    embeddings_map: dict[uuid.UUID, tuple[list[float] | None, list[float] | None]] = {}
    if rebuild_embeddings or model:
        embeddings_map = compute_pu_embeddings_batch(portal_pus, model=model)
    with transaction.atomic():
        for portal_pu in portal_pus:
            upsert_pu_cache(
                portal_pu,
                rebuild_embeddings=rebuild_embeddings,
                embeddings=embeddings_map.get(portal_pu.pu_id),
                model=model,
            )
    return len(portal_pus)


__all__ = ["compute_pu_embeddings", "sync_pu_cache", "upsert_pu_cache"]
