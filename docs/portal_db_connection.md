# Portal DB: подключение через админку

## Где находится

Django admin → **«Настройка подключения к базе данных»**.

Ограничения:
- singleton (можно создать только одну запись);
- удаление запрещено;
- список редиректит сразу в change form существующей записи.

Source: apps/analysis_app/models.py (`PortalDbConnectionSettings.Meta`)  
Source: apps/analysis_app/admin.py (`has_add_permission`, `has_delete_permission`, `changelist_view`)

## Поля и режимы

Профили:
- `TEST` — «Тестовая»;
- `PROD` — «Боевая».

Read-only label **«Режим доступа»**:
- `PROD` → `только чтение`;
- иначе `чтение/запись`.

Source: apps/analysis_app/models.py (`PortalDbConnectionSettings.Profile`)  
Source: apps/analysis_app/admin.py (`access_mode_display`)  
Source: apps/analysis_app/portal_db_runtime.py (`build_django_db_settings`, OPTIONS read only)

## Кнопки в форме

- **«Проверить подключение»**: пытается `psycopg2.connect(...)`, обновляет `last_check_ok`, `last_check_error`, `last_check_at`.
- **«Тестовая БД»**: подставляет тестовые параметры из env (`PORTAL_DB_TEST_*` с fallback на `PORTAL_DB_*`), переключает профиль в `TEST`, применяет runtime-настройки.

Source: templates/admin/analysis_app/portaldbconnectionsettings/change_form.html  
Source: apps/analysis_app/admin.py (`check_connection_view`, `use_test_db_view`)  
Source: apps/analysis_app/portal_db_settings_service.py (`get_test_portal_db_params`)

## Откуда берётся пароль и как хранится

1. В форме пароль вводится как `password` (не model field).
2. При сохранении пароль шифруется и пишется в `password_encrypted`.
3. Если пароль в форме пустой при редактировании, сохраняется старое `password_encrypted`.
4. Runtime-пароль для подключения выбирается так:
   - сначала decrypt `password_encrypted`;
   - при ошибке/пустом токене fallback на `PORTAL_DB_PASSWORD`;
   - затем fallback на текущий runtime PASSWORD в `connections.databases['portal']`.

Source: apps/analysis_app/admin_forms.py (`PortalDbConnectionSettingsAdminForm`)  
Source: apps/analysis_app/admin.py (`save_model`)  
Source: apps/analysis_app/models.py (`password_encrypted`)  
Source: apps/analysis_app/portal_db_runtime.py (`resolve_portal_password`)

## Как применяется в рантайме

На каждый HTTP-запрос middleware вызывает `apply_portal_db_settings()` и переопределяет alias `portal` в `connections.databases`. Если настройки изменились — текущее подключение `portal` закрывается.

Source: apps/analysis_app/middleware.py  
Source: apps/analysis_app/portal_db_runtime.py (`apply_portal_db_settings`)

## Типовые ошибки

- `No module named cryptography` / `cryptography package is required...` — установить зависимости из `requirements.txt`.
- `fe_sendauth: no password supplied` — не найден пароль ни в encrypted, ни в env/runtime fallback.
- `database "portal_db" does not exist` — проверьте `db_name` профиля (для test обычно `portal_db_test`, для prod — `portal_db`).

Source: apps/analysis_app/utils/portal_db_crypto.py (`_get_fernet`)  
Source: apps/analysis_app/portal_db_runtime.py (`resolve_portal_password`)  
Source: .env.example
