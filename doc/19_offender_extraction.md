# Offender extraction validation

The offender extractor uses Natasha and lightweight regex helpers, then applies a post-extraction
validator to prevent non-name spans from being treated as people. The validator drops candidates
that look like abbreviations or actions instead of names.

## Validation rules (summary)

* The candidate must contain **at least two tokens** that look like name parts:
  * TitleCase words (e.g., "Смирнова"), or
  * initials ("А." or "А").
* Tokens from the stoplist (e.g., "рф", "мвд", "фсб", "г", "пгт", "районе", "кпп") are rejected.
* The first token **cannot** be an all-caps abbreviation unless it is followed by a TitleCase token.
* Morphology check (pymorphy2): at least one TitleCase token must be tagged as **Name/Surn/Patr**.
* Candidates where most tokens are verbs/adverbs (e.g., "осуществляла") are rejected.

## Debug metadata

Each extracted offender includes a `source` field (`natasha`, `regex_initials`, `regex_context`)
to make false positives easier to trace.

## Offender matching (post-extraction)

After selecting the portal event, offenders are compared in two steps:

1. **Exact match** — strict name key in `Фамилия Имя Отчество` order (normalized
   `second_name + first_name + patronymic`). Portal offender fields are reordered into
   surname-first before comparison.
   DOB rules:
   - Full DOBs must match exactly.
   - A surrogate year date `01.01.YYYY` matches a full DOB of the same year.
2. **Name match, DOB mismatch** — for remaining offenders with the same name key where
   **both DOBs are full and different**, the pair is recorded as `dob_mismatch` and is not
   counted as matched.

Remaining offenders are categorized as:

- `missing_in_portal` — present in the svodka but missing in the portal DB.
- `missing_in_svodka` — present in the portal DB but missing in the svodka.

The UI report shows offender names in surname-first order (`Фамилия Имя Отчество`),
with full portal DOBs rendered as `dd.mm.yyyy` when available.

- `Совпало нарушителей: X из Y` (Y = portal total),
- `ФИО совпало, но ДР отличается` (with DOB from svodka as-is, DOB from portal as full date),
- `В сводке есть, в БД нет`,
- `В БД есть, в сводке нет`.
