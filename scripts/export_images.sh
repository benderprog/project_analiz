#!/usr/bin/env bash
set -euo pipefail

# Export docker images used by the stack into tar artifacts for offline use.

usage() {
  cat <<'USAGE'
Usage: ./scripts/export_images.sh --version 1.1 [--tag-prefix project_analiz] [--output dist/release_ver_1_1/artifacts]
USAGE
}

log() {
  printf "[export_images] %s\n" "$1"
}

version=""
tag_prefix="project_analiz"
output=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      version="$2"
      shift 2
      ;;
    --tag-prefix)
      tag_prefix="$2"
      shift 2
      ;;
    --output)
      output="$2"
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

if [[ -z "$version" ]]; then
  echo "--version is required." >&2
  usage
  exit 1
fi

version_slug="${version//./_}"
if [[ -z "$output" ]]; then
  output="dist/release_ver_${version_slug}/artifacts"
fi

mkdir -p "$output"

log "Building web image via docker compose"
docker compose build web

web_image_id="$(docker compose images -q web)"
if [[ -z "$web_image_id" ]]; then
  echo "Unable to resolve web image ID from docker compose." >&2
  exit 1
fi

web_tag="${tag_prefix}:web-ver-${version}"
log "Tagging web image ${web_image_id} as ${web_tag}"
docker tag "$web_image_id" "$web_tag"

web_tar="${output}/web_ver_${version}.tar"
log "Saving web image to ${web_tar}"
docker save -o "$web_tar" "$web_tag"
sha256sum "$web_tar" > "${web_tar}.sha256"

postgres_image="postgres:15"
log "Ensuring postgres image ${postgres_image} is present"
docker pull "$postgres_image"

postgres_tar="${output}/postgres_15.tar"
log "Saving postgres image to ${postgres_tar}"
docker save -o "$postgres_tar" "$postgres_image"
sha256sum "$postgres_tar" > "${postgres_tar}.sha256"

log "Image export complete: ${output}"
