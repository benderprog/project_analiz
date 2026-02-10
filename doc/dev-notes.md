# Dev notes

- Hotfix: restored `_hydrate_events_with_offenders` in `analysis_app.services` and switched candidate flows to use returned hydrated structures (`HydratedEvent`) to avoid mutating frozen portal DTOs.
