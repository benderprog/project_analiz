# Closed contour runbook (1.5_test)

This runbook assumes Docker is installed on both the online build host and the offline target host.

## 1) Online: build image and prepare local assets

From project root:

```bash
docker build -f docker/Dockerfile.web -t project_analiz:web-ver-1.5_test .
docker pull postgres:15
```

Optional model prefetch (required when `--with-model` is used):

```bash
bash scripts/prefetch_model.sh
```

## 2) Online: build one offline bundle

```bash
./scripts/offline/offline.sh bundle \
  --version 1.5_test \
  --with-model \
  --seed-xlsx /ABS/PATH/subdivision_primer.xlsx \
  --seed-docx /ABS/PATH/test_svodka_semantic.docx \
  --archive
```

Bundle output:

- `dist/offline_bundle_1_5_test/artifacts` (docker image archives)
- `dist/offline_bundle_1_5_test/compose` (`compose.yml`, `.env`, `portal.yml`, optional `models/`, optional `seed/`)
- `dist/offline_bundle_1_5_test/models` (optional copy of local models)
- `dist/offline_bundle_1_5_test/seed` (optional seed fixtures)
- `dist/offline_bundle_1_5_test/doc` (this runbook)
- `dist/offline_bundle_1_5_test/manifest.json` (sha256 list)

Copy the whole `dist/offline_bundle_1_5_test/` directory (or the `.tar.gz` archive) to the offline host.

## 3) Offline host: before startup

1. Disable internet/network access.
2. Stop local postgres services that can occupy `5432`.

## 4) Offline host: import images

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh import
```

## 5) Offline host: start stack (db + one-shot migrations + web)

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh up
```

## 6) Offline host: optional portal seed

Only if bundle includes `seed/` files:

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh seed
```

## 7) Verify app

Open in browser:

- `http://localhost:8000/admin/`
- `http://localhost:8000/upload/`

## 8) Logs and shutdown

```bash
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh logs
OFFLINE_BUNDLE_DIR=/path/to/offline_bundle_1_5_test ./scripts/offline/offline.sh down
```
