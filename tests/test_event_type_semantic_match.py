from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.analysis_app.services import _classify_event_type
from apps.analysis_app.views import _build_highlighted_html
from apps.classifier.models import EventType, EventTypePattern


class _StubModel:
    def encode(self, texts):
        vectors = []
        for text in texts:
            normalized = text.lower().replace("ё", "е")
            vectors.append(
                [
                    1.0,
                    1.0 if "правонар" in normalized else 0.0,
                    1.0 if "всу" in normalized else 0.0,
                ]
            )
        return vectors


class EventTypeSemanticWindowTests(TestCase):
    @override_settings(SKIP_SEMANTIC_MODEL=False, EVENT_PATTERN_SEMANTIC_THRESHOLD=0.15)
    def test_semantic_window_prefers_vsu_pattern_and_returns_evidence_span(self):
        legal_type = EventType.objects.create(event_type="Юридический общий")
        operative_type = EventType.objects.create(event_type="Оперативный интерес")

        EventTypePattern.objects.create(
            event_type=legal_type,
            pattern="Обнаружены признаки правонарушения",
            article_of_law="18.1",
        )
        EventTypePattern.objects.create(
            event_type=operative_type,
            pattern="Найдены признаки финансирования ВСУ",
            article_of_law="18.4",
        )

        text = "В ходе проверки найдены признаки финансрования ВСУ и иные сведения."

        with mock.patch("apps.analysis_app.services.get_sentence_model", return_value=_StubModel()):
            predicted_type, _, event_match = _classify_event_type(text)

        self.assertEqual(predicted_type, "Оперативный интерес")
        self.assertIsNotNone(event_match)
        span = event_match.get("span")
        self.assertIsInstance(span, list)
        evidence = text[span[0] : span[1]]
        self.assertIn("признаки", evidence.lower())
        self.assertIn("всу", evidence.lower())


class EventTypeHighlightTests(SimpleTestCase):
    def test_highlight_uses_span_only_without_substring_matches(self):
        text = "Выявлено правонарушение. Найдены признаки финансрования ВСУ."
        start = text.index("признаки")
        end = text.index("ВСУ") + len("ВСУ")
        html = _build_highlighted_html(
            text,
            extracted={"offenders": [], "staff": []},
            match_result={
                "matched": False,
                "predicted": {
                    "event_type_match": {
                        "span": [start, end],
                        "evidence_text": text[start:end],
                    }
                },
            },
        )

        self.assertIn('<span class="hl hl-green hl-eventpattern">признаки финансрования ВСУ</span>', html)
        self.assertNotIn('>право</span>нарушение', html)
