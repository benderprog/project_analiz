from django.test import SimpleTestCase

from apps.analysis_app.offenders.normalize import normalize_fio_to_nominative


class NormalizeFioToNominativeTests(SimpleTestCase):
    def test_preserves_standard_fio_surface_form(self):
        result = normalize_fio_to_nominative("Холматов", "Тахир", "Зокиржонович")

        self.assertEqual(result[0], "Холматов")
        self.assertEqual(result, ("Холматов", "Тахир", "Зокиржонович"))

    def test_does_not_lemmatize_oblique_case_tokens(self):
        result = normalize_fio_to_nominative("Орлова", "Дмитрия", "Игоревича")

        self.assertEqual(result, ("Орлова", "Дмитрия", "Игоревича"))

    def test_keeps_patronymic_suffix_lowercase(self):
        result = normalize_fio_to_nominative("Парамонов", "Инфантил", "ГИЛЬЯМИНОВИЧ ОГЛЫ")

        self.assertEqual(result, ("Парамонов", "Инфантил", "Гильяминович оглы"))
