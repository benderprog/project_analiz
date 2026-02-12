# PortalGateway: единый доступ к portal DB

`PortalGateway` — единый слой чтения данных из портальной БД. Он поддерживает два режима:

- `orm` (по умолчанию): чтение через Django ORM модели `apps.portaldb.models`.
- `sql`: чтение через SQL-файлы из `configs/portal/sql` и `connections["portal"]`.

## Переключение backend

В `configs/portal/portal.yml` (или `configs/portal.yml` / `configs/portal.example.yml`) используется секция:

```yaml
gateway:
  backend: ${PORTAL_GATEWAY_BACKEND}  # orm|sql
  alias: portal
```

Также в settings выставляются:

- `PORTAL_GATEWAY_BACKEND`
- `PORTAL_DB_ALIAS` (для ORM backend)

## Где лежат SQL

SQL-файлы лежат в `configs/portal/sql/`:

- `pu/list_pus.sql`
- `subdivision/list_subdivisions.sql`
- `event/search_by_subdivision_time.sql`
- `event/search_by_time.sql`
- `event/event_offenders.sql`
- `event/event_snapshot.sql`

## Закрытый контур

Для закрытого контура меняются только profile/env переменные подключения к portal DB. SQL-запросы и логика анализа остаются прежними.

## Проверка

### ORM mode (default)

```bash
export PORTAL_GATEWAY_BACKEND=orm
python manage.py test
python manage.py runserver
```

### SQL mode

```bash
export PORTAL_GATEWAY_BACKEND=sql
export PORTAL_CONFIG_PATH=./configs/portal.example.yml
python manage.py portal_config_info
python manage.py runserver
```
