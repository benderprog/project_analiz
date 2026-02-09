# Локальный запуск

## Зависимости
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
`requirements.txt` включает WhiteNoise, необходимый для работы middleware статических файлов при локальном запуске.

## Переменные окружения
Скопируйте `.env.example` в `.env` и настройте параметры БД.

Обратите внимание на настройки семантической модели:
- `SEMANTIC_MODEL_NAME` — имя модели (по умолчанию `paraphrase-multilingual-MiniLM-L12-v2`).
- `SEMANTIC_MODEL_PATH` — путь к локальной копии модели (если задан, загрузка идет только с диска).

## Миграции
```bash
python manage.py migrate
python manage.py migrate --database=portal
```

## Запуск тестов
Unit-тесты по умолчанию используют SQLite и не требуют Postgres.
Подробности — в [документации по тестированию](06_testing.md).

## Запуск
```bash
python manage.py runserver
```

Доступные страницы:
- `/upload/`
- `/analysis/<uuid>/`
- `/admin/` (логин/пароль `admin/admin` создается автоматически)
