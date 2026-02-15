# CI: запуск тестов в GitHub Actions

## Что делает workflow
Workflow `.github/workflows/tests.yml` запускается на push и pull request в ветку `dev` и выполняет:

- поднимает сервис PostgreSQL 16;
- создает роли `app` и `portal` с правом `CREATEDB` (нужно для создания Django test DB);
- создает базы `app_db` и `portal_db_test` для локальной логики приложения (продовое имя — `portal_db`);
- выполняет миграции для основной и `portal` БД;
- запускает `python manage.py test`.

В CI выставлен `SKIP_SEMANTIC_MODEL=1`, чтобы тесты не скачивали тяжелые модели
`sentence-transformers` во время импорта модулей.

## Как повторить локально

1. Убедитесь, что зависимости установлены:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Подготовьте роли и базы (однократно):

```bash
psql -h 127.0.0.1 -U postgres -d postgres <<'SQL'
CREATE ROLE app LOGIN PASSWORD 'app' CREATEDB;
CREATE ROLE portal LOGIN PASSWORD 'portal' CREATEDB;
CREATE DATABASE app_db OWNER app;
CREATE DATABASE portal_db_test OWNER portal;
-- для PROD по соглашению используется имя portal_db
SQL
```

3. Запустите миграции и тесты:

```bash
export DJANGO_SECRET_KEY=ci-secret
export DJANGO_ALLOWED_HOSTS='*'
export APP_DB_HOST=127.0.0.1
export PORTAL_DB_HOST=127.0.0.1
export SKIP_SEMANTIC_MODEL=1

python manage.py migrate
python manage.py migrate --database=portal
python manage.py test
```

## Почему нужен CREATEDB
Django создает временные тестовые базы при запуске `manage.py test`. Для этого
роли `app` и `portal` должны иметь право `CREATEDB`, иначе тесты падают с ошибкой
доступа при попытке создать test DB.
