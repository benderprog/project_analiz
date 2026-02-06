# Архитектура

## Приложения
- `apps/portaldb`: модели портальной БД (Pu, Subdivision, Event, Offender) и admin для тестовых данных.
- `apps/classifier`: классификатор типов событий (модель + импорт XLSX).
- `apps/analysis_app`: загрузка/анализ docx, хранение результатов, UI `/upload/` и `/analysis/<uuid>/`.
- `apps/users`: автосоздание суперпользователя admin/admin.

## Базы данных
- `default`: Django auth + анализ + классификатор.
- `portal`: портальные таблицы.

Маршрутизация выполнена через `config.db_router.PortalDBRouter`, все модели `portaldb` пишутся в БД `portal`.

## Единая точка доступа к порталу
Все запросы к портальной БД вынесены в `apps/portaldb/repository.py`.

## Миграции
- Общие: `python manage.py migrate`
- Портал: `python manage.py migrate --database=portal`
