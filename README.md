# project_analiz

Сервис на Django для анализа документов и сопоставления с данными портала (подразделения, ПУ, события), включая админ-настройку runtime-подключения к portal DB.

## Где смотреть документацию

- [Аудит текущей документации](docs/audit.md)
- [Быстрый локальный запуск](docs/quickstart_local.md)
- [Переменные окружения](docs/env.md)
- [Подключение к Portal DB через админку](docs/portal_db_connection.md)
- [Офлайн-модели](docs/offline_models.md)
- [Docker в закрытом контуре](docs/docker.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Security notes](docs/security_notes.md)

## High-level схема

1. Запрос проходит через `PortalDbRuntimeSettingsMiddleware`, который перед каждым запросом применяет runtime-настройки подключения к alias `portal`.
2. Настройки берутся из `PortalDbConnectionSettings` (singleton в app_db), пароль хранится в зашифрованном виде.
3. Модели приложения `portaldb` ходят в alias `portal` через DB router.
4. Семантическая модель загружается local-first (`SEMANTIC_MODEL_PATH` или `./models/<SEMANTIC_MODEL_NAME>`), в offline режиме без локальной модели выбрасывается ошибка.

Source: config/settings.py (`MIDDLEWARE`, `DATABASES`, `PORTAL_DB_ALIAS`)  
Source: apps/analysis_app/middleware.py (`PortalDbRuntimeSettingsMiddleware.__call__`)  
Source: apps/analysis_app/portal_db_runtime.py (`apply_portal_db_settings`)  
Source: apps/analysis_app/models.py (`PortalDbConnectionSettings`)  
Source: config/db_router.py (`PortalDBRouter`)  
Source: apps/analysis_app/semantic.py (`get_sentence_model`)  
Source: apps/analysis_app/semantic_model_resolver.py (`resolve_semantic_model_path`, `is_offline_mode`)
