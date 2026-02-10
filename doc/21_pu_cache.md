# PU cache

## What CachedPU stores

`CachedPU` keeps the portal reference and embeddings only:

- `portal_pu_id` (UUID from `portaldb.Pu.pu_id`)
- `embedding_short` (embedding for `Pu.short_name`, with fallback to `full_name`)
- `embedding_full` (embedding for `Pu.full_name`, with fallback to `short_name`)

Text fields (`short_name`, `full_name`) remain for labels/debugging, but no additional embedding caches are stored.

## Auto-update behavior

Whenever a `portaldb.Pu` record is saved through Django (admin or code), the post-save signal recomputes both embeddings and upserts the corresponding `CachedPU` row in the default DB.

## Manual recompute

### Admin button

Open the cached PU changelist:

```
/admin/analysis_app/cachedpu/
```

Click **"Пересчитать PU cache"** to recompute the cache for all PUs.

You can also select rows and run **"Recompute cache for selected PUs"** from the actions menu.

### Management command

```
python manage.py sync_pu_cache --rebuild-embeddings
```

This rebuilds embeddings for all portal PUs and upserts cached rows.

## Verification checklist

```
python manage.py migrate
python manage.py migrate --database=portal

python manage.py sync_pu_cache

python manage.py runserver
# 1) /admin/portaldb/pu/ -> edit a PU short/full name -> save
# 2) verify CachedPU updated (embeddings present)
# 3) /admin/analysis_app/cachedpu/ -> click “Пересчитать PU cache”
```
