#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=scripts/offline/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

usage() {
  cat <<'USAGE'
Offline bundle / runtime helper

Usage:
  ./scripts/offline/offline.sh bundle --version 1.9 --db-app-dump /abs/path/app_db.dump --db-portal-dump /abs/path/portal_db_test.dump [--archive]
  ./scripts/offline/offline.sh import
  ./scripts/offline/offline.sh restore
  ./scripts/offline/offline.sh reset-db
  ./scripts/offline/offline.sh up
  ./scripts/offline/offline.sh stop
  ./scripts/offline/offline.sh start
  ./scripts/offline/offline.sh logs
  ./scripts/offline/offline.sh ps
  ./scripts/offline/offline.sh status
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

resolve_bundle_root() {
  if [[ -n "${OFFLINE_BUNDLE_DIR:-}" ]]; then
    echo "${OFFLINE_BUNDLE_DIR}"
    return
  fi

  if [[ -f "${BUNDLE_ROOT}/compose/compose.yml" ]]; then
    echo "${BUNDLE_ROOT}"
    return
  fi

  local latest
  latest="$(find "${REPO_ROOT}/dist" -maxdepth 1 -type d -name 'offline_bundle_*' | sort | tail -n 1 || true)"
  [[ -n "${latest}" ]] || die "No bundle found in dist/. Set OFFLINE_BUNDLE_DIR, run from extracted bundle root, or run bundle first."
  echo "${latest}"
}

resolve_bundle_paths() {
  local root
  root="$(resolve_bundle_root)"
  compose_dir="${root}/compose"
  artifacts_dir="${root}/artifacts"
  dumps_dir="${root}/db_dumps"
  configs_dir="${root}/configs"
}

bundle_cmd() {
  require_cmd docker

  local version=""
  local db_app_dump=""
  local db_portal_dump=""
  local make_archive="0"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version)
        version="${2:-}"
        shift 2
        ;;
      --with-model)
        log "Flag --with-model is deprecated: semantic model is always included in bundle."
        shift
        ;;
      --db-app-dump)
        db_app_dump="${2:-}"
        shift 2
        ;;
      --db-portal-dump)
        db_portal_dump="${2:-}"
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
  [[ -n "${db_app_dump}" ]] || die "bundle requires --db-app-dump"
  [[ -n "${db_portal_dump}" ]] || die "bundle requires --db-portal-dump"
  [[ "${db_app_dump}" = /* ]] || die "--db-app-dump must be an absolute path"
  [[ "${db_portal_dump}" = /* ]] || die "--db-portal-dump must be an absolute path"
  [[ -f "${db_app_dump}" ]] || die "App DB dump not found: ${db_app_dump}"
  [[ -f "${db_portal_dump}" ]] || die "Portal DB dump not found: ${db_portal_dump}"
  local required_model_dir="${REPO_ROOT}/models/paraphrase-multilingual-MiniLM-L12-v2"
  [[ -d "${required_model_dir}" ]] || die "Required semantic model not found: ${required_model_dir}. Run scripts/prefetch_model.sh before bundling."

  local bundle_dir
  bundle_dir="${OFFLINE_BUNDLE_DIR:-$(default_bundle_dir_for_version "$version")}"
  local compose_dir="${bundle_dir}/compose"
  local artifacts_dir="${bundle_dir}/artifacts"
  local models_dir="${bundle_dir}/models"
  local dumps_dir="${bundle_dir}/db_dumps"
  local doc_dir="${bundle_dir}/doc"
  local scripts_dir="${bundle_dir}/scripts/offline"
  local configs_dir="${bundle_dir}/configs"

  log "Preparing bundle at ${bundle_dir}"
  rm -rf "${bundle_dir}"
  mkdir -p "${compose_dir}" "${artifacts_dir}" "${doc_dir}" "${scripts_dir}" "${configs_dir}" "${dumps_dir}"

  cp "${REPO_ROOT}/docker/offline/compose.yml" "${compose_dir}/compose.yml"
  local portal_backend="${PORTAL_GATEWAY_BACKEND:-sql}"
  local sql_source_dir="${REPO_ROOT}/configs/portal/sql"
  local sql_source_prod_ro_dir="${REPO_ROOT}/configs/portal/sql_prod_ro"
  [[ -f "${REPO_ROOT}/configs/portal.offline.yml" ]] || die "Missing portal config template: configs/portal.offline.yml"
  cp "${REPO_ROOT}/configs/portal.offline.yml" "${configs_dir}/portal.yml"
  mkdir -p "${configs_dir}/portal"
  cp "${REPO_ROOT}/configs/portal.offline.yml" "${configs_dir}/portal/portal.yml"
  if [[ "${portal_backend}" == "sql" && ! -d "${sql_source_dir}" ]]; then
    die "PORTAL_GATEWAY_BACKEND=sql requires ${sql_source_dir} to exist for bundling."
  fi
  if [[ "${portal_backend}" == "sql" && ! -d "${sql_source_prod_ro_dir}" ]]; then
    die "PORTAL_GATEWAY_BACKEND=sql requires ${sql_source_prod_ro_dir} to exist for bundling."
  fi
  mkdir -p "${configs_dir}/portal/sql"
  mkdir -p "${configs_dir}/portal/sql_prod_ro"
  if [[ -d "${sql_source_dir}" ]]; then
    cp -a "${sql_source_dir}/." "${configs_dir}/portal/sql/"
  fi
  if [[ -d "${sql_source_prod_ro_dir}" ]]; then
    cp -a "${sql_source_prod_ro_dir}/." "${configs_dir}/portal/sql_prod_ro/"
  fi

  cp "${REPO_ROOT}/scripts/offline/offline.sh" "${scripts_dir}/offline.sh"
  cp "${REPO_ROOT}/scripts/offline/_lib.sh" "${scripts_dir}/_lib.sh"
  chmod +x "${scripts_dir}/offline.sh" "${scripts_dir}/_lib.sh"

  cat > "${compose_dir}/.env" <<ENV
VERSION=${version}
PORTAL_MODE=local

DJANGO_SECRET_KEY=offline-secret-key
DJANGO_DEBUG=true
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
PORTAL_GATEWAY_BACKEND=sql

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
SENTENCE_TRANSFORMERS_HOME=/opt/models
HF_HOME=/opt/models/hf_home
SEMANTIC_MODEL_PATH=/opt/models/paraphrase-multilingual-MiniLM-L12-v2
ENV

  mkdir -p "${compose_dir}/models" "${compose_dir}/db_dumps" "${compose_dir}/media"

  log "Copying local semantic model cache"
  mkdir -p "${models_dir}"
  cp -a "${REPO_ROOT}/models/." "${models_dir}/"
  cp -a "${models_dir}/." "${compose_dir}/models/"
  [[ -d "${compose_dir}/models/paraphrase-multilingual-MiniLM-L12-v2" ]] || die "Required semantic model was not copied into bundle compose/models."

  log "Copying DB dumps"
  cp "${db_app_dump}" "${dumps_dir}/app_db.dump"
  cp "${db_portal_dump}" "${dumps_dir}/portal_db_test.dump"
  cp "${dumps_dir}/app_db.dump" "${compose_dir}/db_dumps/app_db.dump"
  cp "${dumps_dir}/portal_db_test.dump" "${compose_dir}/db_dumps/portal_db_test.dump"

  log "Saving docker images required by docker/offline/compose.yml"
  local image
  mapfile -t images < <(awk '$1 == "image:" {print $2}' "${REPO_ROOT}/docker/offline/compose.yml" | tr -d '"' | sort -u)

  if [[ "${#images[@]}" -eq 0 ]]; then
    die "No images found in docker/offline/compose.yml"
  fi

  for image in "${images[@]}"; do
    local resolved_image safe_image
    resolved_image="${image//\$\{VERSION\}/${version}}"
    docker image inspect "${resolved_image}" >/dev/null
    safe_image="${resolved_image//\//_}"
    safe_image="${safe_image//:/_}"
    log "Saving image ${resolved_image}"
    docker save "${resolved_image}" -o "${artifacts_dir}/${safe_image}.tar"
  done

  cp "${REPO_ROOT}/README.md" "${doc_dir}/README_MAIN.md"
  cp "${REPO_ROOT}/doc/offline/README.md" "${doc_dir}/README.md"
  cp "${REPO_ROOT}/doc/offline/closed_contour_release.md" "${doc_dir}/closed_contour_release.md"
  cp "${REPO_ROOT}/doc/16_offline_dump_first_bundle.md" "${doc_dir}/16_offline_dump_first_bundle.md"
  cp "${REPO_ROOT}/doc/12_release_process.md" "${doc_dir}/12_release_process.md"
  cp "${REPO_ROOT}/doc/22_portal_config.md" "${doc_dir}/22_portal_config.md"
  cp "${REPO_ROOT}/doc/23_portal_gateway.md" "${doc_dir}/23_portal_gateway.md"

  cp "${REPO_ROOT}/doc/offline/README_OFFLINE.md" "${bundle_dir}/README_OFFLINE.md"
  cp "${REPO_ROOT}/doc/offline/README_REMOTE_PORTAL_RO.md" "${bundle_dir}/README_REMOTE_PORTAL_RO.md"
  cp "${REPO_ROOT}/doc/offline/README_SQL_OVERRIDE.md" "${bundle_dir}/README_SQL_OVERRIDE.md"

  log "Writing manifest"
  (
    cd "${bundle_dir}"
    : > manifest.json
    : > checksums.sha256
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
      printf '%s  %s\n' "$hash" "$rel" >> checksums.sha256
    done < <(find . -type f ! -name manifest.json ! -name checksums.sha256 -print0 | sort -z)
    printf '\n  ]\n}\n' >> manifest.json
  )

  if [[ "${make_archive}" == "1" ]]; then
    local safe_version archive_name archive_path
    safe_version="$(sanitize_version "${version}")"
    archive_name="offline_bundle_${safe_version}.tar.gz"
    archive_path="${REPO_ROOT}/dist/${archive_name}"
    tar -C "$(dirname "${bundle_dir}")" -czf "${archive_path}" "$(basename "${bundle_dir}")"
    cp "${REPO_ROOT}/doc/offline/README_OFFLINE.md" "${REPO_ROOT}/dist/README_OFFLINE_${safe_version}.md"
    log "Created archive ${archive_path}"
  fi

  log "Bundle ready: ${bundle_dir}"
}

compose_cmd() {
  resolve_bundle_paths
  require_cmd docker
  docker compose -f "${compose_dir}/compose.yml" --env-file "${compose_dir}/.env" "$@"
}

load_compose_env() {
  resolve_bundle_paths

  # shellcheck disable=SC1090
  set -a
  source "${compose_dir}/.env"
  set +a
}

service_network_name() {
  local service="$1"
  local container_id
  container_id="$(compose_cmd ps -q "${service}")"
  [[ -n "${container_id}" ]] || die "Container for service '${service}' is not running"

  docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "${container_id}" | head -n 1
}

wait_for_service_healthy() {
  local service="$1"
  local timeout_s="${2:-90}"
  local waited=0

  while (( waited < timeout_s )); do
    local container_id health
    container_id="$(compose_cmd ps -q "${service}")"
    if [[ -n "${container_id}" ]]; then
      health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
      if [[ "${health}" == "healthy" || "${health}" == "running" ]]; then
        return 0
      fi
    fi

    sleep 2
    waited=$((waited + 2))
  done

  die "Timed out waiting for service '${service}' to become healthy"
}

run_pg_restore_in_postgres15() {
  local service="$1"
  local db_host="$2"
  local db_user="$3"
  local db_name="$4"
  local db_password="$5"
  local dump_file="$6"
  local network_name

  resolve_bundle_paths
  network_name="$(service_network_name "${service}")"

  log "Restoring ${db_name} from ${dump_file} using postgres:15 on network ${network_name}"
  docker run --rm \
    --network "${network_name}" \
    -v "${dumps_dir}:/db_dumps:ro" \
    -e "PGPASSWORD=${db_password}" \
    postgres:15 \
    sh -lc "pg_restore --version && pg_restore -h ${db_host} -p 5432 -U ${db_user} -d ${db_name} --clean --if-exists --no-owner --no-privileges /db_dumps/${dump_file}"
}

db_has_user_tables() {
  local service="$1"
  local db_host="$2"
  local db_user="$3"
  local db_name="$4"
  local db_password="$5"
  local network_name query result

  network_name="$(service_network_name "${service}")"
  query="SELECT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_type = 'BASE TABLE'
  );"

  result="$(docker run --rm \
    --network "${network_name}" \
    -e "PGPASSWORD=${db_password}" \
    postgres:15 \
    sh -lc "psql -h ${db_host} -p 5432 -U ${db_user} -d ${db_name} -tAc \"${query}\"" | tr -d '[:space:]')"

  [[ "${result}" == "t" ]]
}

restore_if_needed() {
  local service="$1"
  local db_host="$2"
  local db_user="$3"
  local db_name="$4"
  local db_password="$5"
  local dump_file="$6"
  local force_restore="${7:-0}"

  if [[ "${force_restore}" == "1" ]]; then
    run_pg_restore_in_postgres15 "${service}" "${db_host}" "${db_user}" "${db_name}" "${db_password}" "${dump_file}"
    return
  fi

  if db_has_user_tables "${service}" "${db_host}" "${db_user}" "${db_name}" "${db_password}"; then
    log "restore skipped, DB already initialized: ${db_name}"
    return
  fi

  run_pg_restore_in_postgres15 "${service}" "${db_host}" "${db_user}" "${db_name}" "${db_password}" "${dump_file}"
}

restore_cmd() {
  load_compose_env
  local force_restore="${1:-0}"

  if [[ "${OFFLINE_RESTORE:-0}" == "1" ]]; then
    force_restore="1"
  fi

  local portal_mode="${PORTAL_MODE:-local}"
  if [[ "${portal_mode}" == "remote" ]]; then
    compose_cmd up -d --remove-orphans --no-build db_app
    wait_for_service_healthy "db_app"
    restore_if_needed "db_app" "db_app" "app" "app_db" "${APP_DB_PASSWORD}" "app_db.dump" "${force_restore}"
    return
  fi

  compose_cmd up -d --remove-orphans --no-build db_app portal_db_test
  wait_for_service_healthy "db_app"
  wait_for_service_healthy "portal_db_test"
  restore_if_needed "db_app" "db_app" "app" "app_db" "${APP_DB_PASSWORD}" "app_db.dump" "${force_restore}"
  restore_if_needed "portal_db_test" "portal_db_test" "portal" "portal_db_test" "${PORTAL_DB_PASSWORD}" "portal_db_test.dump" "${force_restore}"
}

import_cmd() {
  require_cmd docker
  resolve_bundle_paths

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

up_cmd() {
  load_compose_env
  mkdir -p "${compose_dir}/media"
  restore_cmd "0"

  local portal_mode="${PORTAL_MODE:-local}"
  if [[ "${portal_mode}" == "remote" ]]; then
    compose_cmd run --rm migrate_app
    compose_cmd up -d --remove-orphans --no-build web worker
    return
  fi

  compose_cmd run --rm migrate_app
  compose_cmd run --rm migrate_portal
  compose_cmd up -d --remove-orphans --no-build web worker
}

reset_db_cmd() {
  load_compose_env
  mkdir -p "${compose_dir}/media"
  log "Factory reset: dropping DB volumes and restoring dumps"
  compose_cmd down -v --remove-orphans
  restore_cmd "1"

  local portal_mode="${PORTAL_MODE:-local}"
  compose_cmd run --rm migrate_app
  if [[ "${portal_mode}" != "remote" ]]; then
    compose_cmd run --rm migrate_portal
  fi
  compose_cmd up -d --remove-orphans --no-build web worker
}

logs_cmd() {
  load_compose_env
  local portal_mode="${PORTAL_MODE:-local}"
  if [[ "${portal_mode}" == "remote" ]]; then
    compose_cmd logs -f --tail=200 web worker db_app
    return
  fi
  compose_cmd logs -f --tail=200 web worker db_app portal_db_test
}

runtime_services() {
  load_compose_env

  local portal_mode="${PORTAL_MODE:-local}"
  local service
  local services=()

  while IFS= read -r service; do
    [[ -n "${service}" ]] || continue
    case "${service}" in
      restore_*|migrate_*)
        continue
        ;;
      portal_db_test)
        if [[ "${portal_mode}" == "remote" ]]; then
          log "PORTAL_MODE=remote detected: skipping portal_db_test"
          continue
        fi
        ;;
    esac
    services+=("${service}")
  done < <(compose_cmd config --services)

  if [[ "${#services[@]}" -eq 0 ]]; then
    die "No runtime services detected in compose"
  fi

  printf '%s\n' "${services[@]}"
}

service_running() {
  local service="$1"
  local container_id

  container_id="$(compose_cmd ps -q "${service}")"
  [[ -n "${container_id}" ]] || return 1

  [[ "$(docker inspect -f '{{.State.Running}}' "${container_id}" 2>/dev/null || true)" == "true" ]]
}

service_exists() {
  local service="$1"
  [[ -n "$(compose_cmd ps -a -q "${service}")" ]]
}

stop_cmd() {
  local services=()
  mapfile -t services < <(runtime_services)

  local running_count=0
  local service
  for service in "${services[@]}"; do
    if service_running "${service}"; then
      running_count=$((running_count + 1))
    fi
  done

  if [[ "${running_count}" -eq 0 ]]; then
    log "Stopping services: ${services[*]}"
    log "already stopped"
    log "Done"
    return
  fi

  log "Stopping services: ${services[*]}"
  compose_cmd stop "${services[@]}"
  log "stop completed"
  log "Done"
}

start_cmd() {
  load_compose_env
  mkdir -p "${compose_dir}/media"
  local services=()
  mapfile -t services < <(runtime_services)

  local all_running=1
  local all_exist=1
  local service

  for service in "${services[@]}"; do
    if ! service_exists "${service}"; then
      all_exist=0
      all_running=0
      continue
    fi
    if ! service_running "${service}"; then
      all_running=0
    fi
  done

  log "Starting services: ${services[*]}"

  if [[ "${all_running}" -eq 1 ]]; then
    log "already running"
    log "Done"
    return
  fi

  if [[ "${all_exist}" -eq 1 ]]; then
    compose_cmd start "${services[@]}"
  else
    compose_cmd up -d --no-build "${services[@]}"
  fi

  log "start completed"
  log "Done"
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
      up_cmd
      ;;
    stop)
      stop_cmd
      ;;
    start)
      start_cmd
      ;;
    restore)
      restore_cmd "1"
      ;;
    reset-db)
      reset_db_cmd
      ;;
    logs)
      logs_cmd
      ;;
    ps|status)
      compose_cmd ps -a
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
