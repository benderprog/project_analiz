from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from apps.analysis_app.offenders.matching import (
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
        self.assertIn("с учётом падежа", result.matched_pairs[0].discrepancy)

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
