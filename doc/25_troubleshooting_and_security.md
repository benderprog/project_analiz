# Troubleshooting and security notes

## `fe_sendauth: no password supplied`

Проверьте:

1. Пароль в админке (и что запись была сохранена).
2. Наличие `PORTAL_DB_PASSWORD` / `PORTAL_DB_TEST_PASSWORD` в окружении.
3. Корректность ключа шифрования (`PORTAL_DB_FERNET_KEY` или `DJANGO_SECRET_KEY` fallback).

## `database "portal_db" does not exist`

Обычно это несоответствие имени БД профилю:

- test: обычно `portal_db_test`
- prod: обычно `portal_db`

## `No module named cryptography`

Установите зависимости:

```bash
pip install -r requirements.txt
```

## Проблемы с миграциями

Проверьте обе схемы:

```bash
python manage.py migrate
python manage.py migrate --database=portal
```

## Security guidance

- Не коммитьте `.env` и реальные секреты.
- В production используйте отдельные значения для `DJANGO_SECRET_KEY` и `PORTAL_DB_FERNET_KEY`.
- При ротации `PORTAL_DB_FERNET_KEY` сохранённые encrypted-пароли не мигрируются автоматически: после смены ключа пароль в админке нужно пересохранить.
