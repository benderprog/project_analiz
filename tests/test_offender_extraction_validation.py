from django.test import SimpleTestCase

from apps.analysis_app.offender_extractor import extract_offenders


class OffenderExtractionValidationTests(SimpleTestCase):
    def test_rejects_bogus_offender_after_citizenship(self):
        text = (
            "гражданка РФ Смирнова Мария Сергеевна (1996 г.р.) и "
            "гражданин РФ осуществляла фото/видео с территории КПП."
        )

        offenders = extract_offenders(text)

        names = [offender["full_name"] for offender in offenders]
        self.assertEqual(len(names), 1)
        self.assertIn("Смирнова Мария Сергеевна", names)
        self.assertTrue(all("РФ осуществляла фото" not in name for name in names))

    def test_extracts_two_offenders_when_both_present(self):
        text = (
            "гражданка РФ Смирнова Мария Сергеевна (1996 г.р.) и "
            "гражданин РФ Климов Андрей Олегович 03.03.1990 г.р."
        )

        offenders = extract_offenders(text)

        names = sorted(offender["full_name"] for offender in offenders)
        self.assertEqual(len(names), 2)
        self.assertEqual(names, ["Климов Андрей Олегович", "Смирнова Мария Сергеевна"])

    def test_keeps_name_with_year_only_birth_info(self):
        text = "гражданка РФ Смирнова Мария Сергеевна (1996 г.р.)"

        offenders = extract_offenders(text)

        names = [offender["full_name"] for offender in offenders]
        self.assertEqual(names, ["Смирнова Мария Сергеевна"])
