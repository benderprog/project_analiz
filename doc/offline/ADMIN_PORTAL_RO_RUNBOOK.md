# Администраторский runbook: закрытый контур + PROD `portal_db` (RO) + переопределение SQL

## 1. Назначение и область применения

Документ описывает эксплуатационный сценарий для администратора в закрытом контуре, когда:

- приложение `project_analiz` разворачивается из offline-bundle;
- рабочая БД приложения (`app_db`) остаётся локальной в docker-compose;
- портал подключается к удалённой production БД `portal_db` в режиме **только чтение** (`PORTAL_MODE=remote`);
- требуется безопасно адаптировать SQL-запросы под реальную схему PROD портала.

Документ ориентирован на эксплуатацию без доступа в интернет (`apt`/внешние репозитории недоступны).

---

## 2. Предварительные требования

Минимально необходимо:

1. Docker Engine + Docker Compose plugin на хосте закрытого контура.
2. Развёрнутый offline bundle (распакованный каталог с `compose/`, `configs/`, `scripts/offline/`).
3. Сетевая достижимость до удалённого хоста `portal_db` с машины/контейнера `web`.
4. Учётная запись БД для портала с правами **SELECT-only** (read-only).

> В этом сценарии любые DDL/DML для `portal_db` запрещены.

---

## 3. Где настраивается окружение

Основной env-файл для compose: `compose/.env`.

Ключевые переменные:

- `PORTAL_MODE` — режим портала (`local` или `remote`).
- `PORTAL_PROFILE` — активный профиль SQL из `configs/portal/portal.yml`.
- `PORTAL_DB_HOST`, `PORTAL_DB_PORT`, `PORTAL_DB_NAME`, `PORTAL_DB_USER`, `PORTAL_DB_PASSWORD` — доступ к `portal_db`.
- `PORTAL_GATEWAY_BACKEND` — backend gateway (обычно `sql`).

Рекомендуемый фрагмент для PROD RO:

```env
PORTAL_MODE=remote
PORTAL_PROFILE=dev
PORTAL_GATEWAY_BACKEND=sql

PORTAL_DB_HOST=<prod-portal-db-host>
PORTAL_DB_PORT=5432
PORTAL_DB_NAME=portal_db
PORTAL_DB_USER=<ro_user>
PORTAL_DB_PASSWORD=<ro_password>
```

---

## 4. Развёртывание offline bundle в закрытом контуре

Базовый жизненный цикл:

```bash
# 1) импорт образов
bash scripts/offline/offline.sh import

# 2) запуск стека
bash scripts/offline/offline.sh up

# 3) штатная остановка/старт
bash scripts/offline/offline.sh stop
bash scripts/offline/offline.sh start
```

Примечания:

- Для первичного старта используется `up`.
- Для штатной эксплуатации без переинициализации БД — `stop -> start`.

### 4.1. Режим `PORTAL_MODE=remote`

В режиме `remote` удалённая `portal_db` не должна изменяться. Защитное поведение:

- контейнер `portal_db_test` **не запускается**;
- шаг `restore_portal` **не выполняется**;
- шаг `migrate_portal` **не выполняется**.

Это исключает случайные записи/миграции в production-портал.

---

## 5. Безопасные smoke-check после запуска

### 5.1. Проверка UI

1. Открыть `http://<host>:8000/upload`.
2. Загрузить небольшой DOCX.
3. Убедиться, что документ обрабатывается и в результатах появляются события/карточки.

Если в выдаче пусто (`candidates=0`) — см. раздел troubleshooting ниже.

### 5.2. Проверка сети до `portal_db` без `psql`

В закрытом контуре используйте bash TCP probe из контейнера `web`:

```bash
docker compose -f compose/compose.yml --env-file compose/.env exec -T web \
  bash -lc 'echo > /dev/tcp/${PORTAL_DB_HOST}/${PORTAL_DB_PORT} && echo OK || echo FAIL'
```

`OK` означает, что TCP-порт достижим. Это базовая проверка сети/маршрута без дополнительных утилит.

---

## 6. Обновление bundle (upgrade) в закрытом контуре

Рекомендуемая схема:

1. Остановить текущий стек:

```bash
bash scripts/offline/offline.sh stop
```

2. Заменить каталог bundle на новый (или распаковать новую версию рядом).
3. Проверить/перенести актуальный `compose/.env`.
4. Запустить:

```bash
bash scripts/offline/offline.sh start
# либо up, если нужен полный сценарий запуска
```

### 6.1. Замечание по именам volume

Стабильность имён Docker volume важна для сохранения данных между релизами. При смене имени проекта/compose-файла возможно создание новых volume и «потеря» прежнего состояния (данные останутся в старых volume, но не будут подмонтированы автоматически).

---

## 7. Как переопределяется SQL (override / replacement)

### 7.1. Откуда берётся маппинг SQL

Авторитетная конфигурация:

- `configs/portal/portal.yml`
- `profiles.<name>.sql.base_dir`
- `profiles.<name>.sql.queries.<key> -> <relative_sql_path>`

Текущий маппинг ключей:

- `list_pus` → `pu/list_pus.sql`
- `list_subdivisions` → `subdivision/list_subdivisions.sql`
- `search_by_subdivision_time` → `event/search_by_subdivision_time.sql`
- `search_by_time` → `event/search_by_time.sql`
- `event_offenders` → `event/event_offenders.sql`
- `search_by_offender` → `event/search_by_offender.sql`
- `search_by_offender_subdivision` → `event/search_by_offender_subdivision.sql`
- `event_snapshot` → `event/event_snapshot.sql`

### 7.2. Стратегия 1 (рекомендуется): новый профиль

Безопасный путь для PROD:

1. Скопировать профиль `dev` в новый, например `prod_ro`, в `configs/portal/portal.yml`.
2. Для `prod_ro` изменить `sql.base_dir` и/или `queries` на ваши SQL-файлы.
3. В `compose/.env` переключить `PORTAL_PROFILE=prod_ro`.
4. Перезапустить сервисы:

```bash
bash scripts/offline/offline.sh stop
bash scripts/offline/offline.sh start
```

Плюс: легко откатиться обратно на `dev` одной переменной.

### 7.3. Стратегия 2 (быстро, менее безопасно): замена SQL «на месте»

1. Сделать backup исходников SQL в `configs/portal/sql/**`.
2. Редактировать файлы по тем же путям.
3. Перезапустить стек (`stop -> start`).

Минус: выше риск неявной несовместимости при обновлениях.

### 7.4. Жёсткие контрактные правила

При любом override обязательно:

1. **Не менять имена параметров** вида `%(...)s`.
2. **Не ломать ожидаемые alias колонок** (например, `... as subdivision_id`).
3. Сохранять типовую семантику фильтров (период, лимит, логика DOB), если не меняете и прикладной код.

### 7.5. Безопасный restart после изменения SQL

```bash
bash scripts/offline/offline.sh stop
bash scripts/offline/offline.sh start
```

### 7.6. Откат

1. Держать копии оригинальных SQL (`*.bak` или отдельный каталог).
2. Вернуть исходные файлы/профиль.
3. Выполнить `stop -> start`.

---

## 8. Каталог возможностей запросов (по текущим SQL)

| Key | SQL file path | Назначение | Параметры | Возвращает (колонки) | Примечания |
|---|---|---|---|---|---|
| `list_pus` | `configs/portal/sql/pu/list_pus.sql` | Справочник ПУ | нет | `pu_id`, `short_name`, `full_name` | Сортировка по `short_name`, `full_name`. |
| `list_subdivisions` | `configs/portal/sql/subdivision/list_subdivisions.sql` | Список подразделений (возможно по ПУ) | `pu_id` (nullable) | `subdivision_id`, `name`, `short_name`, `parent_pu_id` | Если `pu_id is null` — возвращаются все. |
| `search_by_subdivision_time` | `configs/portal/sql/event/search_by_subdivision_time.sql` | Поиск событий по подразделению и периоду | `subdivision_id`, `from_ts`, `to_ts`, `limit` | `event_id`, `date_detection`, `subdivision_id`, `event_type`, `article_of_law` | `between ...::timestamptz`, сортировка по `date_detection desc`, ограничение `limit`. |
| `search_by_time` | `configs/portal/sql/event/search_by_time.sql` | Поиск событий только по периоду | `from_ts`, `to_ts`, `limit` | `event_id`, `date_detection`, `subdivision_id`, `event_type`, `article_of_law` | Та же оконная логика времени и `limit`. |
| `search_by_offender` | `configs/portal/sql/event/search_by_offender.sql` | Поиск событий по нарушителю | `second_name`, `birth_date` (nullable), `birth_year` (nullable), `limit` | `event_id`, `date_detection`, `subdivision_id`, `event_type`, `article_of_law` | Нормализация фамилии `ё→е` (`replace(lower(...), 'ё','е')`), DOB-логика: точная дата / год / без фильтра DOB. |
| `search_by_offender_subdivision` | `configs/portal/sql/event/search_by_offender_subdivision.sql` | Поиск по нарушителю в конкретном подразделении | `second_name`, `subdivision_id`, `birth_date`, `birth_year`, `limit` | `event_id`, `date_detection`, `subdivision_id`, `event_type`, `article_of_law` | Как выше + фильтр по `subdivision_id`; `select distinct`. |
| `event_snapshot` | `configs/portal/sql/event/event_snapshot.sql` | Карточка события по ID | `event_id` | `event_id`, `date_detection`, `subdivision_id`, `event_type`, `article_of_law` | Одиночный снимок без `limit`. |
| `event_offenders` | `configs/portal/sql/event/event_offenders.sql` | Нарушители для набора событий | `event_ids` | `offender_id`, `event_id`, `second_name`, `first_name`, `patronymic_name`, `date_of_birth` | Фильтр `where o.event_id = any(%(event_ids)s)`, сортировка по `event_id`, `offender_id`. |

---

## 9. Troubleshooting

### 9.1. Ошибки подключения к `portal_db`

Проверки:

1. Значения в `compose/.env`: host/port/db/user/password.
2. Сетевая достижимость `/dev/tcp` из контейнера `web`.
3. Правила межсетевого экрана и маршрутизация.
4. Ограничения на стороне Postgres (`pg_hba.conf`, whitelist).

### 9.2. В логах/результатах `candidates=0`

Возможные причины:

- слишком узкие фильтры (время/подразделение/ФИО/дата рождения);
- несовпадение SQL со схемой PROD (неверные поля/joins);
- сломан контракт alias/параметров после override;
- данные в выбранном окне времени отсутствуют.

Практика диагностики в закрытом контуре (без `apt`/интернета):

- просмотр env и compose-конфигов: `sed`, `cat`;
- проверка SQL-мэппинга и запросов: `find`, `grep`;
- проверка статуса/логов контейнеров: `docker compose ... ps`, `docker compose ... logs`.

### 9.3. Производительность

- Уменьшайте `limit` для первичной диагностики.
- Сужайте временное окно (`from_ts`/`to_ts`).
- Для тяжёлых `search_by_offender*` согласуйте индексы с DBA production портала.

---

## 10. Короткий operational checklist

1. Выставить `PORTAL_MODE=remote` и RO-учётку в `compose/.env`.
2. Проверить TCP-доступ до `PORTAL_DB_HOST:PORTAL_DB_PORT` из `web`.
3. Выполнить `offline.sh up` (или `stop -> start` после правок).
4. Проверить UI на небольшом DOCX.
5. При необходимости адаптировать SQL через профиль `prod_ro`.
6. После изменения SQL: `stop -> start`, проверить логи и результат.
