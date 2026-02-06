# Архитектура

## Приложения
- `apps/portaldb`: модели портальной БД (Pu, Subdivision, Event, Offender) и admin для тестовых данных.
- `apps/classifier`: классификатор типов событий (нормализованные типы + паттерны и импорт XLSX).
- `apps/analysis_app`: загрузка/анализ docx, хранение результатов, UI `/upload/` и `/analysis/<uuid>/`.
- `apps/users`: автосоздание суперпользователя admin/admin.

## Базы данных
- `default`: Django auth + анализ + классификатор.
- `portal`: портальные таблицы.

Маршрутизация выполнена через `config.db_router.PortalDBRouter`, все модели `portaldb` пишутся в БД `portal`.

## Единая точка доступа к порталу
Все запросы к портальной БД вынесены в `apps/portaldb/repository.py`.

## Классификатор событий
Классификатор хранит типы событий и паттерны отдельно: `EventType` содержит уникальный тип, `EventTypePattern` — один паттерн с привязкой к статье КоАП. Анализ подбирает тип события по совпадению текста с паттернами, выбирая самый длинный матч. 

## Миграции
- Общие: `python manage.py migrate`
- Портал: `python manage.py migrate --database=portal`
