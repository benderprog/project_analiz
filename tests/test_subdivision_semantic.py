import json
from unittest import mock

from django.test import TestCase

from apps.analysis_app.models import CachedSubdivision
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache, match_subdivision
from apps.analysis_app.subdivision_utils import to_py_float, to_py_floats


class DummyFloat:
    def __init__(self, value: float) -> None:
        self.value = value

    def __float__(self) -> float:
        return float(self.value)


class SubdivisionSemanticTests(TestCase):
    def test_to_py_float_converts_scalar(self):
        try:
            import numpy as np

            value = np.float32(0.42)
        except ImportError:
            value = DummyFloat(0.42)

        result = to_py_float(value)

        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 0.42, places=6)

    def test_to_py_floats_converts_vector(self):
        try:
            import numpy as np

            vector = np.array([0.1, 0.2], dtype=np.float32)
        except ImportError:
            vector = [DummyFloat(0.1), DummyFloat(0.2)]

        result = to_py_floats(vector)

        self.assertEqual(result, [0.1, 0.2])
        self.assertTrue(all(isinstance(item, float) for item in result))

    def test_match_subdivision_returns_json_safe_scores(self):
        CachedSubdivision.objects.create(
            portal_subdivision_id="00000000-0000-0000-0000-000000000001",
            name="Test Subdivision",
            normalized_name="test subdivision",
            aliases=[],
            embedding=[0.0, 1.0],
        )
        invalidate_subdivision_cache()

        class StubModel:
            def encode(self, texts):
                return [[0.0, 1.0]]

        float_value = DummyFloat(0.9)
        try:
            import numpy as np

            float_value = np.float32(0.9)
        except ImportError:
            pass

        with mock.patch(
            "apps.analysis_app.subdivision_matcher.get_sentence_model", return_value=StubModel()
        ), mock.patch(
            "apps.analysis_app.subdivision_matcher._cosine_similarity", return_value=float_value
        ):
            candidates = match_subdivision("Test Subdivision", top_k=1)

        self.assertEqual(len(candidates), 1)
        self.assertIsInstance(candidates[0]["score"], float)
        json.dumps(candidates)
