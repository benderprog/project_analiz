from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.semantic_model_resolver import resolve_semantic_model_path


class SemanticModelResolverTests(TestCase):
    def test_configured_path_preferred(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            configured_model = tmp_path / "custom_model"
            configured_model.mkdir()

            resolved = resolve_semantic_model_path(
                base_dir=tmp_path,
                model_name="paraphrase-multilingual-MiniLM-L12-v2",
                configured_path=str(configured_model),
            )

            self.assertEqual(resolved, str(configured_model))

    def test_autodetect_models_dir(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            model_name = "paraphrase-multilingual-MiniLM-L12-v2"
            local_model = tmp_path / "models" / model_name
            local_model.mkdir(parents=True)

            resolved = resolve_semantic_model_path(
                base_dir=tmp_path,
                model_name=model_name,
                configured_path="",
            )

            self.assertEqual(resolved, str(local_model))

    def test_fallback_to_name_when_missing(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

            resolved = resolve_semantic_model_path(
                base_dir=tmp_path,
                model_name=model_name,
                configured_path="",
            )

            self.assertEqual(resolved, model_name)


class SemanticOfflineModelTests(SimpleTestCase):
    @override_settings(
        SKIP_SEMANTIC_MODEL=False,
        BASE_DIR=Path("/tmp/nonexistent_base_for_semantic_test"),
        SEMANTIC_MODEL_NAME="paraphrase-multilingual-MiniLM-L12-v2",
        SEMANTIC_MODEL_PATH="",
    )
    def test_offline_mode_missing_local_raises(self):
        get_sentence_model.cache_clear()
        with patch.dict("os.environ", {"HF_HUB_OFFLINE": "1"}, clear=False):
            with self.assertRaisesRegex(
                RuntimeError,
                "Offline mode enabled but local semantic model not found",
            ):
                get_sentence_model()
        get_sentence_model.cache_clear()
