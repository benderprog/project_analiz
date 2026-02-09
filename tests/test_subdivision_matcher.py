import uuid
from unittest import mock

from django.test import TestCase, override_settings

from apps.analysis_app.models import CachedSubdivision
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache, match_subdivision
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text
from apps.analysis_app import views as analysis_views


class SubdivisionMatcherTests(TestCase):
    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_match_subdivision_prefers_substring_match(self):
        subdivision = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="КПП-2 «Ухтомское»",
            normalized_name=normalize_subdivision_text("КПП-2 «Ухтомское»"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        paragraph = "На КПП №2 \"Ухтомское\" выявлено нарушение."
        candidates = match_subdivision(paragraph, top_k=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["portal_subdivision_id"], str(subdivision.portal_subdivision_id))
        self.assertEqual(candidates[0]["match_method"], "substring")
        self.assertIsNotNone(candidates[0]["normalized_span"])

    @override_settings(SKIP_SEMANTIC_MODEL=False, SUBDIVISION_SEMANTIC_THRESHOLD=0.5)
    def test_match_subdivision_semantic_fallback_uses_windows(self):
        CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГК Северная",
            normalized_name=normalize_subdivision_text("Северная"),
            embedding=[1.0, 0.0],
        )
        CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГК Южная",
            normalized_name=normalize_subdivision_text("Южная"),
            embedding=[0.0, 1.0],
        )
        invalidate_subdivision_cache()

        class StubModel:
            def encode(self, texts):
                return [[1.0, 0.0] for _ in texts]

        with mock.patch(
            "apps.analysis_app.subdivision_matcher.get_sentence_model", return_value=StubModel()
        ):
            candidates = match_subdivision(
                "Службой выявлено нарушение на пункте Северном.", top_k=1
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["match_method"], "semantic_window")
        self.assertEqual(candidates[0]["name"], "ПОГК Северная")

    def test_build_comments_includes_locality_mismatch(self):
        comments = analysis_views._build_comments(
            {
                "matched": True,
                "diffs": {},
                "subdivision_locality_mismatch": True,
                "subdivision_locality_query": {"type": "с", "name": "лесное"},
                "subdivision_locality_candidate": {"type": "с", "name": "полярное"},
            }
        )

        self.assertTrue(any("Населённый пункт не совпадает" in comment for comment in comments))
