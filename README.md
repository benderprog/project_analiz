# project_analiz

Сервис на Django для анализа документов и сопоставления с данными портала (подразделения, ПУ, события), включая админ-настройку runtime-подключения к portal DB.

## Документация

Единая документация проекта находится в [`/doc`](./doc/README.md).

Рекомендуем начать с:

- [doc/README.md](./doc/README.md)
- [Локальный запуск](./doc/02_local_setup.md)
- [Offline / closed-network](./doc/offline/README.md)


## Локальный async-анализ (Redis + Celery)

Для локальной разработки используйте команды Makefile (они запускают Python из `.venv`):

1. Поднимите Redis:
   - хостовый: `redis-server`
   - или в Docker: `make redis-docker`
2. Выполните миграции:
   - `make migrate`
3. Запустите Django + Celery одной командой:
   - `make dev`

Альтернативно можно запускать по отдельности:

- `make web` — только Django (`HOST`/`PORT`)
- `make worker` — только Celery (авто-лимиты: 80% CPU/RAM контейнера, cgroup-aware)

Параметры можно переопределять при запуске, например:

- `make dev PORT=8001`

`make dev` запускает Celery worker в фоне и корректно останавливает его при остановке Django (`Ctrl+C`).

Worker auto-limits:
- воркер автоматически вычисляет `concurrency` и `--max-memory-per-child` из 80% доступных контейнеру CPU/RAM (с учетом cgroup-лимитов).
- администратор может ограничить контейнер через Docker/Compose (`cpus`, `mem_limit`) — воркер возьмет 80% уже от этих лимитов.
- дополнительные safety/env-параметры: `WORKER_MAX_CONCURRENCY` (default 8), `WORKER_MEMORY_SAFETY_MARGIN_KB` (default 200000), `WORKER_MAX_TASKS_PER_CHILD` (default 50), `WORKER_SOFT_TIME_LIMIT` (default 840), `WORKER_TIME_LIMIT` (default 900).

После загрузки DOCX и выбора ПУ анализ выполняется в фоне; страница загрузки покажет текущий статус и таймер до завершения.
