from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from apps.analysis_app.semantic import get_sentence_model

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
        return get_sentence_model()
