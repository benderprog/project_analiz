# Admin: Subdivision list

## Где находится страница
- Django Admin: `http://127.0.0.1:8000/admin/portaldb/subdivision/`

## Какие колонки видны
- `subdivision_id`
- `short_name`
- `name`
- `parent_pu`

## Как искать по short_name
- Используйте строку поиска в списке подразделений.
- Поиск работает по `short_name`, по полному названию (`name`), а также по названиям PU
  (`parent_pu__short_name`, `parent_pu__full_name`).

## Примечание о миграции short_name
- Миграция `portaldb.0002_subdivision_short_name` безопасна для БД, где колонка `short_name`
  уже существует: используется `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
