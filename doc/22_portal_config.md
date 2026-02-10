# Portal YAML configuration

## Где хранить YAML для закрытого контура

Разместите файл YAML в каталоге, доступном в закрытом контуре, например:

```
/etc/portal/portal.yml
```

Укажите путь через переменную окружения:

```
export PORTAL_CONFIG_PATH=/etc/portal/portal.yml
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
    sql_registry:
      base_dir: /opt/portal/sql
      queries:
        portal_events: queries/portal_events.sql
```

## Обязательные переменные окружения

- `PORTAL_PROFILE` — активный профиль в `profiles`
- `PORTAL_DB_HOST`
- `PORTAL_DB_PORT`
- `PORTAL_DB_NAME`
- `PORTAL_DB_USER`
- `PORTAL_DB_PASSWORD`

## Как переключать dev/prod

Укажите имя профиля в `PORTAL_PROFILE`, например:

```
export PORTAL_PROFILE=dev
```

или:

```
export PORTAL_PROFILE=prod
```

## Проверка конфигурации

```
export PORTAL_CONFIG_PATH=./config/portal.example.yml
export PORTAL_PROFILE=dev
export PORTAL_DB_HOST=...
export PORTAL_DB_PORT=...
export PORTAL_DB_NAME=...
export PORTAL_DB_USER=...
export PORTAL_DB_PASSWORD=...

python manage.py portal_config_info
python manage.py check
python manage.py shell -c "from django.db import connections; print(connections['portal'].settings_dict['HOST'])"
python manage.py test
```
