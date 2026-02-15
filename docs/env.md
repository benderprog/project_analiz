# Переменные окружения

Ниже перечислены ключевые переменные, подтверждённые кодом.

## Django / базовые

- `DJANGO_SECRET_KEY` (обязательно в prod, есть dev default)
- `DJANGO_DEBUG` (`true`/`false`)
- `DJANGO_ALLOWED_HOSTS` (CSV)

Source: config/settings.py

## App DB (`default`)

- `APP_DB_NAME`
- `APP_DB_USER`
- `APP_DB_PASSWORD`
- `APP_DB_HOST`
- `APP_DB_PORT`

Source: config/settings.py (`DATABASES['default']`)

## Portal DB (`portal`)

- `PORTAL_DB_NAME` (test-значение по умолчанию: `portal_db_test`)
- `PORTAL_DB_USER`
- `PORTAL_DB_PASSWORD`
- `PORTAL_DB_HOST`
- `PORTAL_DB_PORT`

Source: config/settings.py (`DATABASES['portal']`)

## Тестовый профиль Portal DB (кнопка «Тестовая БД» в админке)

- `PORTAL_DB_TEST_HOST`
- `PORTAL_DB_TEST_PORT`
- `PORTAL_DB_TEST_NAME`
- `PORTAL_DB_TEST_USER`
- `PORTAL_DB_TEST_PASSWORD`

Если `PORTAL_DB_TEST_*` не задан, используется fallback на `PORTAL_DB_*`.

Source: apps/analysis_app/portal_db_settings_service.py (`get_test_portal_db_params`)  
Source: apps/analysis_app/admin.py (`PortalDbConnectionSettingsAdmin.use_test_db_view`)

## Шифрование пароля Portal DB

- `PORTAL_DB_FERNET_KEY` — опциональный ключ Fernet.
- Если не задан, ключ детерминированно строится из `SECRET_KEY`.
- Для шифрования требуется пакет `cryptography`.

Source: apps/analysis_app/utils/portal_db_crypto.py (`_derive_key`, `_get_fernet`)  
Source: requirements.txt

## Portal gateway / profile

- `PORTAL_GATEWAY_BACKEND` (`orm`/`sql`)
- `PORTAL_PROFILE`
- `PORTAL_CONFIG_PATH`

Source: config/settings.py (`PORTAL_GATEWAY_BACKEND`, загрузка portal config)  
Source: apps/portaldb/portal_config.py

## Семантическая модель и offline

- `SEMANTIC_MODEL_NAME`
- `SEMANTIC_MODEL_PATH`
- `SKIP_SEMANTIC_MODEL`
- `HF_HUB_OFFLINE`
- `TRANSFORMERS_OFFLINE`

Source: config/settings.py  
Source: apps/analysis_app/semantic.py  
Source: apps/analysis_app/semantic_model_resolver.py

## Актуальный пример `.env.example`

Используйте файл в корне репозитория как эталон.

Source: .env.example
