import uuid

from django.test import TestCase, override_settings

from apps.analysis_app.models import CachedSubdivision
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache, match_subdivision
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text


@override_settings(SKIP_SEMANTIC_MODEL=True)
class SubdivisionCandidateTests(TestCase):
    def setUp(self):
        super().setUp()
        self.pu_a_id = uuid.uuid4()
        self.pu_b_id = uuid.uuid4()
        CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="Отдел Альфа",
            parent_pu_id=self.pu_a_id,
            normalized_name=normalize_subdivision_text("Отдел Альфа"),
        )
        CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="Отдел Бета",
            parent_pu_id=self.pu_b_id,
            normalized_name=normalize_subdivision_text("Отдел Бета"),
        )
        invalidate_subdivision_cache()

    def test_subdivision_candidates_general_not_filtered(self):
        _, meta = match_subdivision("Нет совпадений", selected_pu_id=None)

        self.assertEqual(meta["subdivision_candidates_total"], 2)
        self.assertEqual(meta["subdivision_candidates_after_pu_filter"], 2)
        self.assertFalse(meta["pu_filter_fallback_used"])

    def test_subdivision_candidates_filtered_by_pu(self):
        _, meta = match_subdivision("Нет совпадений", selected_pu_id=self.pu_a_id)

        self.assertEqual(meta["subdivision_candidates_total"], 2)
        self.assertEqual(meta["subdivision_candidates_after_pu_filter"], 1)
        self.assertFalse(meta["pu_filter_fallback_used"])

    def test_subdivision_candidates_fallback_when_filter_empty(self):
        unknown_pu_id = uuid.uuid4()

        candidates, meta = match_subdivision(
            "Доклад по отделу Альфа", selected_pu_id=unknown_pu_id
        )

        self.assertEqual(meta["subdivision_candidates_total"], 2)
        self.assertEqual(meta["subdivision_candidates_after_pu_filter"], 0)
        self.assertTrue(meta["pu_filter_fallback_used"])
        self.assertTrue(candidates)

    def test_matcher_uses_all_candidates_for_general_summary(self):
        candidates, meta = match_subdivision(
            "Доклад по отделу Бета", selected_pu_id=None
        )

        self.assertEqual(meta["subdivision_candidates_after_pu_filter"], 2)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["name"], "Отдел Бета")
