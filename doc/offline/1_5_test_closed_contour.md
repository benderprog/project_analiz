# Offline Docker release for closed-contour testing (1.5_test)

## 1) Build release on an online machine

Fixtures are **not stored in git** by repository policy. Obtain them from approved internal sources first:

- `subdivizion_primer.xlsx`
- `test_svodka_semantic.docx`

Then run from repository root:

```bash
bash scripts/release/build_release.sh 1.5_test --xlsx /abs/path/subdivizion_primer.xlsx --docx /abs/path/test_svodka_semantic.docx
```

Result:

```text
release/1.5_test/
  images/
    web.tar.zst
    postgres.tar.zst
  assets/
    models/paraphrase-multilingual-MiniLM-L12-v2/
  deploy/
    docker-compose.yml
    configs/portal.yml
    fixtures/subdivizion_primer.xlsx
    fixtures/test_svodka_semantic.docx
    scripts/
      load_images.sh
      init_models_volume.sh
      bootstrap_portal_test.sh
  sha256sum.txt
```

## 2) Transfer release into the closed contour

Copy `release/1.5_test/` to the offline server with removable media or approved secure transfer.

On target, verify checksums:

```bash
cd release/1.5_test
sha256sum -c sha256sum.txt
```

## 3) Offline deployment (no internet, no local postgres)

```bash
cd release/1.5_test/deploy
bash ./scripts/load_images.sh
bash ./scripts/init_models_volume.sh

docker compose up -d db_app portal_db_test

docker compose up -d web
bash ./scripts/bootstrap_portal_test.sh
```

> `docker-compose.yml` keeps `./fixtures:/fixtures:ro` mount. In release mode, these fixture files are generated into `deploy/fixtures` by `build_release.sh` from locally supplied paths.

Open application:

- http://<host>:8000/upload/
- http://<host>:8000/admin/

## 4) Verification checklist

1. Log in to `/admin/` with preconfigured admin account.
2. Confirm `db_app`, `portal_db_test`, and `web` containers are healthy.
3. Upload `fixtures/test_svodka_semantic.docx` on `/upload/`.
4. Ensure analysis finishes without network calls and semantic model is used from `/opt/models/paraphrase-multilingual-MiniLM-L12-v2`.
5. Validate portal-backed data is present after `bootstrap_portal_test.sh`.

## 5) Update procedure for patch releases

For patch updates where model and DB images do not change:

1. Rebuild release on online machine.
2. Transfer only `release/<new_version>/images/web.tar.zst` (and updated `sha256sum.txt` if you verify checksums).
3. On offline server, reload web image and restart only `web` service.
4. Keep existing `models_data` volume; model assets are reused.
