# Quickstart (локально, без Docker)

## 1) Подготовка окружения (Ubuntu)

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip postgresql-client
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Source: requirements.txt

## 2) Настройка env

```bash
cp .env.example .env
```

Для закрытого контура выставьте:

```bash
export OFFLINE_MODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

> Примечание: фактический `OFFLINE_MODE` в коде вычисляется из `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`.

Source: config/settings.py (`OFFLINE_MODE`)  
Source: apps/analysis_app/semantic_model_resolver.py (`is_offline_mode`)

## 3) БД и миграции

Поднимите PostgreSQL (локально или внешне), затем:

```bash
python manage.py migrate
python manage.py migrate --database=portal
```

Source: scripts/bootstrap.sh

## 4) Запуск

```bash
python manage.py runserver 0.0.0.0:8000
```

Откройте:

- приложение: `http://127.0.0.1:8000/upload/`
- админка: `http://127.0.0.1:8000/admin/`

Source: config/urls.py  
Source: docker-compose.yml (`web.healthcheck` использует `/upload/`)

## 5) Проверка тестов

```bash
./scripts/test.sh
```

Source: scripts/test.sh
