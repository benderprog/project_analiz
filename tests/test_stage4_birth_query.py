from datetime import date

from django.test import SimpleTestCase

from apps.analysis_app.services import _svodka_offender_birth_query


class Stage4BirthQueryTests(SimpleTestCase):
    def test_year_only_birth_uses_birth_year_without_birth_date(self):
        text = "Смирнова А.А. (1996 г.р.) доставлена в отдел."
        span_start = text.index("Смирнова")
        span_end = span_start + len("Смирнова А.А.")
        birth_date, birth_year, mode = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_year": 1996,
                "birth_date": None,
                "span": (span_start, span_end),
            },
            text,
        )

        self.assertIsNone(birth_date)
        self.assertEqual(birth_year, 1996)
        self.assertEqual(mode, "year")

    def test_year_only_birth_with_coerced_january_first_date_uses_year_mode(self):
        text = "Смирнова А.А. (1996 г.р.) доставлена в отдел."
        span_start = text.index("Смирнова")
        span_end = span_start + len("Смирнова А.А.")
        birth_date, birth_year, mode = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_year": 1996,
                "birth_date": date(1996, 1, 1),
                "span": [span_start, span_end],
            },
            text,
        )

        self.assertIsNone(birth_date)
        self.assertEqual(birth_year, 1996)
        self.assertEqual(mode, "year")

    def test_full_birth_date_string_uses_exact_date(self):
        text = "Смирнова А.А. 18.01.1996 г.р. доставлена в отдел."
        span_start = text.index("Смирнова")
        span_end = span_start + len("Смирнова А.А.")
        birth_date, birth_year, mode = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_date": "18.01.1996",
                "birth_year": 1996,
                "span": (span_start, span_end),
            },
            text,
        )

        self.assertEqual(birth_date, date(1996, 1, 18))
        self.assertEqual(birth_year, 1996)
        self.assertEqual(mode, "date")

    def test_full_birth_date_date_object_uses_exact_date(self):
        text = "Смирнова А.А. 18.01.1996 г.р. доставлена в отдел."
        span_start = text.index("Смирнова")
        span_end = span_start + len("Смирнова А.А.")
        birth_date, birth_year, mode = _svodka_offender_birth_query(
            {
                "second_name": "Смирнова",
                "birth_date": date(1996, 1, 18),
                "birth_year": 1996,
                "span": (span_start, span_end),
            },
            text,
        )

        self.assertEqual(birth_date, date(1996, 1, 18))
        self.assertEqual(birth_year, 1996)
        self.assertEqual(mode, "date")
