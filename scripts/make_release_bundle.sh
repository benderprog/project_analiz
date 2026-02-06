#!/usr/bin/env bash
set -euo pipefail

# Build a closed-contour release bundle with images, compose files, scripts, and docs.

usage() {
  cat <<'USAGE'
Usage: ./scripts/make_release_bundle.sh --version 1.1 [--with-model] [--with-seed] [--archive] [--include-env]
USAGE
}

log() {
  printf "[make_release_bundle] %s\n" "$1"
}

version=""
with_model="false"
with_seed="false"
archive="false"
include_env="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      version="$2"
      shift 2
      ;;
    --with-model)
      with_model="true"
      shift
      ;;
    --with-seed)
      with_seed="true"
      shift
      ;;
    --archive)
      archive="true"
      shift
      ;;
    --include-env)
      include_env="true"
      shift
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

if [[ -z "$version" ]]; then
  echo "--version is required." >&2
  usage
  exit 1
fi

version_slug="${version//./_}"
base_dir="dist/release_ver_${version_slug}"

model_name="${SEMANTIC_MODEL_NAME:-}"
if [[ -z "$model_name" && -f .env.docker ]]; then
  model_name="$(grep -E '^SEMANTIC_MODEL_NAME=' .env.docker | head -n1 | cut -d= -f2-)"
fi
model_name="${model_name:-paraphrase-multilingual-MiniLM-L12-v2}"

log "Preparing release bundle at ${base_dir}"
mkdir -p "${base_dir}/artifacts" "${base_dir}/compose" "${base_dir}/docker" "${base_dir}/scripts" "${base_dir}/doc"

log "Exporting docker images"
./scripts/export_images.sh --version "$version" --output "${base_dir}/artifacts"

log "Copying compose files"
cp docker-compose.yml docker-compose.offline.yml docker-compose.with-model.yml "${base_dir}/compose/"

log "Copying docker init SQL"
if [[ -d docker/postgres/init ]]; then
  mkdir -p "${base_dir}/docker/postgres"
  cp -R docker/postgres/init "${base_dir}/docker/postgres/"
fi

log "Copying offline scripts"
cp scripts/import_images.sh scripts/offline_up.sh "${base_dir}/scripts/"

log "Copying offline docs"
cp doc/11_docker_offline.md doc/07_portal_seed.md doc/13_closed_contour_release.md "${base_dir}/doc/"
cp doc/13_closed_contour_release.md "${base_dir}/README_OFFLINE.md"

log "Copying environment templates"
cp .env.docker.example "${base_dir}/.env.docker.example"
if [[ "$include_env" == "true" ]]; then
  log "Including .env.docker (explicit request)"
  cp .env.docker "${base_dir}/.env.docker"
fi

if [[ "$with_model" == "true" ]]; then
  if [[ ! -d "models/${model_name}" ]]; then
    echo "Model directory models/${model_name} not found. Run scripts/prefetch_model.sh first." >&2
    exit 1
  fi
  log "Copying model ${model_name}"
  mkdir -p "${base_dir}/models"
  cp -R "models/${model_name}" "${base_dir}/models/"
fi

if [[ "$with_seed" == "true" ]]; then
  seed_xlsx="subdivision_primer.xlsx"
  seed_docx="test_svodka_semantic.docx"
  if [[ ! -f "$seed_xlsx" || ! -f "$seed_docx" ]]; then
    echo "Seed inputs not found at repository root." >&2
    exit 1
  fi
  log "Copying seed inputs"
  mkdir -p "${base_dir}/seed"
  cp "$seed_xlsx" "$seed_docx" "${base_dir}/seed/"
fi

log "Generating manifest.json"
python - <<PY
import datetime
import hashlib
import json
import os
from pathlib import Path

base_dir = Path("${base_dir}")
manifest_path = base_dir / "manifest.json"

files = []
for path in sorted(base_dir.rglob('*')):
    if path.is_dir():
        continue
    if path == manifest_path:
        continue
    rel_path = path.relative_to(base_dir).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    files.append({"path": rel_path, "sha256": digest})

payload = {
    "version": "${version}",
    "git_commit": os.popen('git rev-parse HEAD').read().strip(),
    "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    "model_name": "${model_name}" if "${with_model}" == "true" else None,
    "files": files,
}

manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(f"Wrote {manifest_path}")
PY

if [[ "$archive" == "true" ]]; then
  archive_path="dist/release_ver_${version_slug}.tar.gz"
  log "Creating archive ${archive_path}"
  tar -czf "$archive_path" -C dist "release_ver_${version_slug}"
  log "Archive ready: ${archive_path}"
fi

log "Release bundle created at ${base_dir}"
