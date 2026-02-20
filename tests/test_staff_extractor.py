from django.test import SimpleTestCase

from apps.analysis_app.offender_extractor import extract_offenders
from apps.analysis_app.offenders.matching import split_mentions_by_employee_context
from apps.analysis_app.services import _mention_from_dict
from apps.analysis_app.staff_extractor import extract_staff_mentions


class StaffExtractorTests(SimpleTestCase):
    def test_extract_fused_rank_praporshchik(self):
        text = "... (ст.пр-к Антонов Д.В.), ..."

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].surname, "Антонов")
        self.assertEqual(staff[0].initials, "Д.В.")
        self.assertEqual(staff[0].rank_full, "Старший прапорщик")
        self.assertEqual(staff[0].display, "Старший прапорщик Антонов Д.В.")

    def test_extract_spaced_rank_praporshchik_normalized_to_fused(self):
        text = "... (ст. пр-к Антонов Д.В.), ..."

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "Старший прапорщик Антонов Д.В.")

    def test_extract_praporshchik_without_st(self):
        text = "... (пр-к Антонов Д.В.), ..."

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "Прапорщик Антонов Д.В.")

    def test_extract_fused_rank_with_spaced_initials(self):
        text = "... (ст.пр-к Антонов Д. В.), ..."

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "Старший прапорщик Антонов Д.В.")

    def test_extract_parenthetical_rank_and_initials(self):
        text = "пн (ст. л-т Васильев А.А.)"

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "Старший лейтенант Васильев А.А.")

    def test_extract_st_mn_with_plus_counter(self):
        text = "пн (ст.м-н Смирнов А.А.+1)"

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "Старший мичман Смирнов А.А.")

    def test_extract_full_navy_rank(self):
        text = "доложил капитан 2 ранга Иванов П.П."

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "Капитан 2-го ранга Иванов П.П.")

    def test_extract_major_short_rank_variants(self):
        texts = [
            "м-р Кылосова О.Д.",
            "(м-р Кылосова О.Д.)",
            "м—р Кылосова О.Д.",
            "м.р Кылосова О.Д.",
        ]

        for text in texts:
            with self.subTest(text=text):
                staff = extract_staff_mentions(text)
                self.assertEqual(len(staff), 1)
                self.assertEqual(staff[0].rank_full, "Майор")
                self.assertTrue(staff[0].display.startswith("Майор"))

    def test_extract_additional_short_ranks(self):
        cases = [
            ("п/п-к Иванов И.И.", "Подполковник Иванов И.И."),
            ("к-3р Петров П.П.", "Капитан 3-го ранга Петров П.П."),
            ("ст. пр-к Сидоров С.С.", "Старший прапорщик Сидоров С.С."),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                staff = extract_staff_mentions(text)
                self.assertEqual(len(staff), 1)
                self.assertEqual(staff[0].display, expected)

    def test_fuzzy_full_rank_typo(self):
        staff = extract_staff_mentions("подполквник Иванов И.И.")

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "Подполковник Иванов И.И.")


class StaffAndOffendersSeparationTests(SimpleTestCase):
    def test_staff_is_not_in_offenders_used_for_matching(self):
        text = "(ст.м-н Смирнов А.А.+1), Иванов Иван Иванович 1991 г.р."

        extracted = extract_offenders(text)
        mentions = [_mention_from_dict(item) for item in extracted]
        eligible, _ = split_mentions_by_employee_context(text, mentions)

        offender_names = [item.full_name for item in eligible]
        self.assertEqual(offender_names, ["Иванов Иван Иванович"])

        staff_display = [item.display for item in extract_staff_mentions(text)]
        self.assertIn("Старший мичман Смирнов А.А.", staff_display)
