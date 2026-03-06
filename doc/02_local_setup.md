# Локальный запуск

## 1) Зависимости

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` включает `whitenoise` для корректной обработки static-файлов.

## 2) Переменные окружения

```bash
cp .env.example .env
```

Ключевые группы переменных:

- App DB: `APP_DB_*`
- Portal DB (основной профиль): `PORTAL_DB_*`
- Portal DB test-профиль для админ-кнопки «Тестовая БД»: `PORTAL_DB_TEST_*`
- Семантическая модель: `SEMANTIC_MODEL_NAME`, `SEMANTIC_MODEL_PATH`

Для закрытого контура выставьте offline-флаги:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

Подробная карта переменных и runtime-поведения: [24_runtime_env_and_portal_db.md](./24_runtime_env_and_portal_db.md).

## 3) Redis (для async-анализа)

Запустите Redis локально одним из способов:

```bash
redis-server
# или
make redis-docker
```

## 4) Миграции

```bash
make migrate
python manage.py migrate --database=portal
```

## 5) Запуск приложения

Основной вариант (Django + Celery в одном терминале):

```bash
make dev
```

Альтернативы:

```bash
make web
make worker
```

Параметры запуска можно переопределять:

```bash
make dev PORT=8001
```

Celery worker при `make dev`/`make worker` автоматически ограничивает себя до 80% CPU/RAM, доступных контейнеру/хосту (cgroup-aware).

Доступные страницы:

- `/upload/`
- `/analysis/<uuid>/`
- `/admin/`

## 6) Запуск тестов

Unit-тесты по умолчанию используют SQLite и не требуют Postgres.

```bash
python manage.py test
# или
./scripts/test.sh
# или
make test
```

Подробности: [06_testing.md](./06_testing.md).
