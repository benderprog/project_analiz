#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash scripts/release/build_image.sh <version>
Example:
  bash scripts/release/build_image.sh 1.9
USAGE
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

version="$1"
image="project_analiz:web-ver-${version}"

echo "[release] building ${image}"
docker build -f docker/Dockerfile.web -t "${image}" .
docker image inspect "${image}" >/dev/null
echo "[release] done: ${image}"
