from __future__ import annotations

import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_sentence_model():
    """Load sentence transformer model from local path or model name."""
    if settings.SKIP_SEMANTIC_MODEL:
        # Avoid heavy model downloads during lightweight test runs (e.g., CI).
        raise RuntimeError(
            "Semantic model loading is disabled via SKIP_SEMANTIC_MODEL."
        )

    from sentence_transformers import SentenceTransformer

    if settings.SEMANTIC_MODEL_PATH:
        logger.info("Loading sentence model from %s", settings.SEMANTIC_MODEL_PATH)
        return SentenceTransformer(settings.SEMANTIC_MODEL_PATH)

    logger.info("Loading sentence model by name %s", settings.SEMANTIC_MODEL_NAME)
    return SentenceTransformer(settings.SEMANTIC_MODEL_NAME)
