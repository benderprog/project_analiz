from django.test import SimpleTestCase

from apps.analysis_app.offender_extractor import extract_offenders
from apps.analysis_app.offenders.matching import split_mentions_by_employee_context
from apps.analysis_app.services import _mention_from_dict
from apps.analysis_app.staff_extractor import extract_staff_mentions


class StaffExtractorTests(SimpleTestCase):
    def test_extract_parenthetical_rank_and_initials(self):
        text = "пн (ст. л-т Васильев А.А.)"

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "ст. л-т Васильев А.А.")

    def test_extract_st_mn_with_plus_counter(self):
        text = "пн (ст.м-н Смирнов А.А.+1)"

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "ст.м-н Смирнов А.А.")

    def test_extract_full_navy_rank(self):
        text = "доложил капитан 2 ранга Иванов П.П."

        staff = extract_staff_mentions(text)

        self.assertEqual(len(staff), 1)
        self.assertEqual(staff[0].display, "капитан 2 ранга Иванов П.П.")


class StaffAndOffendersSeparationTests(SimpleTestCase):
    def test_staff_is_not_in_offenders_used_for_matching(self):
        text = "(ст.м-н Смирнов А.А.+1), Иванов Иван Иванович 1991 г.р."

        extracted = extract_offenders(text)
        mentions = [_mention_from_dict(item) for item in extracted]
        eligible, _ = split_mentions_by_employee_context(text, mentions)

        offender_names = [item.full_name for item in eligible]
        self.assertEqual(offender_names, ["Иванов Иван Иванович"])

        staff_display = [item.display for item in extract_staff_mentions(text)]
        self.assertIn("ст.м-н Смирнов А.А.", staff_display)
