from io import BytesIO

from django.test import TestCase
from openpyxl import Workbook

from apps.classifier.importer import parse_classifier_xlsx


class ClassifierImportTests(TestCase):
    def test_parse_classifier_xlsx_fill_down(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Тип", "Паттерн", "Статья"])
        sheet.append(["Событие A", "паттерн 1", "12.1"])
        sheet.append([None, "паттерн 2", None])
        sheet.append([None, None, "12.2"])
        sheet.append([None, None, None])

        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)

        rows = parse_classifier_xlsx(stream)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].event_type, "Событие A")
        self.assertEqual(rows[1].event_type, "Событие A")
        self.assertEqual(rows[1].event_pattern, "паттерн 2")
        self.assertEqual(rows[2].article_of_law, "12.2")
