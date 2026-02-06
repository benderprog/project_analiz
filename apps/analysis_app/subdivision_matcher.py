from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

from django.conf import settings

from apps.analysis_app.models import CachedSubdivision, CachedSubdivisionAlias
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import normalize_subdivision_name, to_py_float, to_py_floats
from apps.analysis_app.utils.subdivision_norm import extract_locality, normalize_text

logger = logging.getLogger(__name__)

SUBDIVISION_MATCH_THRESHOLD = 0.75
SUBDIVISION_GREEN_THRESHOLD = 0.85
SUBDIVISION_YELLOW_THRESHOLD = 0.75

_CODE_REGEX = re.compile(r"\b(опк|оп|пз|погз|пого)\s*[-№]?\s*(\d+)\b", re.IGNORECASE)
_OP_NAME_REGEX = re.compile(r"\bоп\s*-\s*[а-яё]+\b", re.IGNORECASE)
_CONTEXT_REGEX = re.compile(
    r"(?:на посту|посту|службой|служба|в районе ответственности|в р-не ответственности)\s+"
    r"(?P<unit>[^;.,]+)",
    re.IGNORECASE,
)

_UNIT_GROUPS = {
    "op": {"оп", "опк", "отделение пограничного контроля", "отделение погранконтроля"},
    "pz": {"пз", "погз", "погранзастава", "пограничная застава"},
    "pogo": {"пого", "погранотделение", "пограничное отделение"},
}

_cache_version = 0


@dataclass(frozen=True)
class SubdivisionCandidate:
    portal_subdivision_id: str
    name: str
    score: float
    score_percent: float
    flags: dict
    query_span: tuple[int, int] | None


@dataclass(frozen=True)
class SubdivisionQuery:
    text: str
    normalized: str
    span: tuple[int, int] | None
    locality: str
    unit_code: str | None
    unit_number: str | None


def invalidate_subdivision_cache() -> None:
    global _cache_version
    _cache_version += 1
    _load_cached_subdivisions.cache_clear()


@lru_cache(maxsize=2)
def _load_cached_subdivisions(version: int):
    subdivisions = list(
        CachedSubdivision.objects.values(
            "id",
            "portal_subdivision_id",
            "name",
            "normalized_name",
            "embedding",
        )
    )
    alias_rows = list(
        CachedSubdivisionAlias.objects.values(
            "subdivision_id",
            "alias_text",
            "normalized_alias",
            "embedding",
        )
    )
    alias_map: dict[str, list[dict]] = {}
    for row in alias_rows:
        alias_map.setdefault(str(row["subdivision_id"]), []).append(row)

    results = []
    for subdivision in subdivisions:
        subdivision_id = str(subdivision["id"])
        alias_entries = alias_map.get(subdivision_id, [])
        if not alias_entries:
            alias_entries = [
                {
                    "alias_text": subdivision.get("name") or "",
                    "normalized_alias": subdivision.get("normalized_name") or "",
                    "embedding": subdivision.get("embedding"),
                }
            ]
        results.append(
            {
                "portal_subdivision_id": subdivision["portal_subdivision_id"],
                "name": subdivision["name"],
                "normalized_name": subdivision.get("normalized_name") or "",
                "aliases": alias_entries,
            }
        )
    return results


def extract_subdivision_queries(text: str) -> list[SubdivisionQuery]:
    if not text:
        return []

    queries: list[SubdivisionQuery] = []

    def _add_query(fragment: str, span: tuple[int, int] | None) -> None:
        normalized = normalize_text(fragment)
        if not normalized:
            return
        locality = extract_locality(fragment)
        code_match = _CODE_REGEX.search(normalized)
        unit_code = code_match.group(1) if code_match else None
        unit_number = code_match.group(2) if code_match else None
        queries.append(
            SubdivisionQuery(
                text=fragment.strip(),
                normalized=normalized,
                span=span,
                locality=locality,
                unit_code=unit_code,
                unit_number=unit_number,
            )
        )

    for match in _CONTEXT_REGEX.finditer(text):
        fragment = match.group("unit")
        _add_query(fragment, (match.start("unit"), match.end("unit")))

    for match in _CODE_REGEX.finditer(text):
        fragment = match.group(0)
        _add_query(fragment, (match.start(), match.end()))

    for match in _OP_NAME_REGEX.finditer(text):
        fragment = match.group(0)
        _add_query(fragment, (match.start(), match.end()))

    seen = set()
    unique_queries: list[SubdivisionQuery] = []
    for query in queries:
        key = query.normalized
        if key in seen:
            continue
        seen.add(key)
        unique_queries.append(query)

    return unique_queries


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if not norm_a or not norm_b:
        return 0.0
    return to_py_float(dot / (norm_a * norm_b))


def _sequence_similarity(query: str, candidate: str) -> float:
    return SequenceMatcher(None, query, candidate).ratio()


def _unit_group(text: str) -> str | None:
    for group, tokens in _UNIT_GROUPS.items():
        for token in tokens:
            if token in text:
                return group
    return None


def _fallback_query(text: str) -> SubdivisionQuery:
    match = _CODE_REGEX.search(text)
    if match:
        start = max(match.start() - 40, 0)
        end = min(match.end() + 40, len(text))
        fragment = text[start:end]
        normalized = normalize_text(fragment)
        return SubdivisionQuery(
            text=fragment,
            normalized=normalized,
            span=(start, end),
            locality=extract_locality(fragment),
            unit_code=match.group(1),
            unit_number=match.group(2),
        )
    normalized = normalize_text(text)
    return SubdivisionQuery(
        text=text,
        normalized=normalized,
        span=None,
        locality=extract_locality(text),
        unit_code=None,
        unit_number=None,
    )


def _score_alias(
    query: SubdivisionQuery,
    alias: dict,
    query_embedding: list[float] | None,
) -> tuple[float, dict]:
    alias_norm = normalize_subdivision_name(alias.get("normalized_alias") or alias.get("alias_text") or "")
    query_norm = query.normalized
    string_score = _sequence_similarity(query_norm, alias_norm) if alias_norm else 0.0

    semantic_score = 0.0
    if query_embedding is not None:
        embedding = alias.get("embedding")
        if embedding:
            semantic_score = _cosine_similarity(query_embedding, to_py_floats(embedding))

    unit_match_boost = 0.0
    unit_group_query = _unit_group(query_norm)
    unit_group_alias = _unit_group(alias_norm)
    if unit_group_query and unit_group_alias:
        if unit_group_query == unit_group_alias:
            unit_match_boost = 0.15
        else:
            unit_match_boost = -0.10

    locality_boost = 0.0
    if query.locality and query.locality in alias_norm:
        locality_boost = 0.10

    final_score = max(string_score, semantic_score) + unit_match_boost + locality_boost
    final_score = max(0.0, min(1.0, final_score))

    flags = {
        "matched_locality": bool(locality_boost),
        "unit_match": unit_group_query == unit_group_alias if unit_group_query and unit_group_alias else None,
        "unit_conflict": unit_group_query != unit_group_alias if unit_group_query and unit_group_alias else None,
    }
    return final_score, flags


def match_subdivision(text: str, top_k: int = 5) -> list[dict]:
    cached = _load_cached_subdivisions(_cache_version)
    if not cached:
        return []

    query_text = text.strip()
    if not query_text:
        return []

    queries = extract_subdivision_queries(query_text)
    if not queries:
        queries = [_fallback_query(query_text)]

    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable, falling back to sequence match: %s", exc)
        model = None

    query_embeddings: list[list[float] | None] = [None] * len(queries)
    if model:
        embeddings = model.encode([query.normalized for query in queries])
        query_embeddings = [to_py_floats(item) for item in embeddings]

    strict_query = next(
        (query for query in queries if query.unit_code and query.unit_number),
        None,
    )

    def _collect_results(strict_only: bool) -> list[SubdivisionCandidate]:
        collected: list[SubdivisionCandidate] = []
        for subdivision in cached:
            aliases = subdivision.get("aliases") or []
            best_score = 0.0
            best_flags: dict = {}
            best_span: tuple[int, int] | None = None

            for idx, query in enumerate(queries):
                if strict_only and strict_query and query != strict_query:
                    continue
                for alias in aliases:
                    alias_norm = normalize_subdivision_name(
                        alias.get("normalized_alias") or alias.get("alias_text") or ""
                    )
                    if strict_only and strict_query:
                        code_token = f"{strict_query.unit_code} №{strict_query.unit_number}"
                        if code_token not in alias_norm:
                            continue
                    score, flags = _score_alias(query, alias, query_embeddings[idx])
                    if score > best_score:
                        best_score = score
                        best_flags = flags
                        best_span = query.span

            if best_score <= 0.0:
                continue

            collected.append(
                SubdivisionCandidate(
                    portal_subdivision_id=str(subdivision["portal_subdivision_id"]),
                    name=subdivision["name"],
                    score=best_score,
                    score_percent=round(best_score * 100, 2),
                    flags=best_flags,
                    query_span=best_span,
                )
            )
        return collected

    results = _collect_results(strict_only=bool(strict_query))
    if strict_query and not results:
        results = _collect_results(strict_only=False)

    if not results:
        return []

    results.sort(key=lambda item: item.score, reverse=True)
    return [
        {
            "portal_subdivision_id": candidate.portal_subdivision_id,
            "name": candidate.name,
            "score": to_py_float(candidate.score),
            "score_percent": to_py_float(candidate.score_percent),
            "flags": candidate.flags,
            "query_span": candidate.query_span,
        }
        for candidate in results[:top_k]
    ]
