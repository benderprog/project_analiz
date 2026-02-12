from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from apps.analysis_app.semantic_model_resolver import (
    is_offline_mode,
    resolve_semantic_model_path,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_sentence_model():
    """Load sentence transformer model lazily with local-first resolution."""
    if settings.SKIP_SEMANTIC_MODEL:
        # Avoid heavy model downloads during lightweight test runs (e.g., CI).
        raise RuntimeError(
            "Semantic model loading is disabled via SKIP_SEMANTIC_MODEL."
        )

    resolved_model = resolve_semantic_model_path(
        settings.BASE_DIR,
        settings.SEMANTIC_MODEL_NAME,
        settings.SEMANTIC_MODEL_PATH,
    )

    if is_offline_mode() and not Path(resolved_model).exists():
        raise RuntimeError(
            "Offline mode enabled but local semantic model not found. "
            "Set SEMANTIC_MODEL_PATH or place the model in "
            "./models/<SEMANTIC_MODEL_NAME>."
        )

    from sentence_transformers import SentenceTransformer

    if Path(resolved_model).exists():
        logger.info("Loading sentence model from local path %s", resolved_model)
    else:
        logger.info("Loading sentence model by HuggingFace name %s", resolved_model)

    return SentenceTransformer(resolved_model, device="cpu")
