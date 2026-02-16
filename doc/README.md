# project_analiz documentation (`/doc`)

`/doc` is the single source of truth for project documentation.

## What this project is

`project_analiz` is a Django service for document analysis (DOCX upload/processing) with matching against portal data (subdivisions, polling stations, events/offenders).

## Quick start

- Local setup and run: [02_local_setup.md](./02_local_setup.md)
- Test execution: [06_testing.md](./06_testing.md)
- Smoke test for upload flow: [08_smoke_test_upload.md](./08_smoke_test_upload.md)

## Runtime configuration

- Environment variables and Portal DB runtime configuration (including TEST/PROD): [24_runtime_env_and_portal_db.md](./24_runtime_env_and_portal_db.md)
- Portal YAML and SQL configuration: [22_portal_config.md](./22_portal_config.md)
- Portal gateway modes (`orm` / `sql`): [23_portal_gateway.md](./23_portal_gateway.md)

## Analysis flow guides

- Event matching fallback behavior: [18_event_matching_fallbacks.md](./18_event_matching_fallbacks.md)
- Offender extraction: [19_offender_extraction.md](./19_offender_extraction.md)
- Semantic subdivision matching: [10_subdivision_semantic.md](./10_subdivision_semantic.md)

## Offline / closed-network operation

- Offline index: [offline/README.md](./offline/README.md)
- Main closed-network bundle guide: [offline/README_OFFLINE.md](./offline/README_OFFLINE.md)
- Full dump-first runbook: [16_offline_dump_first_bundle.md](./16_offline_dump_first_bundle.md)
- Remote portal read-only mode: [offline/README_REMOTE_PORTAL_RO.md](./offline/README_REMOTE_PORTAL_RO.md)

## Troubleshooting and security

- Common errors and security notes: [25_troubleshooting_and_security.md](./25_troubleshooting_and_security.md)

## Documentation consolidation mapping (`/docs` -> `/doc`)

- `docs/quickstart_local.md` -> merged into [02_local_setup.md](./02_local_setup.md)
- `docs/env.md` + `docs/portal_db_connection.md` + `docs/offline_models.md` -> merged into [24_runtime_env_and_portal_db.md](./24_runtime_env_and_portal_db.md)
- `docs/docker.md` -> merged into [offline/README_OFFLINE.md](./offline/README_OFFLINE.md) and [16_offline_dump_first_bundle.md](./16_offline_dump_first_bundle.md)
- `docs/troubleshooting.md` + `docs/security_notes.md` -> merged into [25_troubleshooting_and_security.md](./25_troubleshooting_and_security.md)
- `docs/audit.md` -> content captured by this index and mapping section.
