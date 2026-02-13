from datetime import date

from django.test import TestCase

from apps.analysis_app.services import match_offenders
from apps.analysis_app.utils.offender_format import offender_display
from apps.portaldb.models import Offender


class OffenderNameOrderNormalizationTests(TestCase):
    def test_portal_offender_surname_first_key_matches_svodka(self):
        portal = [
            Offender(
                first_name="Иван",
                second_name="Иванов",
                patronymic_name="Иванович",
                date_of_birth=date(1991, 5, 10),
            )
        ]
        extracted = [
            {
                "full_name": "Иванов Иван Иванович",
                "birth_date": date(1991, 5, 10),
            }
        ]

        _, counts, _ = match_offenders(extracted, portal)

        self.assertEqual(counts["matched"], 1)
        self.assertEqual(counts["missing_in_portal"], 0)
        self.assertEqual(counts["missing_in_svodka"], 0)

    def test_display_portal_offender_is_surname_first(self):
        offender = Offender(
            first_name="Иван",
            second_name="Иванов",
            patronymic_name="Иванович",
            date_of_birth=date(1991, 5, 10),
        )

        display = offender_display(offender, source="portal")

        self.assertEqual(display, "Иванов Иван Иванович (10-05-1991)")

    def test_display_portal_offender_surname_first_for_partial_name(self):
        offender = Offender(
            first_name="Павел",
            second_name="Зайцев",
            patronymic_name="",
            date_of_birth=date(1980, 12, 12),
        )

        display = offender_display(offender, source="portal")

        self.assertEqual(display, "Зайцев Павел (12-12-1980)")


    def test_display_year_only_dob_as_year(self):
        offender = {
            "full_name": "Климов Андрей Олегович",
            "birth_date": "1990-01-01",
        }

        display = offender_display(offender, source="svodka")

        self.assertEqual(display, "Климов Андрей Олегович (1990)")
