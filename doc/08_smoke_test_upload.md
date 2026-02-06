# Smoke test: DOCX upload/analyze

## Management command

Run the lightweight smoke analyzer against a local DOCX file:

```bash
SKIP_SEMANTIC_MODEL=1 python manage.py smoke_analyze_docx --path test_svodka_semantic.docx
```

What it does:
- Uses the same parsing, extraction, and matching logic as the upload flow.
- Prints one summary line per paragraph, including the extracted date, subdivision (if any), and whether a match was found.
- Exits with a non-zero code if an exception occurs.

## Upload flow

1. Start the application as usual.
2. Upload `test_svodka_semantic.docx` through the upload page.
3. Expect a successful redirect to the analysis detail page and no crash.

## Date normalization rules

The extraction pipeline normalizes Natasha date facts into a `datetime`:
- `datetime` values pass through unchanged.
- `date` values are combined with `00:00` (or a supplied default time).
- Objects with `as_datetime()` or `as_date()` are supported when available.
- If year/month/day attributes exist, a `datetime` is constructed from those.
- Any unsupported or invalid value results in `None`.
