import logging
from dataclasses import dataclass
from typing import Iterable

from openpyxl import load_workbook

logger = logging.getLogger(__name__)


@dataclass
class ClassifierRow:
    event_type: str
    event_pattern: str
    article_of_law: str


def _normalize_cell(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_classifier_xlsx(file_obj) -> list[ClassifierRow]:
    """Parse classifier XLSX with fill-down rules."""
    workbook = load_workbook(file_obj, data_only=True)
    sheet = workbook.active

    rows: list[ClassifierRow] = []
    last_event_type = ""
    last_pattern = ""
    last_article = ""

    for row in sheet.iter_rows(min_row=2, values_only=True):
        raw_event_type = _normalize_cell(row[0] if len(row) > 0 else None)
        raw_pattern = _normalize_cell(row[1] if len(row) > 1 else None)
        raw_article = _normalize_cell(row[2] if len(row) > 2 else None)

        if not raw_event_type and not raw_pattern and not raw_article:
            continue

        event_type = raw_event_type or last_event_type
        pattern = raw_pattern or last_pattern
        article = raw_article or last_article

        if not event_type:
            logger.debug("Skipping row without event_type after fill-down.")
            continue

        rows.append(
            ClassifierRow(
                event_type=event_type,
                event_pattern=pattern,
                article_of_law=article,
            )
        )
        last_event_type = event_type
        if raw_pattern:
            last_pattern = pattern
        if raw_article:
            last_article = article

    logger.info("Parsed %s classifier rows", len(rows))
    return rows


def import_classifier_rows(
    rows: Iterable[ClassifierRow],
    *,
    clear_before: bool = False,
) -> int:
    """Import classifier rows into the DB."""
    from apps.classifier.models import EventTypeClassifier

    if clear_before:
        EventTypeClassifier.objects.all().delete()

    created = 0
    for row in rows:
        EventTypeClassifier.objects.create(
            event_type=row.event_type,
            event_pattern=row.event_pattern,
            article_of_law=row.article_of_law,
        )
        created += 1

    logger.info("Imported %s classifier rows", created)
    return created
