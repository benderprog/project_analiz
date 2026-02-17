from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from apps.analysis_app.offenders.matching import (
    _dob_discrepancy,
    _format_dob,
    match_offenders_with_details,
    split_mentions_by_employee_context,
)
from apps.analysis_app.offenders.types import OffenderMention, PortalOffender


def _mention(full_name: str, second: str, first: str = "", middle: str = "", span=(0, 1), birth=None):
    return OffenderMention(
        full_name=full_name,
        second_name=second,
        first_name=first,
        patronymic_name=middle,
        birth_date=birth,
        birth_year=(birth.year if birth else None),
        span=span,
        source="test",
        surface_text=full_name,
    )


class DobFormattingRegressionTests(SimpleTestCase):
    def test_format_dob_year_only_is_year(self):
        self.assertEqual(_format_dob(date(1990, 1, 1)), "1990")

    def test_dob_discrepancy_year_only_vs_full_same_year_is_none(self):
        mention = _mention(
            "Климов Андрей Олегович",
            "Климов",
            "Андрей",
            "Олегович",
            birth=date(1990, 1, 1),
        )
        portal = PortalOffender(
            "Климов Андрей Олегович",
            "Климов",
            "Андрей",
            "Олегович",
            date(1990, 3, 3),
        )

        self.assertIsNone(_dob_discrepancy(mention, portal))


class EmployeeContextFilterTests(SimpleTestCase):
    def test_excludes_staff_mention_by_context(self):
        text = "(пр-к Кылосова О.Д.) ... Холматов Тахир ..."
        staff_start = text.index("Кылосова")
        offender_start = text.index("Холматов")
        mentions = [
            _mention("Кылосова О.Д.", "Кылосова", "О", "Д", (staff_start, staff_start + 12)),
            _mention("Холматов Тахир", "Холматов", "Тахир", "", (offender_start, offender_start + 14)),
        ]

        eligible, excluded = split_mentions_by_employee_context(text, mentions)

        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].second_name, "Холматов")
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0].second_name, "Кылосова")


    def test_excludes_parenthetical_st_mn_with_plus_counter(self):
        text = "пн (ст.м-н Смирнов А.А.+1), Иванов Иван Иванович"
        staff_start = text.index("Смирнов")
        offender_start = text.index("Иванов")
        mentions = [
            _mention("Смирнов А.А.", "Смирнов", "А", "А", (staff_start, staff_start + 12)),
            _mention("Иванов Иван Иванович", "Иванов", "Иван", "Иванович", (offender_start, offender_start + 20)),
        ]

        eligible, excluded = split_mentions_by_employee_context(text, mentions)

        self.assertEqual([m.second_name for m in eligible], ["Иванов"])
        self.assertEqual([m.second_name for m in excluded], ["Смирнов"])

    def test_excluded_surname_is_overridden_if_in_portal(self):
        text = "(пр-к Кылосова О.Д.)"
        start = text.index("Кылосова")
        mentions = [_mention("Кылосова О.Д.", "Кылосова", "О", "Д", (start, start + 12))]
        eligible, excluded = split_mentions_by_employee_context(text, mentions)

        result = match_offenders_with_details(
            eligible,
            excluded,
            [PortalOffender("Кылосова Ольга Дмитриевна", "Кылосова", "Ольга", "Дмитриевна", None)],
        )

        self.assertEqual(len(result.matched_pairs), 1)
        self.assertTrue(result.matched_pairs[0].mention.employee_context)


class FuzzyOffenderMatchingTests(SimpleTestCase):
    def test_patronymic_typo_is_matched_with_discrepancy(self):
        mention = _mention(
            "Холматов Тахир Зокиржонович",
            "Холматов",
            "Тахир",
            "Зокиржонович",
            birth=date(1984, 2, 24),
        )
        portal = PortalOffender(
            "Холматов Тахир Зокирджонович",
            "Холматов",
            "Тахир",
            "Зокирджонович",
            date(1984, 2, 24),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.matched_pairs), 1)
        self.assertEqual(result.matched_pairs[0].match_type, "fuzzy")
        self.assertIn("отчество отличается", result.matched_pairs[0].discrepancy)

    def test_dob_differs_is_possible_match_only(self):
        mention = _mention(
            "Холматов Тахир Зокирджонович",
            "Холматов",
            "Тахир",
            "Зокирджонович",
            birth=date(1984, 2, 24),
        )
        portal = PortalOffender(
            "Холматов Тахир Зокирджонович",
            "Холматов",
            "Тахир",
            "Зокирджонович",
            date(1985, 2, 24),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.matched_pairs), 0)
        self.assertEqual(len(result.possible_matches), 1)

    def test_surname_with_initials_matches_portal(self):
        mention = _mention(
            "Холматов Т.З.",
            "Холматов",
            "Т",
            "З",
            birth=date(1984, 1, 1),
        )
        portal = PortalOffender(
            "Холматов Тахир Зокирджонович",
            "Холматов",
            "Тахир",
            "Зокирджонович",
            date(1984, 2, 24),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.matched_pairs), 1)
        self.assertIn("инициал", result.matched_pairs[0].discrepancy)


class RussianInflectionOffenderMatchingTests(SimpleTestCase):
    def test_genitive_case_name_with_birth_year_matches_portal_full_dob(self):
        mention = _mention(
            "Орлова Дмитрия Игоревича",
            "Орлова",
            "Дмитрия",
            "Игоревича",
            birth=date(1992, 1, 1),
        )
        portal = PortalOffender(
            "Орлов Дмитрий Игоревич",
            "Орлов",
            "Дмитрий",
            "Игоревич",
            date(1992, 12, 12),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.matched_pairs), 1)
        self.assertEqual(len(result.missing_in_summary), 0)
        self.assertNotIn("с учётом падежа", result.matched_pairs[0].discrepancy or "")

    def test_extract_attributes_preserves_surface_fio(self):
        from apps.analysis_app.services import extract_attributes

        text = "... у гражданина РФ Орлова Дмитрия Игоревича, 1992 г.р. ..."
        with mock.patch("apps.analysis_app.services.match_subdivision", return_value=([], {})):
            attrs = extract_attributes(text)

        self.assertEqual(len(attrs.offenders), 1)
        self.assertEqual(attrs.offenders[0]["full_name"], "Орлова Дмитрия Игоревича")
        self.assertEqual(attrs.offenders[0]["birth_year"], 1992)

    def test_patronymic_suffix_variant_matches_without_suffix(self):
        mention = _mention(
            "Парамонов Инфантил Гильяминович оглы",
            "Парамонов",
            "Инфантил",
            "Гильяминович оглы",
            birth=date(2000, 1, 1),
        )
        portal = PortalOffender(
            "Парамонов Инфантил Гильяминович",
            "Парамонов",
            "Инфантил",
            "Гильяминович",
            date(2000, 5, 5),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.matched_pairs), 1)
        self.assertIn(result.matched_pairs[0].match_type, {"exact", "fuzzy"})



    def test_extract_attributes_adds_dob_spans_for_date_and_year(self):
        from apps.analysis_app.services import extract_attributes

        text = (
            "гражданин РФ Иванов Иван Иванович 01.01.1955 г.р. и "
            "гражданин РФ Петров Петр Петрович (1990 г.р.)"
        )
        with mock.patch("apps.analysis_app.services.match_subdivision", return_value=([], {})):
            attrs = extract_attributes(text)

        offenders_by_name = {item["full_name"]: item for item in attrs.offenders}
        ivanov = offenders_by_name["Иванов Иван Иванович"]
        petrov = offenders_by_name["Петров Петр Петрович"]

        self.assertEqual(text[ivanov["dob_span"][0]:ivanov["dob_span"][1]], "01.01.1955")
        self.assertEqual(ivanov.get("dob_kind"), "date")
        self.assertEqual(text[petrov["dob_span"][0]:petrov["dob_span"][1]], "1990")
        self.assertEqual(petrov.get("dob_kind"), "year")

    def test_inflection_difference_is_exact_without_user_facing_notes(self):
        mention = _mention(
            "Орлов Дмитрий Игоревич",
            "Орлов",
            "Дмитрий",
            "Игоревич",
            birth=date(1992, 1, 1),
        )
        portal = PortalOffender(
            "Орлов Дмитрий Игоревич",
            "Орлов",
            "Дмитрий",
            "Игоревич",
            date(1992, 12, 12),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.matched_pairs), 1)
        self.assertEqual(result.matched_pairs[0].match_type, "exact")
        discrepancy = result.matched_pairs[0].discrepancy or ""
        self.assertNotIn("частично/с ошибкой", discrepancy)
        self.assertNotIn("косвенном падеже", discrepancy)

    def test_year_only_dob_matches_full_date_by_same_year(self):
        mention = _mention(
            "Орлова Дмитрия Игоревича",
            "Орлова",
            "Дмитрия",
            "Игоревича",
            birth=date(1992, 1, 1),
        )
        portal = PortalOffender(
            "Орлов Дмитрий Игоревич",
            "Орлов",
            "Дмитрий",
            "Игоревич",
            date(1992, 12, 12),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.possible_matches), 0)
        self.assertEqual(len(result.matched_pairs), 1)
        self.assertEqual(len(result.missing_in_summary), 0)

    def test_full_dob_mismatch_is_possible_match_but_not_missing_in_summary(self):
        mention = _mention(
            "Смирнова Мария Сергеевна",
            "Смирнова",
            "Мария",
            "Сергеевна",
            birth=date(1996, 1, 18),
        )
        portal = PortalOffender(
            "Смирнова Мария Сергеевна",
            "Смирнова",
            "Мария",
            "Сергеевна",
            date(1996, 2, 1),
        )

        result = match_offenders_with_details([mention], [], [portal])

        self.assertEqual(len(result.matched_pairs), 0)
        self.assertEqual(len(result.possible_matches), 1)
        self.assertEqual(len(result.missing_in_summary), 0)

    def test_missing_in_summary_is_deduplicated_for_duplicate_portal_offenders(self):
        mention = _mention("Иванов Иван Иванович", "Иванов", "Иван", "Иванович", birth=date(1990, 1, 1))
        portal_1 = PortalOffender(
            "Петров Петр Петрович",
            "Петров",
            "Петр",
            "Петрович",
            date(1980, 12, 12),
        )
        portal_2 = PortalOffender(
            "Петров Петр Петрович",
            "Петров",
            "Петр",
            "Петрович",
            date(1980, 12, 12),
        )

        result = match_offenders_with_details([mention], [], [portal_1, portal_2])

        self.assertEqual(len(result.missing_in_summary), 1)

    def test_year_only_match_does_not_duplicate_portal_offender_in_missing_lists(self):
        mention = _mention(
            "Смирнова Мария Сергеевна",
            "Смирнова",
            "Мария",
            "Сергеевна",
            birth=date(1996, 1, 1),
        )
        portal_smirnova = PortalOffender(
            "Смирнова Мария Сергеевна",
            "Смирнова",
            "Мария",
            "Сергеевна",
            date(1996, 2, 1),
        )
        portal_klimov = PortalOffender(
            "Климов Андрей Олегович",
            "Климов",
            "Андрей",
            "Олегович",
            date(1990, 3, 3),
        )

        result = match_offenders_with_details([mention], [], [portal_smirnova, portal_klimov])

        self.assertEqual(len(result.matched_pairs), 1)
        self.assertEqual(result.matched_pairs[0].portal.second_name, "Смирнова")
        self.assertEqual([item.second_name for item in result.missing_in_summary], ["Климов"])
        self.assertEqual(len(result.missing_in_portal), 0)


class EmployeeContextParenthesesRegressionTests(SimpleTestCase):
    def test_multiple_parentheses_do_not_exclude_regular_offenders(self):
        text = (
            "(ст. л-т Васильев А.А.) гражданка РФ Смирнова Мария Сергеевна и "
            "гражданин РФ Климов Андрей Олегович (не знали о правилах прохода)"
        )

        from apps.analysis_app.services import extract_attributes

        with mock.patch("apps.analysis_app.services.match_subdivision", return_value=([], {})):
            attrs = extract_attributes(text)

        self.assertEqual(
            sorted(item["full_name"] for item in attrs.offenders),
            ["Климов Андрей Олегович", "Смирнова Мария Сергеевна"],
        )
        self.assertEqual(len(attrs.staff), 1)
        self.assertEqual(attrs.staff[0]["display"], "ст. л-т Васильев А.А.")

    def test_parenthetical_ranked_staff_is_excluded_from_eligible(self):
        text = "(ст. л-т Васильев А.А.)"
        start = text.index("Васильев")
        mentions = [_mention("Васильев А.А.", "Васильев", "А", "А", (start, start + 12))]

        eligible, excluded = split_mentions_by_employee_context(text, mentions)

        self.assertEqual(len(eligible), 0)
        self.assertEqual(len(excluded), 1)
        self.assertTrue(excluded[0].employee_context)

    def test_staff_keeps_surface_surname_without_duplicate_normalized_variant(self):
        text = "(пр-к Кылосова О.Д.), гражданка РФ Смирнова Мария Сергеевна"

        from apps.analysis_app.services import extract_attributes

        with mock.patch("apps.analysis_app.services.match_subdivision", return_value=([], {})):
            attrs = extract_attributes(text)

        self.assertEqual(len(attrs.staff), 1)
        self.assertEqual(attrs.staff[0]["display"], "пр-к Кылосова О.Д.")
        self.assertEqual(attrs.staff[0]["surname"], "Кылосова")
        self.assertNotIn("Кылосов", [item["display"] for item in attrs.staff])
