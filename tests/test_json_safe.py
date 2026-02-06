import json
from datetime import date

from django.test import SimpleTestCase

from apps.analysis_app.utils.json_safe import offender_to_json


class JsonSafeTests(SimpleTestCase):
    def test_offender_to_json_serializes_birth_date(self):
        offender = {
            "full_name": "Иванов Иван Иванович",
            "birth_date": date(1990, 3, 3),
            "birth_year": 1990,
            "span": (5, 10),
        }

        serialized = offender_to_json(offender)

        payload = json.dumps(serialized)
        self.assertIn("1990-03-03", payload)
