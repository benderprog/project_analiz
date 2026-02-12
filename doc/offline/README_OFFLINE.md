# Offline release bundle (single archive)

## 1) Build bundle on connected machine

> Important: **do not remove `postgres:15`** when registry access is unreliable.

1. Build web image and tag by release version:

   ```bash
   docker compose build web
   docker tag project_analiz-web:latest project_analiz:web-ver-1.5_test
   ```

2. Create PostgreSQL dumps in `pg_dump -Fc` format with `postgres:15` toolchain (prevents `pg_restore: unsupported version (1.15)` mismatch):

   ```bash
   docker run --rm --network host -v "$PWD:/work" -e PGPASSWORD='<app_pwd>' postgres:15 \
     sh -lc "pg_dump -Fc -h 127.0.0.1 -p 5432 -U app -d app_db -f /work/app_db.dump"

   docker run --rm --network host -v "$PWD:/work" -e PGPASSWORD='<portal_pwd>' postgres:15 \
     sh -lc "pg_dump -Fc -h 127.0.0.1 -p 5432 -U portal -d portal_db_test -f /work/portal_db_test.dump"
   ```

3. (Optional) prefetch semantic model:

   ```bash
   ./scripts/prefetch_model.sh --model paraphrase-multilingual-MiniLM-L12-v2
   ```

4. Build bundle and archive:

   ```bash
   ./scripts/offline/offline.sh bundle \
     --version 1.5_test \
     --db-app-dump /absolute/path/app_db.dump \
     --db-portal-dump /absolute/path/portal_db_test.dump \
     --with-model \
     --archive
   ```

5. Expected outputs:

   - `dist/offline_bundle_1_5_test/`
   - `dist/offline_bundle_1_5_test.tar.gz`
   - `dist/README_OFFLINE_1_5_test.md`

## 2) Deploy in closed contour

```bash
tar -xzf offline_bundle_1_5_test.tar.gz
cd offline_bundle_1_5_test
bash scripts/offline/offline.sh import
bash scripts/offline/offline.sh up
```

Open:

- <http://127.0.0.1:8000/admin>
- <http://127.0.0.1:8000/upload>

Runtime helper commands:

```bash
bash scripts/offline/offline.sh ps
bash scripts/offline/offline.sh logs
bash scripts/offline/offline.sh down
```

## 3) Bundle structure

- `artifacts/` docker image tar files
- `compose/` compose.yml + .env
- `scripts/offline/` offline CLI
- `configs/portal.yml` (и/или `configs/portal/portal.yml`) + `configs/portal/sql/*.sql`
- `db_dumps/app_db.dump`, `db_dumps/portal_db_test.dump`
- `models/` (if built with `--with-model`)
- `doc/` copied documentation set
- `manifest.json` + `checksums.sha256`


## 4) Semantic model in offline mode

Рекомендуемая раскладка локальной модели:

```
./models/paraphrase-multilingual-MiniLM-L12-v2
```

Переменные окружения для web-контейнера:

```bash
SEMANTIC_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2
SEMANTIC_MODEL_PATH=./models/paraphrase-multilingual-MiniLM-L12-v2
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Порядок выбора модели:

1. `SEMANTIC_MODEL_PATH`, если путь существует.
2. `./models/<SEMANTIC_MODEL_NAME>`, если каталог существует.
3. Иначе используется имя модели (`SEMANTIC_MODEL_NAME`) для загрузки из HuggingFace (только для online/development).

Если включен offline-режим (`HF_HUB_OFFLINE=1` или `TRANSFORMERS_OFFLINE=1`) и локальная модель не найдена, приложение завершает загрузку модели с понятной ошибкой без попыток обращения в сеть.
