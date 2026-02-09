# Offender admin display and ordering

## Admin pages

- Offender list: `/admin/portaldb/offender/`
- Add event: `/admin/portaldb/event/add/`
- Edit event: `/admin/portaldb/event/<id>/change/`

## Offender list view

The offender list page displays the name parts in surname-first order and includes the
patronymic column. The visible columns are:

1. `second_name` (Фамилия)
2. `first_name` (Имя)
3. `patronymic_name` (Отчество)
4. `date_of_birth` (Дата рождения)
5. `event`

The default ordering and search fields also follow the surname → name → patronymic
sequence.

## Event admin inline

The offender inline on the event add/edit pages enforces the same field order:
`second_name`, `first_name`, `patronymic_name`, `date_of_birth`.

## How to verify

```bash
python manage.py test tests.test_offender_admin_display
python manage.py runserver
```

1. Open `/admin/portaldb/offender/` and confirm the columns read:
   Фамилия, Имя, Отчество, ДР, Event.
2. Open `/admin/portaldb/event/add/` and confirm the offender inline fields are ordered:
   Фамилия, Имя, Отчество, ДР.
