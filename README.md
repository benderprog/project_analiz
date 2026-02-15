# project_analiz

## Portal DB admin settings

Для настройки подключения `portal` через Django admin используется раздел
**«Настройка подключения к базе данных»**.

Дополнительные env-переменные:

- `PORTAL_DB_TEST_HOST`, `PORTAL_DB_TEST_PORT`, `PORTAL_DB_TEST_NAME`,
  `PORTAL_DB_TEST_USER`, `PORTAL_DB_TEST_PASSWORD` — тестовый профиль.
- Если `PORTAL_DB_TEST_*` не заданы, используются `PORTAL_DB_*`.
- `PORTAL_DB_FERNET_KEY` — ключ Fernet для шифрования пароля portal БД в app_db.
  Если не задан, ключ детерминированно вычисляется из `SECRET_KEY`.
