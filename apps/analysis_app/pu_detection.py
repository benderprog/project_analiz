from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from django.conf import settings

from apps.analysis_app.models import CachedPU
from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import to_py_float, to_py_floats
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PuDetectionResult:
    pu: CachedPU | None
    method: str
    score: float | None = None
    extracted_snippet: str | None = None


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if not norm_a or not norm_b:
        return 0.0
    return to_py_float(dot / (norm_a * norm_b))


def _extract_title_blob(document, paragraph_limit: int = 30, table_limit: int = 2) -> str:
    parts: list[str] = []
    for paragraph in document.paragraphs[:paragraph_limit]:
        text = paragraph.text.strip()
        if text:
            parts.append(text)

    for table in document.tables[:table_limit]:
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    parts.append(text)
    return "\n".join(parts)


def detect_pu_from_text(title_blob: str) -> PuDetectionResult:
    normalized_blob = normalize_subdivision_text(title_blob or "")
    if not normalized_blob:
        return PuDetectionResult(pu=None, method="none")

    cached_pus = list(CachedPU.objects.all())
    best_match: dict | None = None
    for pu in cached_pus:
        candidates = [
            (pu.normalized_short_name or "", "short"),
            (pu.normalized_full_name or "", "full"),
        ]
        for normalized_key, source in candidates:
            if not normalized_key:
                continue
            pos = normalized_blob.find(normalized_key)
            if pos == -1:
                continue
            length = len(normalized_key)
            match = {
                "pu": pu,
                "length": length,
                "pos": pos,
                "snippet": normalized_key,
                "source": source,
            }
            if best_match is None:
                best_match = match
                continue
            if length > best_match["length"]:
                best_match = match
                continue
            if length == best_match["length"] and pos < best_match["pos"]:
                best_match = match

    if best_match:
        return PuDetectionResult(
            pu=best_match["pu"],
            method="substring",
            score=1.0,
            extracted_snippet=best_match["snippet"],
        )

    try:
        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except RuntimeError as exc:
        logger.info("Semantic model unavailable, skipping PU semantic match: %s", exc)
        model = None

    if not model:
        return PuDetectionResult(pu=None, method="none")

    candidates = [
        {"pu": pu, "embedding": to_py_floats(pu.embedding)}
        for pu in cached_pus
        if pu.embedding
    ]
    if not candidates:
        return PuDetectionResult(pu=None, method="none")

    title_text = normalized_blob[:3000]
    title_embedding = to_py_floats(model.encode([title_text])[0])

    best_score = 0.0
    best_pu = None
    for candidate in candidates:
        score = _cosine_similarity(title_embedding, candidate["embedding"])
        if score > best_score:
            best_score = score
            best_pu = candidate["pu"]

    threshold = getattr(settings, "PU_SEMANTIC_THRESHOLD", 0.6)
    if best_pu and best_score >= threshold:
        return PuDetectionResult(pu=best_pu, method="semantic", score=best_score)

    return PuDetectionResult(pu=None, method="none")


def detect_pu_from_docx(document) -> PuDetectionResult:
    title_blob = _extract_title_blob(document)
    return detect_pu_from_text(title_blob)


__all__ = ["PuDetectionResult", "detect_pu_from_docx", "detect_pu_from_text"]
