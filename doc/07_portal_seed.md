# Seeding portal_db for upload/analyze tests

## Prerequisites

- Ensure migrations are applied for the portal database alias:
  - `python manage.py migrate --database=portal`
- Place the input files in the project root (or pass explicit paths):
  - `subdivizion_primer.xlsx`
  - `test_svodka_semantic.docx`

## Usage

Seed using default file names from the project root:

```bash
python manage.py seed_portal --reset
```

Seed using explicit paths:

```bash
python manage.py seed_portal --xlsx /path/to/subdivizion_primer.xlsx --docx /path/to/test_svodka_semantic.docx --reset
```

Dry-run to preview operations without writing to the DB:

```bash
python manage.py seed_portal --dry-run --xlsx /path/to/subdivizion_primer.xlsx --docx /path/to/test_svodka_semantic.docx
```

## Scenarios created from the DOCX

The command parses non-empty DOCX paragraphs (1-based indexing). It inserts only a curated subset to create matching scenarios for the upload/analyze flow.

### FULL match

- Paragraph 1: exact datetime, subdivision, and one offender (Тарасов Илья Петрович, 04.04.1994).
- Paragraph 10: exact datetime, subdivision, and two offenders (Петров Пётр, Сидоров ...).

### PARTIAL match

- Paragraph 3: time shifted by +40 minutes, subdivision correct, only the first offender is inserted, and `event_type`/`article_of_law` are empty.
- Paragraph 7: exact datetime, subdivision correct, **no offenders**, and `event_type`/`article_of_law` are empty.
- Paragraph 14: time shifted by +15 minutes, subdivision correct, no offenders, and `event_type` set to a mismatched value.

### ABSENT in DB

- All other DOCX paragraphs are **not** inserted so they show up as absent during matching.

## DOB handling

If a birth year is detected without a full date, it is stored as `yyyy-01-01` in the portal DB.
