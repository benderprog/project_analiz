import uuid
from unittest import mock

from django.test import TestCase, override_settings

from apps.analysis_app.models import CachedSubdivision
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache, match_subdivision
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text
from apps.analysis_app import views as analysis_views
from apps.analysis_app.services import extract_attributes


class SubdivisionMatcherTests(TestCase):
    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_match_subdivision_prefers_substring_match(self):
        subdivision = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="КПП-2 «Ухтомское»",
            normalized_short_name=normalize_subdivision_text("КПП-2 «Ухтомское»"),
            normalized_name=normalize_subdivision_text("КПП-2 «Ухтомское»"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        paragraph = "На КПП-2 \"Ухтомское\" выявлено нарушение."
        candidates, _ = match_subdivision(paragraph, top_k=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["portal_subdivision_id"], str(subdivision.portal_subdivision_id))
        self.assertEqual(candidates[0]["match_method"], "substring")
        self.assertIsNotNone(candidates[0]["normalized_span"])

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_subdivision_substring_matches_by_name_when_short_name_not_present(self):
        subdivision = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ОПК «Пятницкая» (г. Цветочный)",
            normalized_short_name=normalize_subdivision_text("ПОГЗ №1"),
            normalized_name=normalize_subdivision_text("ОПК «Пятницкая» (г. Цветочный)"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        paragraph = "В ОПК «Пятницкая» (г. Цветочный) выявлено нарушение."
        candidates, _ = match_subdivision(paragraph, top_k=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["portal_subdivision_id"], str(subdivision.portal_subdivision_id))
        self.assertEqual(candidates[0]["match_method"], "substring")
        self.assertEqual(candidates[0]["match_token"], "name")
        self.assertEqual(candidates[0]["score"], 1.0)

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_subdivision_substring_matches_by_short_name(self):
        subdivision = CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГЗ №1 (Пятницкая)",
            normalized_short_name=normalize_subdivision_text("ПОГЗ №1"),
            normalized_name=normalize_subdivision_text("ПОГЗ №1 (Пятницкая)"),
            embedding=None,
        )
        invalidate_subdivision_cache()

        paragraph = "ПОГЗ № 1 задержало нарушителя."
        candidates, _ = match_subdivision(paragraph, top_k=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["portal_subdivision_id"], str(subdivision.portal_subdivision_id))
        self.assertEqual(candidates[0]["match_method"], "substring")
        self.assertEqual(candidates[0]["match_token"], "short_name")
        self.assertEqual(candidates[0]["score"], 1.0)

    @override_settings(SKIP_SEMANTIC_MODEL=False, SUBDIVISION_SEMANTIC_THRESHOLD=0.5)
    def test_match_subdivision_semantic_fallback_uses_windows(self):
        subdivision_north = CachedSubdivision(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГК Северная",
            normalized_name=normalize_subdivision_text("ПОГК Северная"),
            embedding=[1.0, 0.0],
        )
        subdivision_north._skip_embedding_rebuild = True
        subdivision_north.save()
        subdivision_south = CachedSubdivision(
            portal_subdivision_id=uuid.uuid4(),
            name="ПОГК Южная",
            normalized_name=normalize_subdivision_text("ПОГК Южная"),
            embedding=[0.0, 1.0],
        )
        subdivision_south._skip_embedding_rebuild = True
        subdivision_south.save()
        invalidate_subdivision_cache()

        class StubModel:
            def encode(self, texts):
                return [[1.0, 0.0] for _ in texts]

        with mock.patch(
            "apps.analysis_app.subdivision_matcher.get_sentence_model", return_value=StubModel()
        ):
            candidates, _ = match_subdivision(
                "Службой выявлено нарушение на пункте Северная.", top_k=1
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["match_method"], "semantic_window")
        self.assertEqual(candidates[0]["name"], "ПОГК Северная")


    @override_settings(SKIP_SEMANTIC_MODEL=False, SUBDIVISION_SEMANTIC_THRESHOLD=0.5)
    def test_lexical_gating_prefers_uhtomskoe_and_excludes_ochakovo(self):
        subdivision_1 = CachedSubdivision(
            portal_subdivision_id=uuid.uuid4(),
            name='КПП-1 "Ухтомское"',
            normalized_short_name=normalize_subdivision_text('КПП-1 "Ухтомское"'),
            normalized_name=normalize_subdivision_text('КПП-1 "Ухтомское"'),
            embedding=[0.0, 1.0],
        )
        subdivision_1._skip_embedding_rebuild = True
        subdivision_1.save()
        subdivision_2 = CachedSubdivision(
            portal_subdivision_id=uuid.uuid4(),
            name='КПП-2 "Ухтомское"',
            normalized_short_name=normalize_subdivision_text('КПП-2 "Ухтомское"'),
            normalized_name=normalize_subdivision_text('КПП-2 "Ухтомское"'),
            embedding=[0.0, 0.9],
        )
        subdivision_2._skip_embedding_rebuild = True
        subdivision_2.save()
        subdivision_3 = CachedSubdivision(
            portal_subdivision_id=uuid.uuid4(),
            name='ПОГК "Очаково"',
            normalized_short_name=normalize_subdivision_text('ПОГК "Очаково"'),
            normalized_name=normalize_subdivision_text('ПОГК "Очаково"'),
            embedding=[1.0, 0.0],
        )
        subdivision_3._skip_embedding_rebuild = True
        subdivision_3.save()
        invalidate_subdivision_cache()

        class StubModel:
            def encode(self, texts):
                return [[0.0, 1.0] for _ in texts]

        with mock.patch(
            'apps.analysis_app.subdivision_matcher.get_sentence_model', return_value=StubModel()
        ):
            candidates, _ = match_subdivision('в АППр «Ухтомское» выявлено нарушение', top_k=5)

        self.assertGreaterEqual(len(candidates), 2)
        top_names = [item['name'] for item in candidates[:2]]
        self.assertTrue(all('Ухтомское' in name for name in top_names))
        self.assertFalse(any('Очаково' in item['name'] for item in candidates))



    @override_settings(
        SKIP_SEMANTIC_MODEL=False,
        SUBDIVISION_SEMANTIC_THRESHOLD=0.01,
        SUBDIVISION_LOW_LEXICAL_FACTOR=0.1,
        SUBDIVISION_ACCEPT_THRESHOLD=0.75,
    )
    def test_extract_attributes_does_not_determine_subdivision_without_lexical_evidence(self):
        target = CachedSubdivision(
            portal_subdivision_id=uuid.uuid4(),
            name='ОПК "Пятницкая"',
            normalized_short_name=normalize_subdivision_text('ОПК "Пятницкая"'),
            normalized_name=normalize_subdivision_text('ОПК "Пятницкая"'),
            embedding=[1.0, 0.0],
        )
        target._skip_embedding_rebuild = True
        target.save()
        invalidate_subdivision_cache()

        class StubModel:
            def encode(self, texts):
                return [[1.0, 0.0] for _ in texts]

        with mock.patch(
            'apps.analysis_app.subdivision_matcher.get_sentence_model', return_value=StubModel()
        ):
            attributes = extract_attributes('Наряд обнаружил нарушение на маршруте патруля в 12:00 01.01.2024.')

        self.assertIsNone(attributes.subdivision_id)
        self.assertIsNone(attributes.subdivision_name)
        self.assertGreaterEqual(len(attributes.subdivision_candidates), 1)
        best = attributes.subdivision_candidates[0]
        self.assertEqual(best['portal_subdivision_id'], str(target.portal_subdivision_id))
        self.assertAlmostEqual(best['semantic_score'], 1.0, places=6)
        self.assertAlmostEqual(best['lexical_factor'], 0.1, places=6)
        self.assertLess(best['score'], 0.75)

    @override_settings(
        SKIP_SEMANTIC_MODEL=False,
        SUBDIVISION_SEMANTIC_THRESHOLD=0.01,
        SUBDIVISION_ACCEPT_THRESHOLD=0.75,
    )
    def test_extract_attributes_determines_subdivision_with_lexical_evidence(self):
        target = CachedSubdivision(
            portal_subdivision_id=uuid.uuid4(),
            name='КПП "Ухтомское"',
            normalized_short_name=normalize_subdivision_text('КПП "Ухтомское"'),
            normalized_name=normalize_subdivision_text('КПП "Ухтомское"'),
            embedding=[1.0, 0.0],
        )
        target._skip_embedding_rebuild = True
        target.save()
        invalidate_subdivision_cache()

        class StubModel:
            def encode(self, texts):
                return [[1.0, 0.0] for _ in texts]

        with mock.patch(
            'apps.analysis_app.subdivision_matcher.get_sentence_model', return_value=StubModel()
        ):
            attributes = extract_attributes('Нарушение выявлено на посту Ухтомское в 12:00 01.01.2024.')

        self.assertEqual(attributes.subdivision_id, str(target.portal_subdivision_id))
        self.assertEqual(attributes.subdivision_name, target.name)
        self.assertGreaterEqual(len(attributes.subdivision_candidates), 1)
        best = attributes.subdivision_candidates[0]
        self.assertAlmostEqual(best['lexical_factor'], 1.0, places=6)
        self.assertGreaterEqual(best['score'], 0.75)

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


class TimestampStatusThresholdTests(TestCase):
    def test_status_for_timestamp_yellow_when_delta_within_error_threshold(self):
        status = analysis_views._status_for_timestamp(
            {
                "matched": True,
                "time_delta_minutes": 20,
            }
        )

        self.assertEqual(status, "yellow")

    def test_comments_include_error_when_delta_exceeds_error_threshold(self):
        comments = analysis_views._build_comments(
            {
                "matched": True,
                "time_delta_minutes": 31,
                "diffs": {},
            }
        )

        self.assertTrue(any("Ошибка: расхождение даты/времени на 31 мин (более 30 мин)." in comment for comment in comments))
        self.assertEqual(analysis_views._status_for_timestamp({"matched": True, "time_delta_minutes": 31}), "red")
