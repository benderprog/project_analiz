# Security notes

## Секреты и хранение

- Не коммитьте `.env` и реальные пароли.
- Используйте отдельные значения для `DJANGO_SECRET_KEY` и `PORTAL_DB_FERNET_KEY` в prod.
- Если `PORTAL_DB_FERNET_KEY` не задан, ключ шифрования привязан к `SECRET_KEY` — это упрощает старт, но усложняет независимую ротацию.

Source: apps/analysis_app/utils/portal_db_crypto.py (`_derive_key`)  
Source: config/settings.py (`SECRET_KEY`, `load_dotenv`)

## Ротация ключа шифрования

Текущее поведение не содержит автоматической миграции уже сохранённых encrypted паролей при смене `PORTAL_DB_FERNET_KEY`.

Практический безопасный сценарий:
1. Ввести новый `PORTAL_DB_FERNET_KEY`.
2. Зайти в админку и повторно сохранить пароль подключения Portal DB (перешифровать).
3. Проверить кнопкой «Проверить подключение».

Source: apps/analysis_app/admin.py (`save_model`, `check_connection_view`)  
Source: apps/analysis_app/utils/portal_db_crypto.py (`encrypt_password`, `decrypt_password`)

## TODO / ограничения

- Нет встроенного механизма массовой re-encrypt миграции для исторических значений `password_encrypted`.

Source: TODO based on repository scan (нет отдельной management-команды/миграции для re-encrypt)
