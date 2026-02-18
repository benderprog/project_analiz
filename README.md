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
- `make worker` — только Celery (`CONCURRENCY`)

Параметры можно переопределять при запуске, например:

- `make dev PORT=8001 CONCURRENCY=2`

`make dev` запускает Celery worker в фоне и корректно останавливает его при остановке Django (`Ctrl+C`).

После загрузки DOCX и выбора ПУ анализ выполняется в фоне; страница загрузки покажет текущий статус и таймер до завершения.
