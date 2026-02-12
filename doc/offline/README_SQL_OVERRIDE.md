# SQL override via `portal.yml`

Bundle exposes SQL mapping in:

- `configs/portal.yml (или configs/portal/portal.yml)`
- `configs/portal/sql/...`

## Config structure

`configs/portal.yml (или configs/portal/portal.yml)` uses:

- `profiles.<name>.sql.base_dir` (directory prefix)
- `profiles.<name>.sql.queries.<query_name>` (relative SQL file path)

Example:

```yaml
profiles:
  dev:
    sql:
      base_dir: configs/sql
      queries:
        list_pus: pu/list_pus.sql
        search_by_time: event/search_by_time.sql
```

At runtime bundle mounts `./configs` to `/app/configs` and app reads
`PORTAL_CONFIG_PATH=/app/configs/portal.yml (или configs/portal/portal.yml)`.

## Override workflow

1. Edit SQL files under `configs/sql/`.
2. If needed, remap query filenames in `configs/portal.yml (или configs/portal/portal.yml)`.
3. Restart web service:

```bash
bash scripts/offline/offline.sh down
bash scripts/offline/offline.sh up
```

Or fast restart:

```bash
docker compose -f compose/compose.yml --env-file compose/.env restart web
```
