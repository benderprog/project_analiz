# Remote portal DB (read-only) mode

Use this mode when app DB stays local in offline bundle, but portal DB points to an external read-only host.

## Steps

1. Edit `compose/.env` inside extracted bundle:

   ```env
   PORTAL_MODE=remote

   # app DB remains local container
   APP_DB_HOST=db_app
   APP_DB_PORT=5432
   APP_DB_NAME=app_db
   APP_DB_USER=app
   APP_DB_PASSWORD=app

   # portal DB points to remote read-only source
   PORTAL_DB_HOST=<portal-db-host>
   PORTAL_DB_PORT=5432
   PORTAL_DB_NAME=<portal_db_or_portal_db_test>
   PORTAL_DB_USER=<ro_user>
   PORTAL_DB_PASSWORD=<ro_password>
   ```

2. Keep `PORTAL_CONFIG_PATH=/app/configs/portal.yml`.
3. Use **read-only credentials** only.
4. Start stack:

   ```bash
   bash scripts/offline/offline.sh up
   ```

5. Verify portal data is readable in UI/API.

## Safety behavior in `PORTAL_MODE=remote`

- `portal_db_test` container is **not started**.
- `restore_portal` is **not executed**.
- `migrate_portal` is **not executed**.

This protects remote portal DB from accidental restore/migration writes.
