# Dump-first offline bundle workflow (pg15-in-docker)

This guide is a full **from-zero** flow for release `1.9`.

> Why this flow: dumps must be produced with `pg_dump` from `postgres:15` (containerized), so offline restore uses a compatible `pg_restore` and avoids errors like `unsupported version (1.15)`.

See also: [doc/offline/closed_contour_release.md](./offline/closed_contour_release.md).

## A) Clean previous offline stack (containers / volumes / network)

```bash
bash scripts/offline/offline.sh down || true
```

```bash
docker ps -aq --filter "name=^compose-" | xargs -r docker rm -f
```

```bash
docker volume ls -q --filter "name=^compose_" | xargs -r docker volume rm
```

```bash
docker network ls -q --filter "name=^compose_default$" | xargs -r docker network rm
```

## B) Ensure `postgres:15` exists locally (no mandatory `docker pull`)

Do **not** rely on registry access in this flow.

Check if image is already present:

```bash
docker image inspect postgres:15 >/dev/null && echo "OK postgres:15 local"
```

If registry is unavailable and you have artifact tar:

```bash
docker load -i /path/to/postgres_15.tar
```

Compatibility check:

```bash
docker run --rm postgres:15 pg_restore --version
```

## C) Generate dumps via dockerized `pg_dump` (`postgres:15`, `--network host`)

Load local env first:

```bash
set -a; source .env; set +a
```

```bash
DUMP_DIR="$HOME/db_dumps_project_analiz_pg15"
mkdir -p "$DUMP_DIR"
```

app DB dump:

```bash
docker run --rm --network host -v "$DUMP_DIR:/out" -e PGPASSWORD="$APP_DB_PASSWORD" postgres:15 \
  pg_dump -Fc --no-owner --no-privileges -h "$APP_DB_HOST" -p "$APP_DB_PORT" -U "$APP_DB_USER" -d "$APP_DB_NAME" -f /out/app_db.dump
```

portal DB dump:

```bash
docker run --rm --network host -v "$DUMP_DIR:/out" -e PGPASSWORD="$PORTAL_DB_PASSWORD" postgres:15 \
  pg_dump -Fc --no-owner --no-privileges -h "$PORTAL_DB_HOST" -p "$PORTAL_DB_PORT" -U "$PORTAL_DB_USER" -d "$PORTAL_DB_NAME" -f /out/portal_db_test.dump
```

Quick dump validation:

```bash
docker run --rm -v "$DUMP_DIR:/d:ro" postgres:15 sh -lc 'pg_restore --version && pg_restore -l /d/app_db.dump | head -n 5'
```

## D) Build and tag web image

```bash
docker compose build web
```

```bash
VERSION="1.10"
docker tag project_analiz_web:latest "project_analiz:web-ver-${VERSION}"
```

```bash
docker image inspect "project_analiz:web-ver-${VERSION}" >/dev/null && echo "OK web tag"
```

## E) Optional: prefetch model

```bash
MODEL="paraphrase-multilingual-MiniLM-L12-v2"
OUT="models/${MODEL}"
bash scripts/prefetch_model.sh --model "${MODEL}" --out "${OUT}"
```

## F) Build offline bundle

```bash
rm -rf dist
bash scripts/offline/offline.sh bundle --version 1.10 --with-model \
  --db-app-dump "$DUMP_DIR/app_db.dump" \
  --db-portal-dump "$DUMP_DIR/portal_db_test.dump" \
  --archive
```

## G) Import images + start

```bash
bash scripts/offline/offline.sh import
bash scripts/offline/offline.sh up
```

Expected URLs:

- `http://localhost:8000/admin/`
- `http://localhost:8000/upload/`

## H) Status / logs

`offline.sh` now supports `ps`/`status`.

```bash
bash scripts/offline/offline.sh ps
bash scripts/offline/offline.sh status
```

Direct docker compose fallback for bundle compose dir:

```bash
BUNDLE="$PWD/dist/offline_bundle_1_9"
docker compose -f "$BUNDLE/compose/compose.yml" --env-file "$BUNDLE/compose/.env" ps -a
docker compose -f "$BUNDLE/compose/compose.yml" --env-file "$BUNDLE/compose/.env" logs --tail 200
```

## I) Stop

```bash
bash scripts/offline/offline.sh down
```
