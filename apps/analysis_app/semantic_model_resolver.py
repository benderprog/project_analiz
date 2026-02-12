from __future__ import annotations

import os
from pathlib import Path


def is_offline_mode() -> bool:
    """Return True when HuggingFace/Transformers offline mode is enabled."""
    offline_values = {"1", "true", "yes"}
    hf_hub_offline = os.getenv("HF_HUB_OFFLINE", "").strip().lower()
    transformers_offline = os.getenv("TRANSFORMERS_OFFLINE", "").strip().lower()
    return hf_hub_offline in offline_values or transformers_offline in offline_values


def resolve_semantic_model_path(base_dir: Path, model_name: str, configured_path: str) -> str:
    """Resolve sentence-transformers model source preferring local filesystem paths."""
    if configured_path:
        configured = Path(configured_path)
        if configured.exists():
            return str(configured)

    candidate = base_dir / "models" / model_name
    if candidate.exists():
        return str(candidate)

    return model_name
