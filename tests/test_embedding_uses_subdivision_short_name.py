from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.analysis_app.utils.text_normalize import normalize_subdivision_text
from apps.portaldb.models import Pu, Subdivision


class StubSentenceModel:
    def __init__(self) -> None:
        self.calls = []

    def encode(self, texts):
        if texts:
            self.calls.append(list(texts))
        return [[0.0, 0.0] for _ in texts]


@override_settings(SKIP_SEMANTIC_MODEL=False)
class SubdivisionEmbeddingTextTests(TestCase):
    databases = {"default", "portal"}

    def test_embedding_text_uses_short_name_with_fallback(self):
        portal_pu = Pu.objects.using("portal").create(
            full_name="ПУ Южное", short_name="ПУ Южное"
        )
        Subdivision.objects.using("portal").create(
            name="ПОГК «Васильковое» (пгт Васильковое)",
            short_name="Васильковое",
            parent_pu=portal_pu,
        )
        Subdivision.objects.using("portal").create(
            name="ПОГК «Солнечное» (пгт Солнечное)",
            short_name="",
            parent_pu=portal_pu,
        )
        stub_model = StubSentenceModel()

        with mock.patch(
            "apps.analysis_app.subdivision_cache.get_sentence_model",
            return_value=stub_model,
        ):
            call_command("sync_subdivision_cache", rebuild_embeddings=True)

        called_texts = [text for call in stub_model.calls for text in call]
        expected_texts = [
            normalize_subdivision_text("Васильковое"),
            normalize_subdivision_text("ПОГК «Солнечное» (пгт Солнечное)"),
        ]

        self.assertCountEqual(called_texts, expected_texts)
