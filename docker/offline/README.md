# Offline compose assets

Templates for the offline release bundle are stored here.

Build bundle:

```bash
./scripts/offline/offline.sh bundle --version <ver> --db-app-dump /abs/path/app_db.dump --db-portal-dump /abs/path/portal_db_test.dump --archive
```

Runbook:
- `doc/offline/README_OFFLINE.md`
- `doc/offline/README_REMOTE_PORTAL_RO.md`
- `doc/offline/closed_contour_release.md`
