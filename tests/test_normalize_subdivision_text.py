from django.test import SimpleTestCase

from apps.analysis_app.utils.text_normalize import normalize_subdivision_text


class NormalizeSubdivisionTextTests(SimpleTestCase):
    def test_normalize_subdivision_text_variants(self):
        variants = [
            "КПП-2 «Ухтомское»",
            "КПП 2 \"Ухтомское\"",
            "КПП№2 Ухтомское",
            "КПП No 2 Ухтомское",
        ]
        normalized = {normalize_subdivision_text(value) for value in variants}

        self.assertEqual(len(normalized), 1)
        self.assertIn("кпп-2", next(iter(normalized)))

    def test_normalize_number_sign_equivalence(self):
        self.assertEqual(
            normalize_subdivision_text("ПОГЗ №1"),
            normalize_subdivision_text("ПОГЗ № 1"),
        )
