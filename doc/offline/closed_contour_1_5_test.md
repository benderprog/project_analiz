# Closed contour runbook (1.5_test)

This runbook assumes Docker is installed on both the online build host and the offline target host.

For a full from-zero, dump-first process (including pg15-compatible dump creation and cleanup commands), use:

- [doc/16_offline_dump_first_bundle.md](../16_offline_dump_first_bundle.md)

## 1) Online: build image and prepare local assets

From project root:

```bash
docker compose build web
VERSION="1.5_test"
docker tag project_analiz_web:latest "project_analiz:web-ver-${VERSION}"
```

Ensure `postgres:15` is available locally (without mandatory registry usage):

```bash
docker image inspect postgres:15 >/dev/null || docker load -i /path/to/postgres_15.tar
```

Optional model prefetch (required when `--with-model` is used):

```bash
bash scripts/prefetch_model.sh --model "paraphrase-multilingual-MiniLM-L12-v2" --out "models/paraphrase-multilingual-MiniLM-L12-v2"
```

## 2) Online: build one offline bundle

```bash
./scripts/offline/offline.sh bundle \
  --version 1.5_test \
  --db-app-dump /ABS/PATH/app_db.dump \
  --db-portal-dump /ABS/PATH/portal_db.dump \
  --with-model \
  --archive
```

Bundle output:

- `dist/offline_bundle_1_5_test/artifacts` (docker image archives)
- `dist/offline_bundle_1_5_test/compose` (`compose.yml`, `.env`, `portal.yml`, optional `models/`, `db_dumps/`)
- `dist/offline_bundle_1_5_test/db_dumps` (`app_db.dump`, `portal_db.dump`)
- `dist/offline_bundle_1_5_test/models` (optional copy of local models)
- `dist/offline_bundle_1_5_test/doc` (runbooks)
- `dist/offline_bundle_1_5_test/manifest.json` (sha256 list)

Copy the whole `dist/offline_bundle_1_5_test/` directory (or the `.tar.gz` archive) to the offline host.

## 3) Offline host: before startup

1. Disable internet/network access.
2. Stop local postgres services that can occupy `5432`.

## 4) Offline host: import images

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh import
```

## 5) Offline host: start stack (restore + migrate + web)

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh up
```

`up` starts DB containers, restores both bundled dumps, runs Django migrations, then starts `web`.

If needed, run only restore phase explicitly:

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh restore
```

## 6) Verify app

Open in browser:

- `http://localhost:8000/admin/`
- `http://localhost:8000/upload/`

## 7) Status, logs, and shutdown

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh ps
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh logs
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh down
```
