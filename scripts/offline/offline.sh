#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=scripts/offline/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

usage() {
  cat <<'USAGE'
Offline bundle / runtime helper

Usage:
  ./scripts/offline/offline.sh bundle --version 1.5_test [--with-model] [--seed-xlsx PATH --seed-docx PATH] [--archive]
  ./scripts/offline/offline.sh import
  ./scripts/offline/offline.sh up
  ./scripts/offline/offline.sh seed
  ./scripts/offline/offline.sh logs
  ./scripts/offline/offline.sh down

Environment:
  OFFLINE_BUNDLE_DIR  Bundle path (default: dist/offline_bundle_<version>)
USAGE
}

sanitize_version() {
  echo "$1" | tr '.-' '__'
}

default_bundle_dir_for_version() {
  local version="$1"
  local safe
  safe="$(sanitize_version "$version")"
  echo "${REPO_ROOT}/dist/offline_bundle_${safe}"
}

bundle_cmd() {
  require_cmd docker

  local version=""
  local with_model="0"
  local seed_xlsx=""
  local seed_docx=""
  local make_archive="0"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version)
        version="${2:-}"
        shift 2
        ;;
      --with-model)
        with_model="1"
        shift
        ;;
      --seed-xlsx)
        seed_xlsx="${2:-}"
        shift 2
        ;;
      --seed-docx)
        seed_docx="${2:-}"
        shift 2
        ;;
      --archive)
        make_archive="1"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown bundle argument: $1"
        ;;
    esac
  done

  [[ -n "${version}" ]] || die "bundle requires --version"

  if [[ -n "${seed_xlsx}" || -n "${seed_docx}" ]]; then
    [[ -n "${seed_xlsx}" && -n "${seed_docx}" ]] || die "Provide both --seed-xlsx and --seed-docx together"
    [[ -f "${seed_xlsx}" ]] || die "Seed XLSX not found: ${seed_xlsx}"
    [[ -f "${seed_docx}" ]] || die "Seed DOCX not found: ${seed_docx}"
  fi

  local bundle_dir
  bundle_dir="${OFFLINE_BUNDLE_DIR:-$(default_bundle_dir_for_version "$version")}"
  local compose_dir="${bundle_dir}/compose"
  local artifacts_dir="${bundle_dir}/artifacts"
  local models_dir="${bundle_dir}/models"
  local seed_dir="${bundle_dir}/seed"
  local doc_dir="${bundle_dir}/doc"

  log "Preparing bundle at ${bundle_dir}"
  rm -rf "${bundle_dir}"
  mkdir -p "${compose_dir}" "${artifacts_dir}" "${doc_dir}"

  cp "${REPO_ROOT}/docker/offline/compose.yml" "${compose_dir}/compose.yml"
  cp "${REPO_ROOT}/docker/offline/portal.offline.yml" "${compose_dir}/portal.yml"

  cat > "${compose_dir}/.env" <<ENV
VERSION=${version}

DJANGO_SECRET_KEY=offline-secret-key
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=*

APP_DB_NAME=app_db
APP_DB_USER=app
APP_DB_PASSWORD=app
APP_DB_HOST=db_app
APP_DB_PORT=5432

PORTAL_DB_NAME=portal_db_test
PORTAL_DB_USER=portal
PORTAL_DB_PASSWORD=portal
PORTAL_DB_HOST=portal_db_test
PORTAL_DB_PORT=5432

PORTAL_CONFIG_PATH=/app/configs/portal.yml
PORTAL_PROFILE=dev
PORTAL_GATEWAY_BACKEND=orm

HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
SENTENCE_TRANSFORMERS_HOME=/opt/models
HF_HOME=/opt/models/hf_home
SEMANTIC_MODEL_PATH=/opt/models/paraphrase-multilingual-MiniLM-L12-v2
ENV

  mkdir -p "${compose_dir}/models" "${compose_dir}/seed"

  if [[ "${with_model}" == "1" ]]; then
    [[ -d "${REPO_ROOT}/models/paraphrase-multilingual-MiniLM-L12-v2" ]] || die "Model directory not found at models/paraphrase-multilingual-MiniLM-L12-v2. Prefetch model before bundling."
    log "Copying local model cache"
    mkdir -p "${models_dir}"
    cp -a "${REPO_ROOT}/models/." "${models_dir}/"
    cp -a "${models_dir}/." "${compose_dir}/models/"
  fi

  if [[ -n "${seed_xlsx}" ]]; then
    log "Copying seed files"
    mkdir -p "${seed_dir}" "${compose_dir}/seed"
    cp "${seed_xlsx}" "${seed_dir}/subdivision_primer.xlsx"
    cp "${seed_docx}" "${seed_dir}/test_svodka_semantic.docx"
    cp "${seed_dir}/subdivision_primer.xlsx" "${compose_dir}/seed/subdivision_primer.xlsx"
    cp "${seed_dir}/test_svodka_semantic.docx" "${compose_dir}/seed/test_svodka_semantic.docx"
  fi

  log "Saving docker images"
  docker image inspect "project_analiz:web-ver-${version}" >/dev/null
  docker image inspect "postgres:15" >/dev/null
  docker save "project_analiz:web-ver-${version}" -o "${artifacts_dir}/project_analiz_web-ver-${version}.tar"
  docker save "postgres:15" -o "${artifacts_dir}/postgres_15.tar"

  cp "${REPO_ROOT}/doc/offline/closed_contour_1_5_test.md" "${doc_dir}/closed_contour_1_5_test.md"

  log "Writing manifest"
  (
    cd "${bundle_dir}"
    : > manifest.json
    printf '{\n  "files": [\n' >> manifest.json
    local first="1"
    while IFS= read -r -d '' file; do
      local rel hash
      rel="${file#./}"
      hash="$(sha256_file "$file")"
      if [[ "${first}" == "0" ]]; then
        printf ',\n' >> manifest.json
      fi
      first="0"
      printf '    {"path": "%s", "sha256": "%s"}' "$rel" "$hash" >> manifest.json
    done < <(find . -type f ! -name manifest.json -print0 | sort -z)
    printf '\n  ]\n}\n' >> manifest.json
  )

  if [[ "${make_archive}" == "1" ]]; then
    local archive_name
    archive_name="${bundle_dir}.tar.gz"
    tar -C "$(dirname "${bundle_dir}")" -czf "${archive_name}" "$(basename "${bundle_dir}")"
    log "Created archive ${archive_name}"
  fi

  log "Bundle ready: ${bundle_dir}"
}

resolve_compose_dir() {
  if [[ -n "${OFFLINE_BUNDLE_DIR:-}" ]]; then
    echo "${OFFLINE_BUNDLE_DIR}/compose"
    return
  fi

  local latest
  latest="$(find "${REPO_ROOT}/dist" -maxdepth 1 -type d -name 'offline_bundle_*' | sort | tail -n 1 || true)"
  [[ -n "${latest}" ]] || die "No bundle found in dist/. Set OFFLINE_BUNDLE_DIR or run bundle first."
  echo "${latest}/compose"
}

compose_cmd() {
  local compose_dir
  compose_dir="$(resolve_compose_dir)"
  require_cmd docker
  docker compose -f "${compose_dir}/compose.yml" --env-file "${compose_dir}/.env" "$@"
}

import_cmd() {
  require_cmd docker

  local bundle_dir="${OFFLINE_BUNDLE_DIR:-}"
  if [[ -z "${bundle_dir}" ]]; then
    local compose_dir
    compose_dir="$(resolve_compose_dir)"
    bundle_dir="$(cd "${compose_dir}/.." && pwd)"
  fi

  local artifacts_dir="${bundle_dir}/artifacts"
  [[ -d "${artifacts_dir}" ]] || die "Artifacts directory not found: ${artifacts_dir}"

  shopt -s nullglob
  local loaded=0
  local archive
  for archive in "${artifacts_dir}"/*.tar; do
    log "Loading ${archive}"
    docker load -i "${archive}"
    loaded=1
  done
  for archive in "${artifacts_dir}"/*.tar.gz "${artifacts_dir}"/*.tgz; do
    log "Loading ${archive}"
    gzip -dc "${archive}" | docker load
    loaded=1
  done
  for archive in "${artifacts_dir}"/*.tar.zst; do
    require_cmd zstd
    log "Loading ${archive}"
    zstd -dc "${archive}" | docker load
    loaded=1
  done
  shopt -u nullglob

  [[ "${loaded}" == "1" ]] || die "No image archives found in ${artifacts_dir}"
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    bundle)
      shift
      bundle_cmd "$@"
      ;;
    import)
      import_cmd
      ;;
    up)
      compose_cmd up -d db_app portal_db_test migrate_app migrate_portal web
      ;;
    seed)
      compose_cmd --profile seed run --rm seed_portal
      ;;
    logs)
      compose_cmd logs -f --tail=200 web db_app portal_db_test migrate_app migrate_portal
      ;;
    down)
      compose_cmd down --remove-orphans
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      die "Unknown command: ${cmd}"
      ;;
  esac
}

main "$@"
