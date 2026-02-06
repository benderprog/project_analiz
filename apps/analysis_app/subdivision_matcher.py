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
from apps.analysis_app.utils.subdivision_norm import extract_locality, normalize_text, unit_type_group

logger = logging.getLogger(__name__)

SUBDIVISION_MATCH_THRESHOLD = 0.75
SUBDIVISION_GREEN_THRESHOLD = 0.85
SUBDIVISION_YELLOW_THRESHOLD = 0.75

_CODE_REGEX = re.compile(r"\b(опк|оп|пз|погз|пого|погк)\s*[-№]?\s*(\d+)\b", re.IGNORECASE)
_OP_NAME_REGEX = re.compile(r"\bоп\s*-\s*[а-яё]+\b", re.IGNORECASE)
_CONTEXT_REGEX = re.compile(
    r"(?:на посту|посту|службой|служба|в районе ответственности|в р-не ответственности|в районе|в р-не)\s+"
    r"(?P<unit>[^;.,]+)",
    re.IGNORECASE,
)

_cache_version = 0


@dataclass(frozen=True)
class SubdivisionCandidate:
    portal_subdivision_id: str
    name: str
    score: float
    score_percent: float
    flags: dict
    query_span: tuple[int, int] | None
    query_locality: dict
    candidate_locality: dict
    locality_mismatch: bool


@dataclass(frozen=True)
class SubdivisionQuery:
    text: str
    normalized: str
    span: tuple[int, int] | None
    locality_type: str | None
    locality_name: str | None
    unit_code: str | None
    unit_number: str | None
    unit_type: str


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
        locality_type, locality_name = extract_locality(fragment)
        code_match = _CODE_REGEX.search(normalized)
        unit_code = code_match.group(1) if code_match else None
        unit_number = code_match.group(2) if code_match else None
        unit_type = unit_type_group(normalized)
        queries.append(
            SubdivisionQuery(
                text=fragment.strip(),
                normalized=normalized,
                span=span,
                locality_type=locality_type,
                locality_name=locality_name,
                unit_code=unit_code,
                unit_number=unit_number,
                unit_type=unit_type,
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


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    return set(re.findall(r"[\w№]+", text.lower()))


def _containment_score(
    query_norm: str,
    alias_norm: str,
    query_unit_type: str,
    alias_unit_type: str,
) -> tuple[float, bool]:
    if not query_norm or not alias_norm:
        return 0.0, False
    containment_score = 0.0
    if query_norm in alias_norm or alias_norm in query_norm:
        coverage = min(len(query_norm), len(alias_norm)) / max(len(query_norm), len(alias_norm))
        containment_score = 0.90 + 0.10 * coverage
    query_tokens = _tokenize(query_norm)
    alias_tokens = _tokenize(alias_norm)
    if (
        query_tokens
        and query_tokens.issubset(alias_tokens)
        and query_unit_type != "UNKNOWN"
        and query_unit_type == alias_unit_type
    ):
        containment_score = max(containment_score, 0.95)
    return containment_score, containment_score > 0.0


def _fallback_query(text: str) -> SubdivisionQuery:
    match = _CODE_REGEX.search(text)
    if match:
        start = max(match.start() - 40, 0)
        end = min(match.end() + 40, len(text))
        fragment = text[start:end]
        normalized = normalize_text(fragment)
        locality_type, locality_name = extract_locality(fragment)
        unit_type = unit_type_group(normalized)
        return SubdivisionQuery(
            text=fragment,
            normalized=normalized,
            span=(start, end),
            locality_type=locality_type,
            locality_name=locality_name,
            unit_code=match.group(1),
            unit_number=match.group(2),
            unit_type=unit_type,
        )
    normalized = normalize_text(text)
    locality_type, locality_name = extract_locality(text)
    return SubdivisionQuery(
        text=text,
        normalized=normalized,
        span=None,
        locality_type=locality_type,
        locality_name=locality_name,
        unit_code=None,
        unit_number=None,
        unit_type=unit_type_group(normalized),
    )


def _score_alias(
    query: SubdivisionQuery,
    alias: dict,
    query_embedding: list[float] | None,
    candidate_unit_type: str,
) -> tuple[float, dict]:
    alias_norm = normalize_subdivision_name(alias.get("normalized_alias") or alias.get("alias_text") or "")
    query_norm = query.normalized
    string_score = _sequence_similarity(query_norm, alias_norm) if alias_norm else 0.0

    semantic_score = 0.0
    if query_embedding is not None:
        embedding = alias.get("embedding")
        if embedding:
            semantic_score = _cosine_similarity(query_embedding, to_py_floats(embedding))

    alias_unit_type = unit_type_group(alias_norm)
    if alias_unit_type == "UNKNOWN":
        alias_unit_type = candidate_unit_type
    query_unit_type = query.unit_type
    unit_type_match = (
        query_unit_type != "UNKNOWN"
        and alias_unit_type != "UNKNOWN"
        and query_unit_type == alias_unit_type
    )
    unit_type_conflict = (
        query_unit_type != "UNKNOWN"
        and alias_unit_type != "UNKNOWN"
        and query_unit_type != alias_unit_type
    )

    containment_score, containment_hit = _containment_score(
        query_norm,
        alias_norm,
        query_unit_type,
        alias_unit_type,
    )

    base_score = max(string_score, semantic_score, containment_score)
    base_score = max(0.0, min(1.0, base_score))

    flags = {
        "unit_type_match": unit_type_match if query_unit_type != "UNKNOWN" else None,
        "unit_type_conflict": unit_type_conflict if query_unit_type != "UNKNOWN" else None,
        "containment_hit": containment_hit,
        "alias_unit_type": alias_unit_type,
    }
    return base_score, flags


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

    queries_with_locality = [query for query in queries if query.locality_name]
    primary_queries = queries_with_locality or queries

    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable, falling back to sequence match: %s", exc)
        model = None

    query_embeddings: list[list[float] | None] = [None] * len(primary_queries)
    if model:
        embeddings = model.encode([query.normalized for query in primary_queries])
        query_embeddings = [to_py_floats(item) for item in embeddings]

    strict_query = next(
        (query for query in primary_queries if query.unit_code and query.unit_number),
        None,
    )

    def _collect_results(strict_only: bool) -> list[SubdivisionCandidate]:
        collected: list[SubdivisionCandidate] = []
        for subdivision in cached:
            aliases = subdivision.get("aliases") or []
            best_score = 0.0
            best_flags: dict = {}
            best_span: tuple[int, int] | None = None
            best_query_locality: dict | None = None
            best_query_unit_type = "UNKNOWN"
            candidate_locality_type, candidate_locality_name = extract_locality(subdivision.get("name") or "")
            candidate_has_locality_match = False
            candidate_has_locality_present = bool(candidate_locality_name)
            candidate_has_locality_conflict = False
            candidate_unit_type = unit_type_group(
                normalize_subdivision_name(subdivision.get("normalized_name") or subdivision.get("name") or "")
            )

            for idx, query in enumerate(primary_queries):
                if strict_only and strict_query and query != strict_query:
                    continue
                for alias in aliases:
                    alias_text = alias.get("alias_text") or ""
                    alias_norm = normalize_subdivision_name(
                        alias.get("normalized_alias") or alias_text or ""
                    )
                    alias_locality_type, alias_locality_name = extract_locality(alias_text)
                    if strict_only and strict_query:
                        code_token = f"{strict_query.unit_code} №{strict_query.unit_number}"
                        if code_token not in alias_norm:
                            continue
                    if alias_locality_name:
                        candidate_has_locality_present = True
                    locality_match = bool(
                        query.locality_name
                        and (
                            query.locality_name in alias_norm
                            or (
                                candidate_locality_name
                                and candidate_locality_name == query.locality_name
                            )
                            or (alias_locality_name and alias_locality_name == query.locality_name)
                        )
                    )
                    locality_conflict = bool(
                        query.locality_name
                        and (
                            (candidate_locality_name and candidate_locality_name != query.locality_name)
                            or (alias_locality_name and alias_locality_name != query.locality_name)
                        )
                    )
                    if locality_match:
                        candidate_has_locality_match = True
                    if locality_conflict:
                        candidate_has_locality_conflict = True

                    score, flags = _score_alias(
                        query,
                        alias,
                        query_embeddings[idx],
                        candidate_unit_type,
                    )
                    adjusted_score = score
                    if locality_match:
                        adjusted_score += 0.10
                    if locality_conflict:
                        adjusted_score -= 0.25
                    if flags.get("unit_type_conflict"):
                        adjusted_score -= 0.15
                    adjusted_score = max(0.0, min(1.0, adjusted_score))
                    if flags.get("unit_type_conflict"):
                        adjusted_score = min(adjusted_score, 0.84)

                    if adjusted_score > best_score:
                        best_score = adjusted_score
                        best_flags = {
                            **flags,
                            "locality_match": locality_match,
                            "locality_conflict": locality_conflict,
                            "locality_present": candidate_has_locality_present,
                        }
                        best_span = query.span
                        best_query_locality = {
                            "type": query.locality_type,
                            "name": query.locality_name,
                        }
                        best_query_unit_type = query.unit_type

            if best_score <= 0.0:
                continue

            collected.append(
                SubdivisionCandidate(
                    portal_subdivision_id=str(subdivision["portal_subdivision_id"]),
                    name=subdivision["name"],
                    score=best_score,
                    score_percent=round(best_score * 100, 2),
                    flags={
                        **best_flags,
                        "locality_match": candidate_has_locality_match,
                        "locality_conflict": candidate_has_locality_conflict,
                        "locality_present": candidate_has_locality_present,
                        "query_unit_type": best_query_unit_type,
                        "candidate_unit_type": candidate_unit_type,
                    },
                    query_span=best_span,
                    query_locality=best_query_locality
                    or {"type": None, "name": None},
                    candidate_locality={
                        "type": candidate_locality_type,
                        "name": candidate_locality_name,
                    },
                    locality_mismatch=False,
                )
            )
        return collected

    results = _collect_results(strict_only=bool(strict_query))
    if strict_query and not results:
        results = _collect_results(strict_only=False)
    if not results and primary_queries != queries:
        primary_queries = queries
        query_embeddings = [None] * len(primary_queries)
        if model:
            embeddings = model.encode([query.normalized for query in primary_queries])
            query_embeddings = [to_py_floats(item) for item in embeddings]
        strict_query = next(
            (query for query in primary_queries if query.unit_code and query.unit_number),
            None,
        )
        results = _collect_results(strict_only=bool(strict_query))

    if not results:
        return []

    preferred_locality = None
    if strict_query and strict_query.locality_name:
        preferred_locality = strict_query.locality_name
    else:
        preferred_locality = next(
            (query.locality_name for query in primary_queries if query.locality_name),
            None,
        )

    if preferred_locality:
        locality_matches = [item for item in results if item.flags.get("locality_match")]
        if locality_matches:
            results = locality_matches
        else:
            locality_present = [item for item in results if item.flags.get("locality_present")]
            if locality_present:
                results = locality_present

    preferred_unit_type = None
    if strict_query and strict_query.unit_type != "UNKNOWN":
        preferred_unit_type = strict_query.unit_type
    else:
        preferred_unit_type = next(
            (query.unit_type for query in primary_queries if query.unit_type != "UNKNOWN"),
            None,
        )

    if preferred_unit_type:
        unit_matches = [
            item
            for item in results
            if item.flags.get("unit_type_match") or item.flags.get("candidate_unit_type") == preferred_unit_type
        ]
        if unit_matches:
            results = unit_matches

    results = [
        SubdivisionCandidate(
            portal_subdivision_id=item.portal_subdivision_id,
            name=item.name,
            score=item.score,
            score_percent=item.score_percent,
            flags=item.flags,
            query_span=item.query_span,
            query_locality=item.query_locality,
            candidate_locality=item.candidate_locality,
            locality_mismatch=bool(item.flags.get("locality_conflict")),
        )
        for item in results
    ]
    results.sort(key=lambda item: item.score, reverse=True)
    return [
        {
            "portal_subdivision_id": candidate.portal_subdivision_id,
            "name": candidate.name,
            "score": to_py_float(candidate.score),
            "score_percent": to_py_float(candidate.score_percent),
            "flags": candidate.flags,
            "query_span": candidate.query_span,
            "query_locality": candidate.query_locality,
            "candidate_locality": candidate.candidate_locality,
            "locality_mismatch": candidate.locality_mismatch,
        }
        for candidate in results[:top_k]
    ]
