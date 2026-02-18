SHELL := /bin/bash

PY := .venv/bin/python
CELERY := $(PY) -m celery
MANAGE := $(PY) manage.py

HOST ?= 127.0.0.1
PORT ?= 8000
CONCURRENCY ?= 1

.PHONY: test dev web worker migrate redis-docker redis-stop

test:
	./scripts/test.sh

migrate:
	$(MANAGE) migrate

web:
	$(MANAGE) runserver $(HOST):$(PORT)

worker:
	$(CELERY) -A project_analiz worker -l info --concurrency=$(CONCURRENCY)

dev:
	@set -euo pipefail; \
	echo "[dev] starting celery..."; \
	$(CELERY) -A project_analiz worker -l info --concurrency=$(CONCURRENCY) & \
	CELERY_PID=$$!; \
	cleanup() { \
		echo ""; \
		echo "[dev] stopping celery (pid=$$CELERY_PID)"; \
		kill $$CELERY_PID 2>/dev/null || true; \
		wait $$CELERY_PID 2>/dev/null || true; \
	}; \
	trap cleanup EXIT INT TERM; \
	echo "[dev] starting django on $(HOST):$(PORT)..."; \
	$(MANAGE) runserver $(HOST):$(PORT)

redis-docker:
	@docker run --name project_analiz_redis -p 6379:6379 -d redis:7 >/dev/null 2>&1 || true
	@echo "redis started on 127.0.0.1:6379"

redis-stop:
	@docker stop project_analiz_redis >/dev/null 2>&1 || true
	@docker rm project_analiz_redis >/dev/null 2>&1 || true
