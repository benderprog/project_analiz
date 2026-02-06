from io import BytesIO

from django.test import TestCase
from openpyxl import Workbook

from apps.classifier.importer import import_classifier_rows, parse_classifier_xlsx
from apps.classifier.models import EventType, EventTypePattern


class ClassifierImportTests(TestCase):
    def _build_workbook(self, rows: list[list[object]]) -> BytesIO:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Тип", "Паттерн", "Статья"])
        for row in rows:
            sheet.append(row)
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return stream

    def test_import_new_type_pattern_article(self):
        stream = self._build_workbook([["Событие A", "паттерн 1", "12.1"]])
        rows, skipped = parse_classifier_xlsx(stream)
        summary = import_classifier_rows(rows, skipped_rows=skipped)

        self.assertEqual(summary.created_types, 1)
        self.assertEqual(summary.created_patterns, 1)
        self.assertEqual(EventType.objects.count(), 1)
        self.assertEqual(EventTypePattern.objects.count(), 1)

    def test_import_existing_type_new_pattern(self):
        EventType.objects.create(event_type="Событие A")
        stream = self._build_workbook([["Событие A", "паттерн 2", "12.2"]])
        rows, skipped = parse_classifier_xlsx(stream)
        summary = import_classifier_rows(rows, skipped_rows=skipped)

        self.assertEqual(summary.created_types, 0)
        self.assertEqual(summary.created_patterns, 1)
        pattern = EventTypePattern.objects.get(pattern="паттерн 2")
        self.assertEqual(pattern.article_of_law, "12.2")

    def test_import_existing_pattern_updates_article(self):
        event_type = EventType.objects.create(event_type="Событие A")
        EventTypePattern.objects.create(
            event_type=event_type, pattern="паттерн 1", article_of_law="12.1"
        )
        stream = self._build_workbook([["Событие A", "паттерн 1", "12.2"]])
        rows, skipped = parse_classifier_xlsx(stream)
        summary = import_classifier_rows(rows, skipped_rows=skipped)

        self.assertEqual(summary.updated_patterns, 1)
        pattern = EventTypePattern.objects.get(pattern="паттерн 1")
        self.assertEqual(pattern.article_of_law, "12.2")

    def test_import_type_without_pattern(self):
        stream = self._build_workbook([["Событие B", "", ""]])
        rows, skipped = parse_classifier_xlsx(stream)
        summary = import_classifier_rows(rows, skipped_rows=skipped)

        self.assertEqual(summary.created_types, 1)
        self.assertEqual(summary.created_patterns, 0)
        self.assertEqual(EventType.objects.count(), 1)
        self.assertEqual(EventTypePattern.objects.count(), 0)

    def test_parse_skips_empty_row(self):
        stream = self._build_workbook([["Событие A", "паттерн 1", "12.1"], [None, None, None]])
        rows, skipped = parse_classifier_xlsx(stream)

        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped, 1)
