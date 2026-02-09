# PU detection and caching

## CachedPu model (app_db)

The `CachedPU` model stores portal PU data in the app database, including:

- Portal PU UUID (`portal_pu_id`)
- Short/full names + normalized variants
- Embedding (JSON list, same format as cached subdivisions)

`CachedSubdivision` stores the portal `parent_pu_id` to support fast filtering when a PU is selected.

## Cache sync

Use the new management command to refresh cached PUs from `portal_db`:

```bash
python manage.py sync_pu_cache
```

For subdivisions, continue to use the existing cache sync:

```bash
python manage.py sync_subdivision_cache
```

`portaldb.Pu` updates also trigger a best-effort cache update through a post-save signal.

## PU detection from DOCX title page

Detection extracts a title blob from:

- First 30 paragraphs of the document
- Cells from the first couple of tables (if present)

Matching order:

1. **Substring match** against normalized `CachedPU.normalized_short_name` and
   `CachedPU.normalized_full_name` (longest match wins).
2. **Semantic fallback** when no substring is found (cosine similarity against
   cached PU embeddings, above `PU_SEMANTIC_THRESHOLD`).

If no match is found, detection returns `none` and the operator can select manually.

## Upload flow

1. Upload a DOCX on `/upload`.
2. The system auto-detects a PU from the title page and presents a dropdown:
   - “Общая сводка” (no PU constraint)
   - All cached PUs (stored by portal UUID)
3. Operator can override and submit “Анализировать”.

The selected PU is stored with the analysis run and displayed in the result header.

## Subdivision matching with PU filter

When a PU is selected (not “Общая сводка”), subdivision candidate lookup is restricted to
cached subdivisions with matching `parent_pu_id` (portal UUID), reducing the candidate pool
and improving matching speed/precision. “Общая сводка” never applies a PU filter.

If filtering by PU yields zero subdivision candidates, matching automatically falls back to
the full subdivision cache and records debug info so the candidate pool is never silently empty.

## How to verify

```bash
python manage.py migrate
python manage.py migrate --database=portal

python manage.py sync_pu_cache
python manage.py sync_subdivision_cache

python manage.py runserver
```

1. Open `/upload/` and upload a DOCX with a PU mentioned on the title page.
2. Verify the dropdown appears with the detected PU preselected and “Общая сводка” present.
3. Change the PU manually and run analysis.
4. Confirm subdivision matching uses only subdivisions from the selected PU (unless “Общая сводка”).
5. If the debug output reports an empty filtered pool, verify the fallback to the full pool.
