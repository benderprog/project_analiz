from datetime import date

from django.test import SimpleTestCase

from apps.analysis_app.offender_extractor import extract_offenders, parse_birth_info


class BirthInfoParserTests(SimpleTestCase):
    def test_parse_birth_year_in_parentheses(self):
        text = "Смирнова Мария Сергеевна (1996 г.р.) проживает."
        anchor_end = text.index("Смирнова") + len("Смирнова Мария Сергеевна")

        birth_date, birth_year = parse_birth_info(text, anchor_end)

        self.assertIsNone(birth_date)
        self.assertEqual(birth_year, 1996)

    def test_parse_full_birth_date_with_context(self):
        text = "Климов Андрей Олегович 03.03.1990 г.р. проживает."
        anchor_end = text.index("Климов") + len("Климов Андрей Олегович")

        birth_date, birth_year = parse_birth_info(text, anchor_end)

        self.assertEqual(birth_date, date(1990, 3, 3))
        self.assertEqual(birth_year, 1990)

    def test_do_not_capture_bare_year(self):
        text = "Иванов Иван Иванович 02.02.2026 произошло событие."
        anchor_end = text.index("Иванов") + len("Иванов Иван Иванович")

        birth_date, birth_year = parse_birth_info(text, anchor_end)

        self.assertIsNone(birth_date)
        self.assertIsNone(birth_year)


class OffenderExtractorTests(SimpleTestCase):
    def test_extracts_complex_patronymic_suffix(self):
        text = "... был задержан Парамонов Инфантил Гильяминович оглы 2000 г.р. ..."

        offenders = extract_offenders(text)

        self.assertEqual(len(offenders), 1)
        offender = offenders[0]
        self.assertEqual(offender["second_name"], "Парамонов")
        self.assertEqual(offender["first_name"], "Инфантил")
        self.assertEqual(offender["patronymic_name"], "Гильяминович оглы")
        self.assertIn("оглы", offender["full_name"])
        self.assertEqual(offender["birth_year"], 2000)

    def test_extract_offenders_from_paragraph(self):
        text = (
            "… Смирнова Мария Сергеевна (1996 г.р.) и … "
            "Климов Андрей Олегович 03.03.1990 г.р. …"
        )

        offenders = extract_offenders(text)

        names = sorted(offender["full_name"] for offender in offenders)
        self.assertEqual(len(names), 2)
        self.assertEqual(names, ["Климов Андрей Олегович", "Смирнова Мария Сергеевна"])

        offenders_by_name = {item["full_name"]: item for item in offenders}
        smirnova = offenders_by_name["Смирнова Мария Сергеевна"]
        self.assertEqual(smirnova["second_name"], "Смирнова")
        self.assertEqual(smirnova["first_name"], "Мария")
        self.assertEqual(smirnova["patronymic_name"], "Сергеевна")

    def test_extracts_surname_initials_without_dots(self):
        text = "Холматов Т З 1984 г.р."

        offenders = extract_offenders(text)

        self.assertEqual(len(offenders), 1)
        self.assertEqual(offenders[0]["second_name"], "Холматов")
        self.assertEqual(offenders[0]["first_name"], "Т")
        self.assertEqual(offenders[0]["patronymic_name"], "З")
