#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash scripts/release/build_release.sh <version> [--xlsx /abs/path/subdivizion_primer.xlsx] [--docx /abs/path/test_svodka_semantic.docx]

You can also provide fixture paths using environment variables:
  FIXTURE_XLSX=/abs/path/subdivizion_primer.xlsx
  FIXTURE_DOCX=/abs/path/test_svodka_semantic.docx

Example:
  bash scripts/release/build_release.sh 1.5_test --xlsx /data/subdivizion_primer.xlsx --docx /data/test_svodka_semantic.docx
USAGE
}

log() {
  printf '[build_release] %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

version="$1"
shift

fixture_xlsx="${FIXTURE_XLSX:-}"
fixture_docx="${FIXTURE_DOCX:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --xlsx)
      fixture_xlsx="${2:-}"
      shift 2
      ;;
    --docx)
      fixture_docx="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$fixture_xlsx" ]]; then
  echo "Missing fixture XLSX. Provide --xlsx or set FIXTURE_XLSX" >&2
  exit 1
fi
if [[ -z "$fixture_docx" ]]; then
  echo "Missing fixture DOCX. Provide --docx or set FIXTURE_DOCX" >&2
  exit 1
fi
if [[ ! -f "$fixture_xlsx" ]]; then
  echo "Fixture XLSX file not found: $fixture_xlsx" >&2
  exit 1
fi
if [[ ! -f "$fixture_docx" ]]; then
  echo "Fixture DOCX file not found: $fixture_docx" >&2
  exit 1
fi

fixture_xlsx="$(cd "$(dirname "$fixture_xlsx")" && pwd)/$(basename "$fixture_xlsx")"
fixture_docx="$(cd "$(dirname "$fixture_docx")" && pwd)/$(basename "$fixture_docx")"

release_root="release/${version}"
images_dir="${release_root}/images"
assets_dir="${release_root}/assets"
deploy_dir="${release_root}/deploy"

require_cmd docker
require_cmd zstd

log "Preparing release directories at ${release_root}"
rm -rf "${release_root}"
mkdir -p "${images_dir}" "${assets_dir}/models" "${deploy_dir}/configs" "${deploy_dir}/fixtures" "${deploy_dir}/scripts"

log "Exporting requirements to docker/requirements.txt"
if command -v poetry >/dev/null 2>&1 && [[ -f pyproject.toml ]]; then
  poetry export -f requirements.txt -o docker/requirements.txt --without-hashes
elif [[ -f requirements.txt ]]; then
  cp requirements.txt docker/requirements.txt
else
  echo "Unable to prepare docker/requirements.txt: install Poetry with pyproject.toml or add requirements.txt at repo root." >&2
  exit 1
fi

model_name="paraphrase-multilingual-MiniLM-L12-v2"
model_dir="${assets_dir}/models/${model_name}"
log "Downloading SentenceTransformer model: ${model_name}"
python - <<PY
from pathlib import Path
from sentence_transformers import SentenceTransformer

model_name = "${model_name}"
model_path = Path("${model_dir}")
model_path.parent.mkdir(parents=True, exist_ok=True)
model = SentenceTransformer(model_name)
model.save(str(model_path))
SentenceTransformer(str(model_path)).encode(["warmup"], convert_to_numpy=True)
print(f"Saved and warmed model at {model_path}")
PY

log "Building web image project_analiz-web:${version}"
docker build -f docker/Dockerfile.web -t "project_analiz-web:${version}" .

log "Pulling postgres:16-alpine"
docker pull postgres:16-alpine

log "Saving compressed docker images"
docker save "project_analiz-web:${version}" | zstd -T0 -19 -o "${images_dir}/web.tar.zst"
docker save postgres:16-alpine | zstd -T0 -19 -o "${images_dir}/postgres.tar.zst"

log "Copying deploy assets"
cp docker/compose.offline.yml "${deploy_dir}/docker-compose.yml"
cp configs/portal.offline.yml "${deploy_dir}/configs/portal.yml"
cp "$fixture_xlsx" "${deploy_dir}/fixtures/subdivizion_primer.xlsx"
cp "$fixture_docx" "${deploy_dir}/fixtures/test_svodka_semantic.docx"

cat > "${deploy_dir}/scripts/load_images.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
images_dir="${script_dir}/../../images"

for archive in "${images_dir}"/*.tar.zst; do
  echo "Loading ${archive}"
  zstd -dc "${archive}" | docker load
done
SCRIPT

cat > "${deploy_dir}/scripts/init_models_volume.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
assets_models="${script_dir}/../../assets/models"

docker volume create models_data >/dev/null

docker run --rm \
  -v models_data:/models \
  -v "${assets_models}":/assets:ro \
  alpine:3.20 \
  sh -c 'cp -a /assets/. /models/'

echo "Model files copied into docker volume models_data"
SCRIPT

cat > "${deploy_dir}/scripts/bootstrap_portal_test.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

docker compose run --rm web python manage.py migrate --database=portal
docker compose run --rm web python manage.py seed_portal --reset --xlsx /fixtures/subdivizion_primer.xlsx --docx /fixtures/test_svodka_semantic.docx
docker compose run --rm web python manage.py sync_pu_cache
docker compose run --rm web python manage.py sync_subdivision_cache
SCRIPT

chmod +x "${deploy_dir}/scripts/load_images.sh" "${deploy_dir}/scripts/init_models_volume.sh" "${deploy_dir}/scripts/bootstrap_portal_test.sh"

log "Generating checksums"
(
  cd "${release_root}"
  find . -type f ! -name sha256sum.txt -print0 | sort -z | xargs -0 sha256sum > sha256sum.txt
)

log "Release package ready: ${release_root}"
