#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate
python manage.py migrate --database=portal
python manage.py collectstatic --noinput

if [[ "${WARMUP_ON_START:-0}" == "1" ]]; then
  python manage.py warmup_models
fi

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
