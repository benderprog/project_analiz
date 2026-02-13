from django.test import SimpleTestCase

from apps.analysis_app.offenders.normalize import normalize_fio_to_nominative


class NormalizeFioToNominativeTests(SimpleTestCase):
    def test_nominative_surname_holmatov_stays_unchanged(self):
        result = normalize_fio_to_nominative("Холматов", "Тахир", "Зокиржонович")

        self.assertEqual(result[0], "Холматов")
        self.assertEqual(result, ("Холматов", "Тахир", "Зокиржонович"))

    def test_oblique_case_normalizes_to_nominative(self):
        result = normalize_fio_to_nominative("Орлова", "Дмитрия", "Игоревича")

        self.assertEqual(result, ("Орлов", "Дмитрий", "Игоревич"))

    def test_non_confident_surname_parse_keeps_original(self):
        result = normalize_fio_to_nominative("Красный", "Иван", "Иванович")

        self.assertEqual(result[0], "Красный")
