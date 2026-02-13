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

    def test_quoted_name_fallback_returns_all_matching_candidates(self):
        uh_1 = uuid.uuid4()
        uh_2 = uuid.uuid4()
        CachedSubdivision.objects.create(
            portal_subdivision_id=uh_1,
            name='КПП-1 «Ухтомское» (г. Горный)',
            parent_pu_id=self.pu_a_id,
            normalized_short_name=normalize_subdivision_text('КПП-1 «Ухтомское»'),
            normalized_name=normalize_subdivision_text('КПП-1 «Ухтомское» (г. Горный)'),
        )
        CachedSubdivision.objects.create(
            portal_subdivision_id=uh_2,
            name='КПП-2 «Ухтомское» (пгт Озерный)',
            parent_pu_id=self.pu_b_id,
            normalized_short_name=normalize_subdivision_text('КПП-2 «Ухтомское»'),
            normalized_name=normalize_subdivision_text('КПП-2 «Ухтомское» (пгт Озерный)'),
        )
        invalidate_subdivision_cache()

        text = "1. В 10.35 05.04.2020 в АППр «Ухтомское» из РФ ..."
        candidates, meta = match_subdivision(text, top_k=5, selected_pu_id=None)

        self.assertEqual(meta["subdivision_query_source"], "quoted_name")
        self.assertEqual(meta["subdivision_query_text"], "Ухтомское")
        self.assertGreaterEqual(len(candidates), 2)

        names = {item["name"] for item in candidates}
        self.assertIn('КПП-1 «Ухтомское» (г. Горный)', names)
        self.assertIn('КПП-2 «Ухтомское» (пгт Озерный)', names)
        for item in candidates:
            if "Ухтомское" in item["name"]:
                self.assertEqual(item["match_method"], "quoted_name")
                self.assertTrue(item["flags"].get("lexical_quoted_hit"))
