#!/usr/bin/env bash
set -euo pipefail

# Bring up the stack in offline mode and run migrations/seed/sync operations.

usage() {
  cat <<'USAGE'
Usage: ./scripts/offline_up.sh [--seed] [--sync] [--rebuild-embeddings]
USAGE
}

log() {
  printf "[offline_up] %s\n" "$1"
}

seed="false"
sync="false"
rebuild_embeddings="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed)
      seed="true"
      shift
      ;;
    --sync)
      sync="true"
      shift
      ;;
    --rebuild-embeddings)
      rebuild_embeddings="true"
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

if [[ ! -f "compose/.env.docker" ]]; then
  echo "Missing compose/.env.docker. Rebuild the release bundle with scripts/make_release_bundle.sh so compose/.env.docker is generated automatically." >&2
  exit 1
fi

if [[ ! -f "compose/portal.yml" ]]; then
  echo "Missing compose/portal.yml. Rebuild the release bundle with scripts/make_release_bundle.sh so portal config is bundled." >&2
  exit 1
fi

log "Starting docker compose stack"
docker compose --env-file compose/.env.docker -f compose/docker-compose.yml -f compose/docker-compose.offline.yml up -d

wait_for_db() {
  local service="$1"
  local retries=30
  local count=0

  log "Waiting for ${service} to become ready"
  until docker compose exec -T "$service" pg_isready >/dev/null 2>&1; do
    count=$((count + 1))
    if [[ "$count" -ge "$retries" ]]; then
      echo "Timed out waiting for ${service} to be ready." >&2
      exit 1
    fi
    sleep 2
  done
}

wait_for_db db
wait_for_db portal_db

log "Running database migrations"
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py migrate --database=portal

log "Ensuring admin user"
docker compose run --rm web python manage.py ensure_admin

if [[ "$seed" == "true" ]]; then
  log "Seeding portal database"
  docker compose run --rm web python manage.py seed_portal --reset \
    --xlsx /app/seed/subdivision_primer.xlsx \
    --docx /app/seed/test_svodka_semantic.docx
fi

if [[ "$sync" == "true" ]]; then
  sync_args=(sync_portal_reference)
  if [[ "$rebuild_embeddings" == "true" ]]; then
    sync_args+=(--rebuild-embeddings)
  fi
  log "Syncing portal reference data"
  docker compose run --rm web python manage.py "${sync_args[@]}"
fi

log "Offline deployment complete"
log "Open http://127.0.0.1:8000/"
