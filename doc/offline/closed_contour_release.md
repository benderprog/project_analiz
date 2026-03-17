# Closed contour runbook (version-agnostic)

1. Unpack archive `offline_bundle_<version>.tar.gz`.
2. Run `bash scripts/offline/offline.sh import`.
3. Run `bash scripts/offline/offline.sh up`.
4. Verify `web` and `worker` are running (`bash scripts/offline/offline.sh ps`).
5. Use `stop/start` for routine operations.

Notes:
- `portal_db_test` is `postgres:15` restored from `portal_db_test.dump`.
- Dumps are expected in `pg_dump -Fc` format and restored via `pg_restore` from `postgres:15` image.
- Runtime web/worker image must contain Django deps + `celery` + Redis Python client (`redis`) to avoid runtime import failures in offline contour.
