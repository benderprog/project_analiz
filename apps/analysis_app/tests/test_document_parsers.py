from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

from django.test import SimpleTestCase, override_settings

from apps.analysis_app.document_parsers import (
    PdfTextLayerMissingError,
    UnsupportedDocumentFormatError,
    extract_document_text,
)
from apps.analysis_app.services import parse_uploaded_document


class DocumentParserTests(SimpleTestCase):
    def test_extract_docx(self):
        from docx import Document

        document = Document()
        document.add_paragraph("Первая строка")
        document.add_paragraph("Вторая строка")

        with NamedTemporaryFile(suffix=".docx") as tmp:
            document.save(tmp.name)
            parsed = extract_document_text(tmp.name)

        self.assertEqual(parsed.source_format, "docx")
        self.assertEqual(parsed.lines, ["Первая строка", "Вторая строка"])
        self.assertTrue(parsed.is_text_based)

    def test_extract_odt(self):
        content_xml = """<?xml version='1.0' encoding='UTF-8'?>
<office:document-content
 xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0'
 xmlns:text='urn:oasis:names:tc:opendocument:xmlns:text:1.0'>
 <office:body>
  <office:text>
   <text:h>Заголовок</text:h>
   <text:p>Строка ODT</text:p>
  </office:text>
 </office:body>
</office:document-content>"""

        with NamedTemporaryFile(suffix=".odt") as tmp:
            with ZipFile(tmp.name, "w") as archive:
                archive.writestr("content.xml", content_xml)
            parsed = extract_document_text(tmp.name)

        self.assertEqual(parsed.source_format, "odt")
        self.assertEqual(parsed.lines, ["Заголовок", "Строка ODT"])
        self.assertEqual(parsed.text_blocks, ["Заголовок", "Строка ODT"])

    def test_extract_rtf(self):
        rtf_content = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times;}}\f0\fs24 Первая строка\par Вторая строка}"

        with NamedTemporaryFile(suffix=".rtf", mode="w", encoding="utf-8") as tmp:
            tmp.write(rtf_content)
            tmp.flush()
            parsed = extract_document_text(tmp.name)

        self.assertEqual(parsed.source_format, "rtf")
        self.assertEqual(parsed.lines, ["Первая строка", "Вторая строка"])
        self.assertEqual(parsed.text_blocks, ["Первая строка", "Вторая строка"])

    def test_extract_pdf_with_text_layer(self):
        pdf_like = b"stream\nBT /F1 12 Tf 72 712 Td (Hello PDF) Tj ET\nendstream"

        with NamedTemporaryFile(suffix=".pdf") as tmp:
            Path(tmp.name).write_bytes(pdf_like)
            parsed = extract_document_text(tmp.name)

        self.assertEqual(parsed.source_format, "pdf")
        self.assertEqual(parsed.lines, ["Hello PDF"])
        self.assertEqual(parsed.text_blocks, ["Hello PDF"])

    def test_extract_pdf_without_text_layer_raises(self):
        with NamedTemporaryFile(suffix=".pdf") as tmp:
            Path(tmp.name).write_bytes(b"stream\nq 10 0 0 10 0 0 cm /Im0 Do Q\nendstream")
            with self.assertRaises(PdfTextLayerMissingError) as error:
                extract_document_text(tmp.name)

        self.assertIn("Scanned/image-only PDF is not supported yet", str(error.exception))

    @override_settings(MIN_EVENT_PARAGRAPH_CHARS=0)
    def test_parse_uploaded_document_uses_structured_blocks_for_rtf(self):
        rtf_content = r"{\rtf1\ansi Универсальный extractor\par строка 2}"

        with NamedTemporaryFile(suffix=".rtf", mode="w", encoding="utf-8") as tmp:
            tmp.write(rtf_content)
            tmp.flush()
            events, meta = parse_uploaded_document(tmp.name, filename="sample.rtf", return_slicing_meta=True)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].kind, "paragraph")
        self.assertEqual(events[0].joined_text, "Универсальный extractor")
        self.assertEqual(events[1].joined_text, "строка 2")
        self.assertEqual(meta.get("source_format"), "rtf")
        self.assertEqual(meta.get("method"), "document_text_blocks")

    def test_unsupported_format_raises(self):
        with NamedTemporaryFile(suffix=".txt") as tmp:
            Path(tmp.name).write_text("text", encoding="utf-8")
            with self.assertRaises(UnsupportedDocumentFormatError):
                extract_document_text(tmp.name)

    @override_settings(MIN_EVENT_PARAGRAPH_CHARS=0)
    def test_parse_uploaded_document_keeps_docx_path_regression(self):
        from docx import Document

        document = Document()
        document.add_paragraph("Событие 1")
        document.add_paragraph("Событие 2")

        with NamedTemporaryFile(suffix=".docx") as tmp:
            document.save(tmp.name)
            events, _ = parse_uploaded_document(tmp.name, filename="sample.docx", return_slicing_meta=True)

        self.assertEqual(len(events), 2)
        self.assertEqual([e.joined_text for e in events], ["Событие 1", "Событие 2"])

    @override_settings(MIN_EVENT_PARAGRAPH_CHARS=0)
    def test_parse_uploaded_document_uses_structured_blocks_for_odt(self):
        content_xml = """<?xml version='1.0' encoding='UTF-8'?>
<office:document-content
 xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0'
 xmlns:text='urn:oasis:names:tc:opendocument:xmlns:text:1.0'>
 <office:body>
  <office:text>
   <text:p>Первое событие</text:p>
   <text:p>Второе событие</text:p>
  </office:text>
 </office:body>
</office:document-content>"""

        with NamedTemporaryFile(suffix=".odt") as tmp:
            with ZipFile(tmp.name, "w") as archive:
                archive.writestr("content.xml", content_xml)
            events, _ = parse_uploaded_document(tmp.name, filename="sample.odt", return_slicing_meta=True)

        self.assertEqual(len(events), 2)
        self.assertEqual([e.joined_text for e in events], ["Первое событие", "Второе событие"])

    @override_settings(MIN_EVENT_PARAGRAPH_CHARS=0)
    def test_parse_uploaded_document_uses_blocks_for_pdf(self):
        pdf_like = b"stream\nBT /F1 12 Tf 72 712 Td (PDF block 1) Tj ET\nendstream\nstream\nBT /F1 12 Tf 72 680 Td (PDF block 2) Tj ET\nendstream"

        with NamedTemporaryFile(suffix=".pdf") as tmp:
            Path(tmp.name).write_bytes(pdf_like)
            events, _ = parse_uploaded_document(tmp.name, filename="sample.pdf", return_slicing_meta=True)

        self.assertEqual(len(events), 2)
        self.assertEqual([e.joined_text for e in events], ["PDF block 1", "PDF block 2"])
