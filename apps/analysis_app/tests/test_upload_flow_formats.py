from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.analysis_app.models import AnalysisRun, CachedPU


class UploadFlowFormatsTests(TestCase):
    def setUp(self):
        CachedPU.objects.create(
            portal_pu_id="00000000-0000-0000-0000-000000000001",
            short_name="Тест ПУ",
            full_name="Тестовое пограничное управление",
        )

    def _upload(self, uploaded_file: SimpleUploadedFile):
        return self.client.post(
            reverse("analysis-upload"),
            data={"selected_pu_id": "", "file": [uploaded_file]},
            follow=True,
        )

    def _docx_file(self) -> SimpleUploadedFile:
        from docx import Document

        buffer = BytesIO()
        document = Document()
        document.add_paragraph("Тестовая строка DOCX для загрузки")
        document.save(buffer)
        return SimpleUploadedFile(
            "sample.docx",
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def _odt_file(self) -> SimpleUploadedFile:
        buffer = BytesIO()
        content_xml = """<?xml version='1.0' encoding='UTF-8'?>
<office:document-content
 xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0'
 xmlns:text='urn:oasis:names:tc:opendocument:xmlns:text:1.0'>
 <office:body><office:text><text:p>ODT тест</text:p></office:text></office:body>
</office:document-content>"""
        with ZipFile(buffer, "w") as archive:
            archive.writestr("content.xml", content_xml)
        return SimpleUploadedFile("sample.odt", buffer.getvalue(), content_type="application/vnd.oasis.opendocument.text")

    def _doc_file(self) -> SimpleUploadedFile:
        payload = b"legacy doc payload"
        return SimpleUploadedFile("sample.doc", payload, content_type="application/msword")

    def _rtf_file(self) -> SimpleUploadedFile:
        payload = r"{\rtf1\ansi Тест RTF\par Вторая строка}".encode("utf-8")
        return SimpleUploadedFile("sample.rtf", payload, content_type="application/rtf")

    def _pdf_with_text_file(self) -> SimpleUploadedFile:
        payload = b"stream\nBT /F1 12 Tf 72 712 Td (PDF text layer) Tj ET\nendstream"
        return SimpleUploadedFile("sample.pdf", payload, content_type="application/pdf")

    def _pdf_without_text_file(self) -> SimpleUploadedFile:
        payload = b"stream\nq 10 0 0 10 0 0 cm /Im0 Do Q\nendstream"
        return SimpleUploadedFile("scan.pdf", payload, content_type="application/pdf")

    def test_upload_docx_regression(self):
        response = self._upload(self._docx_file())
        self.assertEqual(response.status_code, 200)
        run = AnalysisRun.objects.get()
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)
        self.assertTrue(run.original_filename.endswith(".docx"))

    def test_upload_odt_creates_pending_run(self):
        response = self._upload(self._odt_file())
        self.assertEqual(response.status_code, 200)
        run = AnalysisRun.objects.get()
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)
        self.assertTrue(run.original_filename.endswith(".odt"))

    def test_upload_doc_shows_validation_error(self):
        response = self._upload(self._doc_file())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalysisRun.objects.count(), 0)
        form = response.context["upload_form"]
        self.assertIn("не поддерживается", str(form.errors))

    def test_upload_rtf_shows_validation_error(self):
        response = self._upload(self._rtf_file())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalysisRun.objects.count(), 0)
        form = response.context["upload_form"]
        self.assertIn("не поддерживается", str(form.errors))

    def test_upload_pdf_text_creates_pending_run(self):
        response = self._upload(self._pdf_with_text_file())
        self.assertEqual(response.status_code, 200)
        run = AnalysisRun.objects.get()
        self.assertEqual(run.status, AnalysisRun.Status.CREATED)
        self.assertTrue(run.original_filename.endswith(".pdf"))

    def test_upload_pdf_without_text_layer_shows_validation_error(self):
        response = self._upload(self._pdf_without_text_file())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalysisRun.objects.count(), 0)
        form = response.context["upload_form"]
        self.assertIn("Scanned/image-only PDF is not supported yet", str(form.errors))

    def test_upload_unsupported_format_shows_validation_error(self):
        file = SimpleUploadedFile("bad.txt", b"unsupported", content_type="text/plain")
        response = self._upload(file)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalysisRun.objects.count(), 0)
        form = response.context["upload_form"]
        self.assertIn("не поддерживается", str(form.errors))
