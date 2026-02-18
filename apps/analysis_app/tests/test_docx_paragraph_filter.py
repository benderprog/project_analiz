from __future__ import annotations

from tempfile import NamedTemporaryFile
import os

from django.test import SimpleTestCase, override_settings
from docx import Document

from apps.analysis_app.services import parse_docx


class ParseDocxParagraphFilterTests(SimpleTestCase):
    def _write_docx(self, paragraphs: list[str]) -> str:
        document = Document()
        for paragraph in paragraphs:
            document.add_paragraph(paragraph)

        with NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            document.save(tmp.name)
            return tmp.name

    def test_parse_docx_skips_short_paragraphs(self):
        long_text = "Событие " + ("очень важное " * 12)
        file_path = self._write_docx([
            "Заголовок",
            "   ",
            "---",
            long_text,
        ])

        try:
            with self.assertLogs("apps.analysis_app.services", level="INFO") as captured:
                paragraphs = parse_docx(file_path)

            self.assertEqual(paragraphs, [long_text.strip()])
            self.assertTrue(any("docx split: total=4, kept=1, skipped_short=3, min_chars=100" in msg for msg in captured.output))
        finally:
            os.unlink(file_path)

    @override_settings(MIN_EVENT_PARAGRAPH_CHARS=20)
    def test_parse_docx_threshold_is_configurable(self):
        file_path = self._write_docx([
            "Это абзац длиннее двадцати символов.",
            "Короткий",
        ])

        try:
            paragraphs = parse_docx(file_path)

            self.assertEqual(paragraphs, ["Это абзац длиннее двадцати символов."])
        finally:
            os.unlink(file_path)

    @override_settings(MIN_EVENT_PARAGRAPH_CHARS=100)
    def test_parse_docx_uses_normalized_length(self):
        noisy_short = "Слишком" + ("\n\n     " * 40) + "короткий"
        normalized_long = ("Длинный факт о событии " * 6).strip()
        file_path = self._write_docx([noisy_short, normalized_long])

        try:
            paragraphs = parse_docx(file_path)

            self.assertEqual(paragraphs, [normalized_long])
        finally:
            os.unlink(file_path)
