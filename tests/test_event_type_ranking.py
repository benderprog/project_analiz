from django.test import TestCase, override_settings

from apps.analysis_app.services import _classify_event_type, rank_event_types
from apps.classifier.models import EventType, EventTypePattern


@override_settings(SKIP_SEMANTIC_MODEL=True, CLASSIFIER_MIN_SCORE=0.5, CLASSIFIER_TOP_K=5)
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
        self.assertLessEqual(best.score, 1.0)
        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual([c.event_type_name for c in candidates[:2]], ["Длинный", "Короткий"])

    @override_settings(CLASSIFIER_MIN_SCORE=0.8)
    def test_candidates_respect_min_score_threshold(self):
        t1 = EventType.objects.create(event_type="ДТП")
        t2 = EventType.objects.create(event_type="Пожар")
        EventTypePattern.objects.create(event_type=t1, pattern="дорожно транспортное происшествие")
        EventTypePattern.objects.create(event_type=t2, pattern="возгорание в жилом доме")

        best, candidates = rank_event_types("случайный текст без совпадений", top_k=5)

        self.assertFalse(candidates)
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

    def test_pattern_candidates_include_all_event_types_with_same_pattern(self):
        phrase = "вещество растительного происхождения"
        t1 = EventType.objects.create(event_type="Внос/вынос")
        t2 = EventType.objects.create(event_type="Специальные действия (СД)")
        EventTypePattern.objects.create(event_type=t1, pattern=phrase, article_of_law="18.3 ч.1")
        EventTypePattern.objects.create(event_type=t2, pattern=phrase)

        _, _, event_pattern, classifier_candidates = _classify_event_type(
            f"В сводке указано: {phrase}."
        )

        self.assertEqual((event_pattern or {}).get("pattern_text"), phrase)
        self.assertEqual(len(classifier_candidates), 2)
        self.assertEqual(
            {item.get("event_type_name") for item in classifier_candidates},
            {"Внос/вынос", "Специальные действия (СД)"},
        )
        self.assertTrue(all(item.get("score_percent") == 100.0 for item in classifier_candidates))
        self.assertTrue(all(item.get("score") == 1.0 for item in classifier_candidates))
