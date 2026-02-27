# Remote portal DB (PROD read-only) in closed contour

Use this mode when `app_db` stays local in offline compose, while portal data is read from external PROD DB with RO credentials.

## Required connection data

- `host`
- `port`
- `db_name`
- `user`
- `password`
- target schema/table mapping (for SQL overrides if PROD schema differs)

## Where to configure

### A) Runtime env (`compose/.env`)

```env
PORTAL_MODE=remote

APP_DB_HOST=db_app
APP_DB_PORT=5432
APP_DB_NAME=app_db
APP_DB_USER=app
APP_DB_PASSWORD=app

PORTAL_DB_HOST=<prod-portal-db-host>
PORTAL_DB_PORT=5432
PORTAL_DB_NAME=portal_db
PORTAL_DB_USER=<ro_user>
PORTAL_DB_PASSWORD=<ro_password>
```

### B) Django admin (`PortalDbConnectionSettings`)

Admin page: `.../admin/analysis_app/portaldbconnectionsettings/`

Fill:
- `profile=PROD`
- `host`, `port`, `db_name`, `user`, `password`

Then use **"Проверить подключение"** (`check-connection`) to verify access.

## Start

```bash
bash scripts/offline/offline.sh up
```

## Safety behavior in remote mode

- `portal_db_test` is skipped
- portal dump restore is skipped
- `migrate_portal` is skipped

This prevents write operations against PROD portal DB.
