# Runtime configuration: env, Portal DB (TEST/PROD), semantic model

## Django / базовые

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`

## App DB (`default`)

- `APP_DB_NAME`
- `APP_DB_USER`
- `APP_DB_PASSWORD`
- `APP_DB_HOST`
- `APP_DB_PORT`

## Portal DB (`portal` alias)

Базовые переменные:

- `PORTAL_DB_NAME`
- `PORTAL_DB_USER`
- `PORTAL_DB_PASSWORD`
- `PORTAL_DB_HOST`
- `PORTAL_DB_PORT`

В typical local/test setup используется `portal_db_test`.

## TEST/PROD переключение для Portal DB

В админке доступен singleton `Настройка подключения к базе данных`.

Профили:

- `TEST`
- `PROD`

Кнопка **«Тестовая БД»** читает `PORTAL_DB_TEST_*` и при отсутствии конкретного параметра использует fallback из `PORTAL_DB_*`.

Переменные test-профиля:

- `PORTAL_DB_TEST_HOST`
- `PORTAL_DB_TEST_PORT`
- `PORTAL_DB_TEST_NAME`
- `PORTAL_DB_TEST_USER`
- `PORTAL_DB_TEST_PASSWORD`

## Runtime применение настроек

На каждом HTTP-запросе middleware применяет текущие runtime-настройки к alias `portal`.
Если конфигурация изменилась, текущее подключение `portal` закрывается и пересоздаётся с новыми параметрами.

## Хранение пароля Portal DB

- Пароль из формы в админке шифруется и сохраняется в `password_encrypted`.
- Шифрование использует `PORTAL_DB_FERNET_KEY`, а если ключ не задан — детерминированный ключ от `DJANGO_SECRET_KEY`.
- Для production рекомендуется явный отдельный `PORTAL_DB_FERNET_KEY`.

## Semantic model: online/offline

Порядок выбора модели:

1. `SEMANTIC_MODEL_PATH`, если путь существует.
2. `./models/<SEMANTIC_MODEL_NAME>`, если каталог существует.
3. Иначе используется `SEMANTIC_MODEL_NAME` как remote model id.

Offline-режим определяется флагами:

- `HF_HUB_OFFLINE=1|true|yes`, или
- `TRANSFORMERS_OFFLINE=1|true|yes`.

При offline-флагах и отсутствии локальной модели загрузка завершается ошибкой (без сетевых запросов).

## Связанные гайды

- Portal YAML/SQL config: [22_portal_config.md](./22_portal_config.md)
- Portal gateway режимы: [23_portal_gateway.md](./23_portal_gateway.md)
- Offline bundle/runbook: [offline/README_OFFLINE.md](./offline/README_OFFLINE.md)
