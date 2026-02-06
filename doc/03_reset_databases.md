# Сброс баз данных

## Вариант 1: удалить базы полностью
```sql
DROP DATABASE app_db;
DROP DATABASE portal_db;
```
Создайте их заново и примените миграции:
```bash
python manage.py migrate
python manage.py migrate --database=portal
```

## Вариант 2: очистка таблиц
В Django можно использовать `flush` для каждой базы:
```bash
python manage.py flush
python manage.py flush --database=portal
```
