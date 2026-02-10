# Offline deployment quick guide

## 1) Build and export on a connected machine

```bash
bash scripts/make_release_bundle.sh --version 1.5_test --with-model --with-seed \
  --seed-xlsx /abs/x.xlsx --seed-docx /abs/t.docx --archive
```

The generated bundle includes:

- `compose/docker-compose.offline.yml` configured to run `web` from preloaded image `project_analiz:web-ver-${VERSION}`.
- `compose/.env.docker` with `VERSION=<release-version>`.

## 2) Deploy on offline host

```bash
tar -xzf release_ver_1_5_test.tar.gz
cd release_ver_1_5_test
bash scripts/import_images.sh ./artifacts
bash scripts/offline_up.sh
```

`offline_up.sh` uses compose in runtime-only mode from imported images. No Docker build is performed during startup.

## 3) Important

- Run `scripts/import_images.sh` before `scripts/offline_up.sh`.
- If images are not imported, compose cannot pull/build in a closed contour.
