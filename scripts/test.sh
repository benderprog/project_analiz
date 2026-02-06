#!/usr/bin/env bash
set -euo pipefail

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export DJANGO_SETTINGS_MODULE="config.settings_test"

python manage.py test
