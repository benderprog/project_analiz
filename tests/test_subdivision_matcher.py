import uuid

from django.test import TestCase, override_settings

from apps.analysis_app.models import CachedSubdivision, CachedSubdivisionAlias
from apps.analysis_app.subdivision_matcher import (
    extract_subdivision_queries,
    invalidate_subdivision_cache,
    match_subdivision,
)
from apps.analysis_app.utils.subdivision_norm import normalize_text


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
