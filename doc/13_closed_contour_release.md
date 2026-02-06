# Closed contour release bundle

This guide describes how to build a single offline release archive on a connected machine and deploy it on a closed contour host with no internet access.

## 1) Build the release bundle on a connected machine

### Prefetch the semantic model (once per version)

```bash
./scripts/prefetch_model.sh --model paraphrase-multilingual-MiniLM-L12-v2 \
  --out models/paraphrase-multilingual-MiniLM-L12-v2
```

### Build images and create the bundle

```bash
./scripts/make_release_bundle.sh --version 1.1 --with-model --with-seed --archive
```

The command above:

* Builds and exports the docker images into `dist/release_ver_1_1/artifacts/`.
* Bundles compose files, docker init SQL, offline scripts, and docs.
* Copies the cached model into `dist/release_ver_1_1/models/`.
* Copies seed inputs into `dist/release_ver_1_1/seed/`.
* Writes a `manifest.json` with checksums and metadata.
* Produces `dist/release_ver_1_1.tar.gz`.

## 2) Deploy inside the closed contour

Copy the archive to the offline machine. Then run:

```bash
tar -xzf release_ver_1_1.tar.gz
cd release_ver_1_1

cp .env.docker.example .env.docker
# Edit .env.docker if needed.

./scripts/import_images.sh ./artifacts
./scripts/offline_up.sh --seed --sync --rebuild-embeddings
```

Verify the service:

```bash
curl -f http://127.0.0.1:8000/upload/
```

## 3) Troubleshooting

### Database not ready

If migrations fail with connection errors, check the database containers and retry:

```bash
docker compose -f compose/docker-compose.yml -f compose/docker-compose.offline.yml ps
./scripts/offline_up.sh
```

### Missing models directory

If the application reports missing models, ensure the model is present in the bundle and the env var is set:

```bash
ls -la models/
# Optionally set SEMANTIC_MODEL_PATH in .env.docker
```

### Seed files not found

Make sure the seed files exist in the bundle:

```bash
ls -la seed/subdivision_primer.xlsx seed/test_svodka_semantic.docx
```

### Reset volumes

To reset the databases and start fresh:

```bash
docker compose -f compose/docker-compose.yml -f compose/docker-compose.offline.yml down -v
```
