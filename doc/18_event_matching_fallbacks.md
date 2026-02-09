# Event matching fallbacks (2 of 3 rule)

Matching uses staged, bounded fallbacks to ensure an event is found when any two of the three key attributes align.

## Stage order (priority)

1. **Stage A: subdivision + time window**
   * Query by subdivision and a ±Δ minute window around the extracted timestamp.
   * Select the closest event by absolute time delta.

2. **Stage B: subdivision + offenders overlap (≥1)**
   * Query by subdivision only (bounded to the last N events, default 500).
   * Compute offender overlap; select the event with the highest overlap, tie‑breaking by smallest time delta.
   * Accept when overlap ≥ 1. This stage is used when the portal timestamp is wrong.

3. **Stage C: time window + offenders overlap (≥1)**
   * Query by ±Δ minute window only (bounded to the last N events in that window, default 500).
   * Compute offender overlap; select the event with the highest overlap, tie‑breaking by smallest time delta.
   * Accept when overlap ≥ 1. This stage is used when the portal subdivision is wrong.

The first stage that yields a valid event is selected. The result metadata includes:

* `match_method`: `subdivision+time`, `subdivision+offenders`, or `time+offenders`
* `time_mismatch` when Stage B is used
* `subdivision_mismatch` when Stage C is used

## Offender overlap and DOB rule

Offender overlap is counted when at least one extracted offender matches a portal offender by:

* **Name**: surname + first name must match, patronymic is optional.
* **DOB**: exact match, or year‑only (01.01.YYYY) treated as compatible with any date in that year.

DOB comparison treats year‑only values on either side as compatible when the year matches.

## Portal DOB display

In analysis results under “В БД”, the portal offender’s **full DOB** is shown in `dd.mm.yyyy` format when present.
If the portal DOB is missing or the default placeholder (`1900‑01‑01`), it is omitted or shown as “—”.

## Verification

Run:

```bash
python manage.py test
python manage.py runserver
```

Manual checks in the UI:

* **Case 1:** Portal has wrong date, but subdivision + offender overlap → event found (`subdivision+offenders`).
* **Case 2:** Portal has wrong subdivision, but time + offender overlap → event found (`time+offenders`).
* In both cases, offender DOB under “В БД” shows the full portal date when available.
