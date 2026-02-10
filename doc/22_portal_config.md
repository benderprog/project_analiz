# Portal YAML configuration

## Рекомендуемое расположение YAML в dev

В репозитории храните рабочий dev-файл в:

```
configs/portal.yml
```

Пример структуры лежит в:

```
configs/portal.example.yml
```

Если `PORTAL_CONFIG_PATH` не задан, приложение сначала ищет `configs/portal.yml`, затем `configs/portal.example.yml` (с предупреждением).

## Где хранить YAML для закрытого контура

В закрытом контуре храните конфиг вне репозитория, например:

```
/etc/project_analiz/portal.yml
```

И задавайте путь переменной окружения:

```
export PORTAL_CONFIG_PATH=/etc/project_analiz/portal.yml
```

## Минимальная структура YAML

```yaml
profiles:
  dev:
    database:
      engine: django.db.backends.postgresql
      name: ${PORTAL_DB_NAME}
      user: ${PORTAL_DB_USER}
      password: ${PORTAL_DB_PASSWORD}
      host: ${PORTAL_DB_HOST}
      port: ${PORTAL_DB_PORT}
    sql:
      base_dir: configs/portal/sql
      queries:
        list_pus: pu/list_pus.sql
        list_subdivisions: subdivision/list_subdivisions.sql
        search_by_subdivision_time: event/search_by_subdivision_time.sql
        search_by_time: event/search_by_time.sql
        event_offenders: event/event_offenders.sql
        event_snapshot: event/event_snapshot.sql
```

## SQL assets

Базовое расположение SQL-ассетов:

```
configs/portal/sql/
```

`sql.base_dir` может быть абсолютным или относительным. Для относительного пути используется корень проекта.

Для обратной совместимости поддерживается и старое расположение `apps/portaldb/sql` как fallback при поиске SQL-файлов.

## Обязательные переменные окружения

- `PORTAL_PROFILE` — активный профиль в `profiles`
- `PORTAL_DB_HOST`
- `PORTAL_DB_PORT`
- `PORTAL_DB_NAME`
- `PORTAL_DB_USER`
- `PORTAL_DB_PASSWORD`

## Проверка конфигурации

```
# без PORTAL_CONFIG_PATH будет выбран configs/portal.yml (если есть)
python manage.py portal_config_info

# явный путь
export PORTAL_CONFIG_PATH=./configs/portal.example.yml
python manage.py portal_config_info

# проверка SQL lookup
python manage.py shell -c "from apps.portaldb.sql_registry import get_sql_registry; r = get_sql_registry(); print(r.get_sql('list_pus')[:80])"

python manage.py test
```


## Gateway backend

`portal.yml` supports `gateway.backend` (`orm` or `sql`) and `gateway.alias` (ORM DB alias, default `portal`).
Set `PORTAL_GATEWAY_BACKEND=sql` to switch to SQL gateway.
