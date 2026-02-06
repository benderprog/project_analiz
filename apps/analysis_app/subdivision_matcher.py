from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

from apps.analysis_app.models import CachedSubdivision
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import normalize_subdivision_name

logger = logging.getLogger(__name__)

SUBDIVISION_MATCH_THRESHOLD = 0.75
SUBDIVISION_GREEN_THRESHOLD = 0.85
SUBDIVISION_YELLOW_THRESHOLD = 0.75

_cache_version = 0


@dataclass(frozen=True)
class SubdivisionCandidate:
    portal_subdivision_id: str
    name: str
    score: float


def invalidate_subdivision_cache() -> None:
    global _cache_version
    _cache_version += 1
    _load_cached_subdivisions.cache_clear()


@lru_cache(maxsize=2)
def _load_cached_subdivisions(version: int):
    return list(
        CachedSubdivision.objects.values(
            "portal_subdivision_id",
            "name",
            "normalized_name",
            "aliases",
            "embedding",
        )
    )


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _fallback_similarity(query: str, subdivision: dict) -> float:
    normalized_query = normalize_subdivision_name(query)
    candidates = [subdivision.get("normalized_name") or ""]
    aliases = subdivision.get("aliases") or []
    candidates.extend(aliases)
    best = 0.0
    for candidate in candidates:
        if not candidate:
            continue
        normalized_candidate = normalize_subdivision_name(candidate)
        best = max(best, SequenceMatcher(None, normalized_query, normalized_candidate).ratio())
    return best


def match_subdivision(text: str, top_k: int = 5) -> list[dict]:
    cached = _load_cached_subdivisions(_cache_version)
    if not cached:
        return []

    query_text = text.strip().lower()
    if not query_text:
        return []

    try:
        model = get_sentence_model()
    except RuntimeError as exc:
        logger.info("Semantic model unavailable, falling back to sequence match: %s", exc)
        model = None

    results: list[SubdivisionCandidate] = []
    if model:
        query_embedding = model.encode([query_text])[0]
        for subdivision in cached:
            embedding = subdivision.get("embedding")
            if not embedding:
                continue
            score = _cosine_similarity(query_embedding, embedding)
            results.append(
                SubdivisionCandidate(
                    portal_subdivision_id=str(subdivision["portal_subdivision_id"]),
                    name=subdivision["name"],
                    score=score,
                )
            )

    if not results:
        for subdivision in cached:
            score = _fallback_similarity(query_text, subdivision)
            results.append(
                SubdivisionCandidate(
                    portal_subdivision_id=str(subdivision["portal_subdivision_id"]),
                    name=subdivision["name"],
                    score=score,
                )
            )

    results.sort(key=lambda item: item.score, reverse=True)
    return [
        {
            "portal_subdivision_id": candidate.portal_subdivision_id,
            "name": candidate.name,
            "score": candidate.score,
        }
        for candidate in results[:top_k]
    ]
