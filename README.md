# project_analiz

Сервис на Django для анализа документов и сопоставления с данными портала (подразделения, ПУ, события), включая админ-настройку runtime-подключения к portal DB.

## Документация

Единая документация проекта находится в [`/doc`](./doc/README.md).

Рекомендуем начать с:

- [doc/README.md](./doc/README.md)
- [Локальный запуск](./doc/02_local_setup.md)
- [Offline / closed-network](./doc/offline/README.md)


## Локальный async-анализ (Redis + Celery)

Для локальной разработки асинхронного анализа DOCX:

1. Запустите Redis локально:
   - `redis-server`
   - или `docker run -p 6379:6379 redis:7`
2. Запустите Celery worker:
   - `celery -A project_analiz worker -l info`
3. Запустите Django:
   - `python manage.py runserver`

После загрузки DOCX и выбора ПУ анализ выполняется в фоне; страница загрузки покажет текущий статус и таймер до завершения.
