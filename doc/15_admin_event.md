# Event admin event type dropdown

## Admin pages

- Add event: `/admin/portaldb/event/add/`
- Edit event: `/admin/portaldb/event/<id>/change/`

## Event type behavior

The `Event.event_type` field is stored as a string in the portal database, but the admin
form renders it as a dropdown. The choices are loaded from
`apps.classifier.models.EventType` (default database) and shown alphabetically.

If you open an existing event whose `event_type` no longer exists in the classifier
reference list, the current value is appended to the dropdown at runtime so the form
still renders and validates.

## Subdivision display and semantic input

The `Find subdivision unit` foreign key uses a human-readable label that includes the
subdivision full name plus its parent PU (e.g., `ПОГК «Васильковое» (пгт Васильковое) ПУ Южное`).
This label is shown both in the dropdown and the selected value on the add/edit pages.

Subdivision `short_name` is reserved for matching and semantic embeddings. When cached
subdivision embeddings are computed, the embedding input text is `short_name` when it
exists, falling back to `name` when it does not.
