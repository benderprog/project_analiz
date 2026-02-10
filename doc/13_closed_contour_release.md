# Closed contour release bundle

This guide describes how to build a single offline release archive on a connected machine and deploy it on a closed contour host with no internet access.

## 1) Build the release bundle on a connected machine

### Prefetch the semantic model

```bash
bash scripts/prefetch_model.sh --model paraphrase-multilingual-MiniLM-L12-v2 \
  --out models/paraphrase-multilingual-MiniLM-L12-v2
```

### Build bundle (model + seed from local absolute paths)

```bash
bash scripts/make_release_bundle.sh --version 1.5_test --with-model --with-seed \
  --seed-xlsx /abs/x.xlsx --seed-docx /abs/t.docx --archive
```

Notes:

- `--with-seed` now requires explicit seed paths (`--seed-xlsx` / `--seed-docx`) or env vars (`FIXTURE_XLSX` / `FIXTURE_DOCX`).
- The bundle always contains `compose/.env.docker` generated from `.env.docker.example` with offline-safe defaults.
- `compose/.env.docker` includes `PORTAL_CONFIG_PATH`, `PORTAL_PROFILE`, `PORTAL_GATEWAY_BACKEND`, `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `SENTENCE_TRANSFORMERS_HOME`, `HF_HOME`, and `SEMANTIC_MODEL_PATH`.
- The bundle contains `compose/portal.yml` copied from `configs/portal.offline.yml`.

## 2) Deploy inside the closed contour

Copy the archive to the offline machine. Then run:

```bash
tar -xzf release_ver_1_5_test.tar.gz
sudo systemctl stop postgresql || true
nmcli networking off
cd release_ver_1_5_test
bash scripts/import_images.sh
bash scripts/offline_up.sh
```

Optional bootstrap after stack is up:

```bash
bash scripts/offline_up.sh --seed --sync --rebuild-embeddings
```

Verify the service:

```bash
curl -f http://127.0.0.1:8000/upload/
```

## 3) Troubleshooting

### Missing compose/.env.docker

`offline_up.sh` expects `compose/.env.docker` and exits with a helpful error if it is absent. Rebuild the bundle with `scripts/make_release_bundle.sh`.

### Missing models directory

Check that the model is present and mounted from bundle folder:

```bash
ls -la models/
```

### Seed files not found

Make sure the seed files exist in the bundle:

```bash
ls -la seed/subdivision_primer.xlsx seed/test_svodka_semantic.docx
```

### Reset volumes

To reset the databases and start fresh:

```bash
docker compose --env-file compose/.env.docker -f compose/docker-compose.yml -f compose/docker-compose.offline.yml down -v
```
