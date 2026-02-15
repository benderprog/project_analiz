# Troubleshooting

## `fe_sendauth: no password supplied`

Причина: runtime не нашёл пароль (encrypted/env/current settings).

Проверить:
1. В админке заполнен ли пароль (или ранее сохранён token).
2. Есть ли `PORTAL_DB_PASSWORD`/`PORTAL_DB_TEST_PASSWORD` в окружении.
3. Удалось ли расшифровать `password_encrypted` (корректный `PORTAL_DB_FERNET_KEY`/`SECRET_KEY`).

Source: apps/analysis_app/portal_db_runtime.py (`resolve_portal_password`)  
Source: apps/analysis_app/admin.py (`save_model`, `_connect_to_db`)  
Source: apps/analysis_app/utils/portal_db_crypto.py

## `database "portal_db" does not exist`

Причина: имя БД в настройках не совпало с реально созданной БД.

- Для test-сценария используйте `portal_db_test`.
- Для prod-сценария используйте `portal_db`.

Source: .env.example  
Source: apps/analysis_app/models.py (`PortalDbConnectionSettings.Profile`)

## `No module named cryptography`

Установите зависимости проекта:

```bash
pip install -r requirements.txt
```

Source: requirements.txt  
Source: apps/analysis_app/utils/portal_db_crypto.py (`_get_fernet`)

## Проблемы миграций

Запустить обе схемы:

```bash
python manage.py migrate
python manage.py migrate --database=portal
```

Source: scripts/bootstrap.sh

## Stale connections после смены настроек

`apply_portal_db_settings()` закрывает соединение alias `portal`, если параметры изменились. Для CLI-команд после смены env лучше перезапустить процесс.

Source: apps/analysis_app/portal_db_runtime.py (`apply_portal_db_settings`)
