import uuid

from django.test import TestCase, override_settings

from apps.analysis_app.models import CachedSubdivision, CachedSubdivisionAlias
from apps.analysis_app.subdivision_matcher import (
    extract_subdivision_queries,
    invalidate_subdivision_cache,
    match_subdivision,
)
from apps.analysis_app.utils.subdivision_norm import normalize_text
from apps.analysis_app import views as analysis_views


class SubdivisionMatcherTests(TestCase):
    def test_normalize_text_handles_unit_and_locality(self):
        normalized = normalize_text("ПЗ1 (с. Полярное)")

        self.assertIn("пз №1", normalized)
        self.assertIn("полярное", normalized)

    def test_extract_subdivision_queries_returns_normalized_fragment(self):
        text = "Проверка службой ПЗ1 (с. Полярное) выявила нарушения."
        queries = extract_subdivision_queries(text)
        normalized = [query.normalized for query in queries]

        self.assertIn("пз №1 с. полярное", normalized)

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_match_subdivision_prefers_explicit_unit_code(self):
        correct = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПЗ №1 (с. Полярное)",
            normalized_name=normalize_text("ПЗ №1 (с. Полярное)"),
            aliases=[],
            embedding=None,
        )
        wrong = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="Отделение пограничного контроля 'Центральное'",
            normalized_name=normalize_text("Отделение пограничного контроля Центральное"),
            aliases=[],
            embedding=None,
        )
        CachedSubdivisionAlias.objects.create(
            subdivision=correct,
            alias_text="ПЗ №1 (с. Полярное)",
            normalized_alias=normalize_text("ПЗ №1 (с. Полярное)"),
            embedding=None,
        )
        CachedSubdivisionAlias.objects.create(
            subdivision=wrong,
            alias_text="Отделение пограничного контроля Центральное",
            normalized_alias=normalize_text("Отделение пограничного контроля Центральное"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        candidates = match_subdivision("службой ПЗ1 (с. Полярное) выявлено", top_k=2)

        self.assertEqual(candidates[0]["name"], "ПЗ №1 (с. Полярное)")

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_match_subdivision_prefers_locality_for_unit_code(self):
        lesnoe = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГЗ №1 (с. Лесное)",
            normalized_name=normalize_text("ПОГЗ №1 (с. Лесное)"),
            aliases=[],
            embedding=None,
        )
        polyarnoe = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГЗ №1 (с. Полярное)",
            normalized_name=normalize_text("ПОГЗ №1 (с. Полярное)"),
            aliases=[],
            embedding=None,
        )
        CachedSubdivisionAlias.objects.create(
            subdivision=lesnoe,
            alias_text="ПОГЗ №1 (с. Лесное)",
            normalized_alias=normalize_text("ПОГЗ №1 (с. Лесное)"),
            embedding=None,
        )
        CachedSubdivisionAlias.objects.create(
            subdivision=polyarnoe,
            alias_text="ПОГЗ №1 (с. Полярное)",
            normalized_alias=normalize_text("ПОГЗ №1 (с. Полярное)"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        candidates = match_subdivision("службой ПОГЗ №1 (с. Лесное) выявлено", top_k=2)

        self.assertEqual(candidates[0]["name"], "ПОГЗ №1 (с. Лесное)")
        self.assertFalse(candidates[0]["locality_mismatch"])
        self.assertGreaterEqual(candidates[0]["score_percent"], candidates[1]["score_percent"])

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_match_subdivision_marks_locality_mismatch_when_missing(self):
        polyarnoe = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГЗ №1 (с. Полярное)",
            normalized_name=normalize_text("ПОГЗ №1 (с. Полярное)"),
            aliases=[],
            embedding=None,
        )
        CachedSubdivisionAlias.objects.create(
            subdivision=polyarnoe,
            alias_text="ПОГЗ №1 (с. Полярное)",
            normalized_alias=normalize_text("ПОГЗ №1 (с. Полярное)"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        candidates = match_subdivision("службой ПОГЗ №1 (с. Лесное) выявлено", top_k=1)

        self.assertEqual(candidates[0]["name"], "ПОГЗ №1 (с. Полярное)")
        self.assertTrue(candidates[0]["locality_mismatch"])
        self.assertLess(candidates[0]["score_percent"], 85)

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_match_subdivision_prefers_contained_pogk_with_locality(self):
        pogk = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГК «Северная» (пгт Северный)",
            normalized_name=normalize_text("ПОГК Северная (пгт Северный)"),
            aliases=[],
            embedding=None,
        )
        pz = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПЗ №2 (с. Васильки)",
            normalized_name=normalize_text("ПЗ №2 (с. Васильки)"),
            aliases=[],
            embedding=None,
        )
        CachedSubdivisionAlias.objects.create(
            subdivision=pogk,
            alias_text="ПОГК Северная",
            normalized_alias=normalize_text("ПОГК Северная"),
            embedding=None,
        )
        CachedSubdivisionAlias.objects.create(
            subdivision=pz,
            alias_text="ПЗ №2 (с. Васильки)",
            normalized_alias=normalize_text("ПЗ №2 (с. Васильки)"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        paragraph = "02.02.2026 в 10:35 в районе ПОГК «Северная» (пгт Северный) ..."
        candidates = match_subdivision(paragraph, top_k=2)

        self.assertEqual(candidates[0]["name"], "ПОГК «Северная» (пгт Северный)")
        self.assertGreaterEqual(candidates[0]["score"], 0.85)
        self.assertTrue(candidates[0]["flags"].get("locality_match"))
        self.assertFalse(candidates[0]["flags"].get("unit_type_conflict"))
        self.assertTrue(candidates[0]["flags"].get("containment_hit"))
        self.assertEqual(candidates[1]["name"], "ПЗ №2 (с. Васильки)")
        self.assertTrue(candidates[1]["flags"].get("unit_type_conflict"))
        self.assertTrue(candidates[1]["flags"].get("locality_conflict"))

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
