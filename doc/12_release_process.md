# Release process (1.9+)

## 1) Build release Docker image

Build the runtime image with release tag `project_analiz:web-ver-<version>`:

```bash
bash scripts/release/build_image.sh 1.9
```

Alternative via Makefile:

```bash
make release-image VERSION=1.9
```

The command builds `docker/Dockerfile.web` and tags the image as:

> Note: Docker build context excludes `dist/`, `*.part`, and `db_dumps/` via `.dockerignore`, so release artifacts are not copied into the runtime image.

- `project_analiz:web-ver-1.9`

## 2) Prepare PostgreSQL dumps (strictly with postgres:15 tools)

Dumps for offline bundle must be `pg_dump -Fc` and produced by `postgres:15` tools.

```bash
# app_db
docker run --rm --network host -v "$PWD:/work" -e PGPASSWORD='<app_pwd>' postgres:15 \
  sh -lc "pg_dump -Fc -h 127.0.0.1 -p 5432 -U app -d app_db -f /work/app_db.dump"

# portal_db_test (or PROD RO source if agreed)
docker run --rm --network host -v "$PWD:/work" -e PGPASSWORD='<portal_pwd>' postgres:15 \
  sh -lc "pg_dump -Fc -h 127.0.0.1 -p 5432 -U portal -d portal_db_test -f /work/portal_db_test.dump"
```

Validate dumps before bundling:

```bash
docker run --rm -v "$PWD:/work" postgres:15 sh -lc "pg_restore -l /work/app_db.dump >/dev/null"
docker run --rm -v "$PWD:/work" postgres:15 sh -lc "pg_restore -l /work/portal_db_test.dump >/dev/null"
```

## 3) Build offline bundle

```bash
./scripts/offline/offline.sh bundle \
  --version 1.10 \
  --db-app-dump "$DUMP_DIR/app_db.dump" \
  --db-portal-dump "$DUMP_DIR/portal_db_test.dump" \
  --archive
```

Bundle includes all images declared in `docker/offline/compose.yml` (web/worker image, `postgres:15`, redis, etc.).

## 4) Closed contour deployment

```bash
tar -xzf dist/offline_bundle_1_9.tar.gz
cd offline_bundle_1_9
bash scripts/offline/offline.sh import
bash scripts/offline/offline.sh up
```

Runtime services: `web`, `worker`, `db_app`, `portal_db_test` (for local portal mode).

For remote PROD portal read-only mode, see: `doc/offline/README_REMOTE_PORTAL_RO.md`.
