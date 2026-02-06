from django.test import SimpleTestCase

from apps.analysis_app import services


class NatashaExtractorSmokeTests(SimpleTestCase):
    def test_extract_date_smoke(self):
        text = "Событие произошло 12.03.2024 в городе."

        extracted = services._extract_date(text)

        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.year, 2024)

    def test_extract_names_smoke(self):
        text = "Иванов Иван Иванович находился на месте."

        extracted = services._extract_names(text)

        self.assertTrue(extracted)
        self.assertEqual(extracted[0]["full_name"], "Иванов Иван Иванович")
