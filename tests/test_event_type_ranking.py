from django.test import TestCase, override_settings

from apps.analysis_app.services import rank_event_types
from apps.classifier.models import EventType, EventTypePattern


@override_settings(SKIP_SEMANTIC_MODEL=True, CLASSIFIER_MIN_SCORE=0.35, CLASSIFIER_TOP_K=5)
class EventTypeRankingTests(TestCase):
    def test_regex_candidates_ranked_by_longer_match(self):
        t1 = EventType.objects.create(event_type="Короткий")
        t2 = EventType.objects.create(event_type="Длинный")
        EventTypePattern.objects.create(event_type=t1, pattern=r"кража", article_of_law="158")
        EventTypePattern.objects.create(event_type=t2, pattern=r"кража с проникновением", article_of_law="158.2")

        best, candidates = rank_event_types("Выявлена кража с проникновением в помещение", top_k=5)

        self.assertIsNotNone(best)
        self.assertEqual(best.event_type_name, "Длинный")
        self.assertEqual(best.match_method, "regex_hit")
        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual([c.event_type_name for c in candidates[:2]], ["Длинный", "Короткий"])

    @override_settings(CLASSIFIER_MIN_SCORE=0.8)
    def test_fuzzy_best_respects_min_score_threshold(self):
        t1 = EventType.objects.create(event_type="ДТП")
        t2 = EventType.objects.create(event_type="Пожар")
        EventTypePattern.objects.create(event_type=t1, pattern="дорожно транспортное происшествие")
        EventTypePattern.objects.create(event_type=t2, pattern="возгорание в жилом доме")

        best, candidates = rank_event_types("случайный текст без совпадений", top_k=5)

        self.assertTrue(candidates)
        self.assertLess(candidates[0].score, 0.8)
        self.assertIsNone(best)

    def test_inactive_event_types_and_patterns_are_skipped(self):
        active = EventType.objects.create(event_type="Активный", is_active=True)
        inactive = EventType.objects.create(event_type="Неактивный", is_active=False)
        EventTypePattern.objects.create(event_type=active, pattern=r"мошенничество", is_active=True)
        EventTypePattern.objects.create(event_type=active, pattern=r"мошенн", is_active=False)
        EventTypePattern.objects.create(event_type=inactive, pattern=r"мошенничество", is_active=True)

        best, candidates = rank_event_types("Выявлено мошенничество", top_k=5)

        self.assertIsNotNone(best)
        self.assertEqual(best.event_type_name, "Активный")
        self.assertEqual(len(candidates), 1)
