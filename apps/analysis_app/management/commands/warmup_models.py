from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Warm up sentence-transformers models and validate embedding output."

    def handle(self, *args, **options):
        try:
            model = self._load_model()
            texts = [
                "Проверка загрузки модели.",
                "Warmup model embeddings.",
                "Тестовое предложение.",
            ]
            embeddings = model.encode(texts, convert_to_numpy=True)
            embeddings_list = [list(map(float, vector)) for vector in embeddings]
            if not embeddings_list or not embeddings_list[0]:
                raise CommandError("Embeddings are empty after warmup.")
        except Exception as exc:  # pragma: no cover - command used outside tests
            logger.exception("Warmup failed: %s", exc)
            raise CommandError(str(exc)) from exc

        self.stdout.write("OK")

    def _load_model(self):
        from sentence_transformers import SentenceTransformer

        model_path = settings.SEMANTIC_MODEL_PATH
        if model_path and Path(model_path).exists():
            logger.info("Loading sentence model from %s", model_path)
            return SentenceTransformer(model_path)

        logger.info("Loading sentence model by name %s", settings.SEMANTIC_MODEL_NAME)
        return SentenceTransformer(settings.SEMANTIC_MODEL_NAME)
