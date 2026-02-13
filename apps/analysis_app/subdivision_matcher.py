from __future__ import annotations

import logging
import math
import uuid
from functools import lru_cache

from django.conf import settings
from django.db import models

from apps.analysis_app.models import CachedSubdivision
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import to_py_float, to_py_floats
from apps.analysis_app.utils.text_normalize import (
    normalize_subdivision_text,
    normalize_subdivision_text_with_mapping,
)

logger = logging.getLogger(__name__)

SUBDIVISION_MATCH_THRESHOLD = 0.75
SUBDIVISION_GREEN_THRESHOLD = 0.85
SUBDIVISION_YELLOW_THRESHOLD = 0.75

_MAX_WINDOW_COUNT = 80
_WINDOW_SIZES = (1, 2, 3, 4, 5, 6)
_SUBDIVISION_STOP_TOKENS = {
    "опк",
    "погз",
    "погк",
    "кпп",
    "отделение",
    "участок",
    "пн",
    "пограничный",
    "пункт",
}

_cache_version = 0


def _token_set(value: str) -> set[str]:
    return {token for token in value.split() if token}


def _extract_key_tokens(value: str) -> set[str]:
    return {
        token
        for token in _token_set(value)
        if len(token) > 4 and token not in _SUBDIVISION_STOP_TOKENS
    }


def _lexical_evidence(
    normalized_text: str, normalized_short_name: str, normalized_name: str
) -> tuple[bool, int]:
    evidence_source = normalized_short_name or normalized_name
    key_tokens = _extract_key_tokens(evidence_source)
    text_tokens = _token_set(normalized_text)

    substring_hit = any(token in normalized_text for token in key_tokens)
    token_overlap = len(key_tokens & text_tokens)
    return substring_hit, token_overlap


def _lexical_factor(substring_hit: bool, token_overlap: int) -> float:
    if substring_hit or token_overlap > 0:
        return 1.0
    return float(getattr(settings, "SUBDIVISION_LOW_LEXICAL_FACTOR", 0.1))


def _lexical_strength(
    normalized_text: str,
    subdivision: dict,
) -> tuple[str, int, str | None]:
    short_name = subdivision.get("normalized_short_name") or ""
    name = subdivision.get("normalized_name") or ""
    text_tokens = _token_set(normalized_text)

    evidence_tokens = [token for token in short_name.split() if len(token) >= 4]
    evidence_tokens.extend(token for token in name.split() if len(token) >= 6)

    for token in evidence_tokens:
        if token and token in normalized_text:
            return "strong", 2, token

    substring_source = short_name or name
    if substring_source and substring_source in normalized_text:
        return "strong", 2, substring_source

    overlap = len(text_tokens & (_token_set(short_name) | _token_set(name)))
    if overlap > 0:
        return "medium", 1, None
    return "none", 0, None


def _build_subdivision_candidate_queryset(
    selected_pu_portal_id: uuid.UUID | None,
) -> tuple[models.QuerySet, dict]:
    qs = CachedSubdivision.objects.all()
    total = qs.count()
    filtered_count = total
    fallback_used = False
    if selected_pu_portal_id is not None:
        filtered = qs.filter(parent_pu_id=selected_pu_portal_id)
        filtered_count = filtered.count()
        if filtered_count:
            qs = filtered
        else:
            fallback_used = True
            logger.debug(
                "PU filter %s returned no subdivisions; falling back to all.",
                selected_pu_portal_id,
            )
    meta = {
        "subdivision_candidates_total": total,
        "subdivision_candidates_after_pu_filter": filtered_count,
        "pu_filter_fallback_used": fallback_used,
        "selected_pu_id": str(selected_pu_portal_id) if selected_pu_portal_id else None,
    }
    return qs, meta


def get_subdivision_candidates(
    selected_pu_portal_id: uuid.UUID | None,
) -> models.QuerySet:
    qs, _ = _build_subdivision_candidate_queryset(selected_pu_portal_id)
    return qs


def invalidate_subdivision_cache() -> None:
    global _cache_version
    _cache_version += 1
    _load_cached_subdivisions.cache_clear()


@lru_cache(maxsize=8)
def _load_cached_subdivisions(
    version: int, selected_pu_id: uuid.UUID | None
) -> tuple[list[dict], dict]:
    queryset, meta = _build_subdivision_candidate_queryset(selected_pu_id)
    queryset = queryset.values(
        "id",
        "portal_subdivision_id",
        "name",
        "normalized_short_name",
        "normalized_name",
        "embedding",
        "pu_id",
        "parent_pu_id",
    )
    return list(queryset), meta


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if not norm_a or not norm_b:
        return 0.0
    return to_py_float(dot / (norm_a * norm_b))


def _map_normalized_span(
    span: tuple[int, int], mapping: list[int]
) -> tuple[int, int] | None:
    if not mapping:
        return None
    start, end = span
    if start < 0 or end <= start:
        return None
    if end - 1 >= len(mapping):
        return None
    return mapping[start], mapping[end - 1] + 1


def _tokenize_with_positions(text: str) -> list[tuple[str, int, int]]:
    tokens: list[tuple[str, int, int]] = []
    buffer: list[str] = []
    start = None

    def flush(end_index: int) -> None:
        nonlocal buffer, start
        if buffer and start is not None:
            token = "".join(buffer)
            if any(ch.isalnum() or ch == "\u2116" for ch in token):
                tokens.append((token, start, end_index))
        buffer = []
        start = None

    for index, ch in enumerate(text):
        if ch.isalnum() or ch in {"-", "\u2116", '"'}:
            if start is None:
                start = index
            buffer.append(ch)
        else:
            flush(index)
    flush(len(text))
    return tokens


def _build_windows(tokens: list[tuple[str, int, int]]) -> list[dict]:
    windows: list[dict] = []
    token_texts = [token[0] for token in tokens]
    for start in range(len(tokens)):
        for size in _WINDOW_SIZES:
            end = start + size
            if end > len(tokens):
                continue
            window_text = " ".join(token_texts[start:end])
            window = {
                "text": window_text,
                "span": (tokens[start][1], tokens[end - 1][2]),
            }
            windows.append(window)
            if len(windows) >= _MAX_WINDOW_COUNT:
                return windows
    return windows


def _substring_matches(
    normalized_text: str, mapping: list[int], selected_pu_id: uuid.UUID | None
) -> list[dict]:
    cached, _ = _load_cached_subdivisions(_cache_version, selected_pu_id)
    matches: list[dict] = []
    for subdivision in cached:
        lexical_strength, lexical_score, lexical_token = _lexical_strength(
            normalized_text,
            subdivision,
        )
        if lexical_strength == "none":
            continue
        candidates = [
            ("short_name", subdivision.get("normalized_short_name") or ""),
            ("name", subdivision.get("normalized_name") or ""),
        ]
        for token_type, token in candidates:
            if not token:
                continue
            pos = normalized_text.find(token)
            if pos == -1:
                continue
            span = (pos, pos + len(token))
            matches.append(
                {
                    "portal_subdivision_id": str(subdivision["portal_subdivision_id"]),
                    "name": subdivision["name"],
                    "score": 1.0,
                    "score_percent": 100.0,
                    "match_method": "substring",
                    "match_token": token_type,
                    "query_span": _map_normalized_span(span, mapping),
                    "normalized_span": span,
                    "flags": {},
                    "query_locality": None,
                    "candidate_locality": None,
                    "locality_mismatch": False,
                    "match_text": token,
                    "lexical_strength": lexical_strength,
                    "lexical_score": lexical_score,
                    "token_overlap": lexical_score,
                    "substring_evidence": lexical_strength == "strong",
                    "lexical_token": lexical_token,
                }
            )
            break

    matches.sort(
        key=lambda item: (
            -(item["normalized_span"][1] - item["normalized_span"][0]),
            item["normalized_span"][0],
            item["portal_subdivision_id"],
        )
    )
    return matches


def _semantic_window_matches(
    normalized_text: str,
    mapping: list[int],
    selected_pu_id: uuid.UUID | None,
) -> list[dict]:
    cached, _ = _load_cached_subdivisions(_cache_version, selected_pu_id)
    if not cached:
        return []

    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable, skipping semantic match: %s", exc)
        return []

    if not model:
        return []

    tokens = _tokenize_with_positions(normalized_text)
    if not tokens:
        return []

    windows = _build_windows(tokens)
    if not windows:
        return []

    cached_embeddings = []
    for subdivision in cached:
        embedding = subdivision.get("embedding")
        if embedding:
            cached_embeddings.append(
                {
                    "subdivision": subdivision,
                    "embedding": to_py_floats(embedding),
                }
            )

    if not cached_embeddings:
        return []

    window_texts = [window["text"] for window in windows]
    embeddings = model.encode(window_texts)

    best_by_subdivision: dict[str, dict] = {}
    for window, window_embedding in zip(windows, embeddings):
        window_vec = to_py_floats(window_embedding)
        for candidate in cached_embeddings:
            semantic_score = _cosine_similarity(window_vec, candidate["embedding"])
            portal_id = str(candidate["subdivision"]["portal_subdivision_id"])
            short_name = candidate["subdivision"].get("normalized_short_name") or ""
            full_name = candidate["subdivision"].get("normalized_name") or ""
            substring_hit, token_overlap = _lexical_evidence(
                normalized_text, short_name, full_name
            )
            lexical_factor = _lexical_factor(substring_hit, token_overlap)
            confidence = semantic_score * lexical_factor
            current = best_by_subdivision.get(portal_id)
            if current is None or confidence > current["score"]:
                best_by_subdivision[portal_id] = {
                    "portal_subdivision_id": portal_id,
                    "name": candidate["subdivision"]["name"],
                    "score": confidence,
                    "score_percent": round(confidence * 100, 2),
                    "semantic_score": semantic_score,
                    "lexical_factor": lexical_factor,
                    "match_method": "semantic_window",
                    "query_span": _map_normalized_span(window["span"], mapping),
                    "normalized_span": window["span"],
                    "flags": {},
                    "query_locality": None,
                    "candidate_locality": None,
                    "locality_mismatch": False,
                    "match_text": window["text"],
                    "lexical_strength": "medium" if token_overlap else "none",
                    "lexical_score": token_overlap,
                    "token_overlap": token_overlap,
                    "substring_evidence": substring_hit,
                    "lexical_token": None,
                }

    threshold = getattr(settings, "SUBDIVISION_SEMANTIC_THRESHOLD", 0.6)
    results = [
        item for item in best_by_subdivision.values() if item["score"] >= threshold
    ]
    results.sort(key=lambda item: (-item["score"], item["portal_subdivision_id"]))
    return results


def match_subdivision(
    text: str, top_k: int = 5, selected_pu_id: uuid.UUID | None = None
) -> tuple[list[dict], dict]:
    cached, meta = _load_cached_subdivisions(_cache_version, selected_pu_id)
    if not text:
        return [], meta

    normalized_text, mapping = normalize_subdivision_text_with_mapping(text)
    if not normalized_text:
        return [], meta

    matches = _substring_matches(normalized_text, mapping, selected_pu_id)
    if matches:
        strong = [item for item in matches if item.get("lexical_strength") == "strong"]
        if strong:
            return strong[:top_k], meta
        return matches[:top_k], meta

    semantic_matches = _semantic_window_matches(normalized_text, mapping, selected_pu_id)
    return semantic_matches[:top_k], meta


__all__ = [
    "SUBDIVISION_MATCH_THRESHOLD",
    "SUBDIVISION_GREEN_THRESHOLD",
    "SUBDIVISION_YELLOW_THRESHOLD",
    "get_subdivision_candidates",
    "invalidate_subdivision_cache",
    "match_subdivision",
]
