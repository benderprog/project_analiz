from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from unittest.mock import patch

from apps.analysis_app.forms import UploadDocxForm


class UploadFormsTests(SimpleTestCase):
    def test_upload_form_accepts_docx_extension(self):
        payload = SimpleUploadedFile("summary.docx", b"docx payload")

        with patch("apps.analysis_app.forms.extract_document_text"):
            form = UploadDocxForm(files={"file": [payload]})
            self.assertTrue(form.is_valid(), form.errors)

    def test_upload_form_rejects_doc_extension(self):
        payload = SimpleUploadedFile("summary.doc", b"legacy doc")

        form = UploadDocxForm(files={"file": [payload]})

        self.assertFalse(form.is_valid())
        self.assertIn("DOCX, ODT, PDF", str(form.errors))

    def test_upload_form_rejects_unsupported_extension(self):
        payload = SimpleUploadedFile("summary.txt", b"plain text")

        form = UploadDocxForm(files={"file": [payload]})

        self.assertFalse(form.is_valid())
        self.assertIn("DOC", str(form.errors))
