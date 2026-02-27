# Offline release bundle (closed contour)

## Prerequisites on online host

- Local image: `project_analiz:web-ver-<version>`
- Local image: `postgres:15`
- Local image: `redis:7-alpine`
- Dumps in custom format (`-Fc`):
  - `app_db.dump`
  - `portal_db_test.dump`

## 1. Build release image

```bash
bash scripts/release/build_image.sh 1.9
```

## 2. Build dumps with postgres:15 toolchain

```bash
# app_db
docker run --rm --network host -v "$PWD:/work" -e PGPASSWORD='<app_pwd>' postgres:15 \
  sh -lc "pg_dump -Fc -h 127.0.0.1 -p 5432 -U app -d app_db -f /work/app_db.dump"

# portal_db_test
docker run --rm --network host -v "$PWD:/work" -e PGPASSWORD='<portal_pwd>' postgres:15 \
  sh -lc "pg_dump -Fc -h 127.0.0.1 -p 5432 -U portal -d portal_db_test -f /work/portal_db_test.dump"
```

Validate dumps:

```bash
docker run --rm -v "$PWD:/work" postgres:15 sh -lc "pg_restore -l /work/app_db.dump >/dev/null"
docker run --rm -v "$PWD:/work" postgres:15 sh -lc "pg_restore -l /work/portal_db_test.dump >/dev/null"
```

## 3. Build bundle

```bash
./scripts/offline/offline.sh bundle \
  --version 1.9 \
  --db-app-dump /absolute/path/app_db.dump \
  --db-portal-dump /absolute/path/portal_db_test.dump \
  --archive
```

## 4. Import and run in closed contour

```bash
tar -xzf offline_bundle_1_9.tar.gz
cd offline_bundle_1_9
bash scripts/offline/offline.sh import
bash scripts/offline/offline.sh up
```

`up` performs restore via `postgres:15` tooling and starts runtime services: `web`, `worker`, `db_app`, `portal_db_test`, `redis`.

## 5. Operations

```bash
bash scripts/offline/offline.sh ps
bash scripts/offline/offline.sh logs
bash scripts/offline/offline.sh stop
bash scripts/offline/offline.sh start
bash scripts/offline/offline.sh down
```

For PROD RO portal mode: `doc/offline/README_REMOTE_PORTAL_RO.md` and `doc/offline/ADMIN_PORTAL_RO_RUNBOOK.md`.
