import uuid
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from docx import Document

from apps.analysis_app.models import AnalysisRun, CachedPU, CachedSubdivision
from apps.analysis_app.pu_detection import detect_pu_from_text
from apps.analysis_app.subdivision_matcher import invalidate_subdivision_cache, match_subdivision
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text


class PuDetectionTests(TestCase):
    databases = {"default", "portal"}

    def test_detect_pu_by_substring(self):
        pu = CachedPU.objects.create(
            portal_pu_id=uuid.uuid4(),
            short_name="ПУ Север",
            full_name="Пограничное управление Север",
            normalized_short_name=normalize_subdivision_text("ПУ Север"),
            normalized_full_name=normalize_subdivision_text("Пограничное управление Север"),
        )
        title_text = "Сводка Пограничного управления Север за сутки"
        result = detect_pu_from_text(title_text)

        self.assertEqual(result.pu, pu)
        self.assertEqual(result.method, "substring")

    @override_settings(SKIP_SEMANTIC_MODEL=False, PU_SEMANTIC_THRESHOLD=0.1)
    def test_detect_pu_by_semantic_fallback(self):
        pu_a = CachedPU.objects.create(
            portal_pu_id=uuid.uuid4(),
            short_name="ПУ А",
            full_name="Пограничное управление А",
            normalized_short_name=normalize_subdivision_text("ПУ А"),
            normalized_full_name=normalize_subdivision_text("Пограничное управление А"),
            embedding_short=[1.0, 0.0],
        )
        CachedPU.objects.create(
            portal_pu_id=uuid.uuid4(),
            short_name="ПУ Б",
            full_name="Пограничное управление Б",
            normalized_short_name=normalize_subdivision_text("ПУ Б"),
            normalized_full_name=normalize_subdivision_text("Пограничное управление Б"),
            embedding_full=[0.0, 1.0],
        )

        title_text = "Служебная записка без явного упоминания"
        class DummyModel:
            def encode(self, texts):
                self.last_texts = texts
                return [[1.0, 0.0]]

        with patch("apps.analysis_app.pu_detection.get_sentence_model", return_value=DummyModel()):
            result = detect_pu_from_text(title_text)

        self.assertEqual(result.pu, pu_a)
        self.assertEqual(result.method, "semantic")
        self.assertIsNotNone(result.score)
        self.assertEqual(result.score, 1.0)


class UploadFlowPuSelectionTests(TestCase):
    databases = {"default", "portal"}

    def _make_docx_bytes(self, title: str) -> bytes:
        document = Document()
        document.add_paragraph(title)
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def test_upload_flow_preselects_detected_pu(self):
        pu = CachedPU.objects.create(
            portal_pu_id=uuid.uuid4(),
            short_name="ПУ Восток",
            full_name="Пограничное управление Восток",
            normalized_short_name=normalize_subdivision_text("ПУ Восток"),
            normalized_full_name=normalize_subdivision_text("Пограничное управление Восток"),
        )
        docx_bytes = self._make_docx_bytes("Сводка ПУ Восток")
        upload = SimpleUploadedFile(
            "sample.docx",
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                response = self.client.post(reverse("analysis-upload"), {"file": upload})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'value="{pu.portal_pu_id}" selected')

                run = AnalysisRun.objects.first()
                response = self.client.post(
                    reverse("analysis-upload"),
                    {"upload_id": run.run_id, "selected_pu_id": str(pu.portal_pu_id)},
                )
        self.assertIn(response.status_code, {200, 302})
        run.refresh_from_db()
        self.assertEqual(run.selected_pu_id, str(pu.portal_pu_id))
        self.assertEqual(run.selected_pu_name, "Пограничное управление Восток")


class SubdivisionMatchPuFilterTests(TestCase):
    databases = {"default", "portal"}

    def test_subdivision_matching_filters_by_pu(self):
        pu_a_id = uuid.uuid4()
        pu_b_id = uuid.uuid4()
        pu_a = CachedPU.objects.create(
            portal_pu_id=pu_a_id,
            short_name="ПУ А",
            full_name="Пограничное управление А",
            normalized_short_name=normalize_subdivision_text("ПУ А"),
            normalized_full_name=normalize_subdivision_text("Пограничное управление А"),
        )
        pu_b = CachedPU.objects.create(
            portal_pu_id=pu_b_id,
            short_name="ПУ Б",
            full_name="Пограничное управление Б",
            normalized_short_name=normalize_subdivision_text("ПУ Б"),
            normalized_full_name=normalize_subdivision_text("Пограничное управление Б"),
        )
        CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="Отдел Альфа",
            pu=pu_a,
            parent_pu_id=pu_a_id,
            normalized_name=normalize_subdivision_text("Отдел Альфа"),
        )
        CachedSubdivision.objects.create(
            portal_subdivision_id=uuid.uuid4(),
            name="Отдел Бета",
            pu=pu_b,
            parent_pu_id=pu_b_id,
            normalized_name=normalize_subdivision_text("Отдел Бета"),
        )
        invalidate_subdivision_cache()

        matches, _ = match_subdivision(
            "Доклад по отделу Альфа", selected_pu_id=pu_a_id
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0]["name"], "Отдел Альфа")

        matches, _ = match_subdivision(
            "Доклад по отделу Альфа", selected_pu_id=pu_b_id
        )
        self.assertFalse(matches)
