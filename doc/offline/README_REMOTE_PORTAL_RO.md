# Remote portal DB (read-only) mode

Use this mode to connect application to a real portal database in read-only mode.

## Steps

1. Edit `compose/.env` inside extracted bundle:

   ```env
   PORTAL_MODE=remote
   PORTAL_DB_HOST=<battle-db-host>
   PORTAL_DB_PORT=5432
   PORTAL_DB_USER=<ro_user>
   PORTAL_DB_PASSWORD=<ro_password>
   PORTAL_DB_NAME=<battle_db_name>
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

This protects battle portal DB from accidental restore/migration writes.
