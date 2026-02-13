from datetime import date

from django.test import SimpleTestCase

from apps.analysis_app.services import _svodka_offender_birth_query


class Stage4BirthQueryTests(SimpleTestCase):
    def test_year_only_birth_uses_birth_year_without_birth_date(self):
        birth_date, birth_year = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_year": 1996,
                "birth_date": None,
            }
        )

        self.assertIsNone(birth_date)
        self.assertEqual(birth_year, 1996)

    def test_year_only_birth_without_birth_date_key(self):
        birth_date, birth_year = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_year": "1996",
            }
        )

        self.assertIsNone(birth_date)
        self.assertEqual(birth_year, 1996)

    def test_full_birth_date_string_uses_exact_date(self):
        birth_date, birth_year = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_date": "18.01.1996",
                "birth_year": 1996,
            }
        )

        self.assertEqual(birth_date, date(1996, 1, 18))
        self.assertEqual(birth_year, 1996)

    def test_full_birth_date_date_object_uses_exact_date(self):
        birth_date, birth_year = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_date": date(1996, 1, 18),
                "birth_year": 1996,
            }
        )

        self.assertEqual(birth_date, date(1996, 1, 18))
        self.assertEqual(birth_year, 1996)
