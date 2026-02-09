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
