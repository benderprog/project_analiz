from django.test import SimpleTestCase

from apps.analysis_app import services
from apps.analysis_app.offender_extractor import extract_offenders


class NatashaExtractorSmokeTests(SimpleTestCase):
    def test_extract_datetime_smoke(self):
        text = "Событие произошло 12.03.2024 в городе."

        extracted, time_found = services._extract_datetime(text)

        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.year, 2024)
        self.assertFalse(time_found)

    def test_extract_names_smoke(self):
        text = "Иванов Иван Иванович находился на месте."

        extracted = extract_offenders(text)

        self.assertTrue(extracted)
        self.assertEqual(extracted[0]["full_name"], "Иванов Иван Иванович")
