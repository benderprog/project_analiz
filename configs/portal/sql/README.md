# SQL catalog for portal gateway

This directory contains SQL used by `SQLPortalGateway` (`apps/portaldb/gateway/sql.py`) through mappings in `configs/portal/portal.yml`.

## Runtime mapping

- Config mapping: `profiles.<profile>.sql.queries` in `configs/portal/portal.yml`
- Loader: `apps/portaldb/sql_registry.py`
- Executor: `SQLPortalGateway._fetchall(...)` in `apps/portaldb/gateway/sql.py`

---

## `pu/list_pus.sql`
- Purpose: list all PUs.
- Used by: `SQLPortalGateway.list_pus()`.
- Params: none.
- Tables/columns: `pu(pu_id, short_name, full_name)`.
- Returns: `pu_id`, `short_name`, `full_name`.
- Expected indexes: PK/unique on `pu.pu_id`; optional btree on `short_name` for sorting.
- App output: list of `PuDTO` objects.

## `subdivision/list_subdivisions.sql`
- Purpose: list subdivisions, optional filtering by PU.
- Used by: `SQLPortalGateway.list_subdivisions(pu_id)`.
- Params: `pu_id` (nullable UUID).
- Tables/columns: `subdivision(subdivision_id, name, short_name, parent_pu_id)`.
- Returns: `subdivision_id`, `name`, `short_name`, `parent_pu_id`.
- Expected indexes: PK on `subdivision_id`, index on `parent_pu_id`.
- App output: list of `SubdivisionDTO`.

## `event/search_by_time.sql`
- Purpose: find events in time window.
- Used by: `SQLPortalGateway.search_events_by_time(...)`.
- Params: `from_ts`, `to_ts`, `limit`.
- Tables/columns: `event(event_id, date_detection, find_subdivision_unit_id, event_type, article_of_law)`.
- Filters: `date_detection between from_ts and to_ts`.
- Returns: `event_id`, `date_detection`, `subdivision_id`, `event_type`, `article_of_law`.
- Expected indexes: btree on `event(date_detection)`.
- App output: list of `EventDTO`.

## `event/search_by_subdivision_time.sql`
- Purpose: find events by subdivision + time window.
- Used by: `SQLPortalGateway.search_events_by_subdivision_time(...)`.
- Params: `subdivision_id`, `from_ts`, `to_ts`, `limit`.
- Tables/columns: `event(...)` same as above.
- Filters: `find_subdivision_unit_id = subdivision_id` and time window.
- Returns: same event columns.
- Expected indexes: composite btree `(find_subdivision_unit_id, date_detection)`.
- App output: list of `EventDTO`.

## `event/search_by_offender.sql`
- Purpose: find events by offender surname and DOB/year logic.
- Used by: `SQLPortalGateway.search_events_by_offender(...)` (without subdivision).
- Params: `second_name`, `birth_date` (nullable), `birth_year` (nullable), `limit`.
- Tables/joins: `event e join offenders o on o.event_id = e.event_id`.
- Filters: normalized surname (`ё->е`), optional DOB/year filter.
- Returns: event columns (`event_id`, `date_detection`, `subdivision_id`, `event_type`, `article_of_law`).
- Expected indexes: `offenders(event_id)`, functional index for normalized surname, optional index on `date_of_birth`.
- App output: list of `EventDTO`.

## `event/search_by_offender_subdivision.sql`
- Purpose: same as previous + subdivision restriction.
- Used by: `SQLPortalGateway.search_events_by_offender(...)` (with subdivision).
- Params: `second_name`, `subdivision_id`, `birth_date`, `birth_year`, `limit`.
- Tables/joins: `event` + `offenders`.
- Filters: surname normalization, subdivision filter, DOB/year logic.
- Returns: same event columns.
- Expected indexes: `event(find_subdivision_unit_id)`, offender indexes above.
- App output: list of `EventDTO`.

## `event/event_snapshot.sql`
- Purpose: fetch single event by ID.
- Used by: `SQLPortalGateway.get_event_by_id(event_id)`.
- Params: `event_id`.
- Tables/columns: `event(...)`.
- Returns: single event row with event fields.
- Expected indexes: PK/unique on `event(event_id)`.
- App output: `EventDTO | None`.

## `event/event_offenders.sql`
- Purpose: fetch offenders for given event IDs.
- Used by: `SQLPortalGateway.get_offenders_by_event_ids(event_ids)`.
- Params: `event_ids` (array UUID).
- Tables/columns: `offenders(offender_id, event_id, second_name, first_name, patronymic_name, date_of_birth)`.
- Filters: `event_id = any(event_ids)`.
- Returns: offender columns.
- Expected indexes: btree on `offenders(event_id)`.
- App output: list of `OffenderDTO`.

---

## Adapting for another PROD schema

1. Keep query keys unchanged in `portal.yml` (`list_pus`, `search_by_time`, etc.).
2. Update table/column names inside SQL files for target schema.
3. Preserve returned aliases expected by DTOs:
   - events must return `subdivision_id` alias
   - offenders must return `offender_id`, `event_id`, `second_name`, `first_name`, `patronymic_name`, `date_of_birth`
4. If schema prefix is required, either:
   - hardcode `schema.table` in SQL, or
   - maintain separate profile in `portal.yml` with `sql.base_dir` pointing to schema-specific SQL folder.
5. Activate profile via:
   - env: `PORTAL_PROFILE=<profile>` in compose `.env`, or
   - admin `PortalDbConnectionSettings` + env sync policy.

> Current SQL loader does not apply `{schema}` placeholder substitution automatically; use profile-specific SQL files for safe overrides.
