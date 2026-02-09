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
