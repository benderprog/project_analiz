#!/usr/bin/env bash
set -euo pipefail

# Load docker image tarballs from an artifacts directory.

usage() {
  cat <<'USAGE'
Usage: ./scripts/import_images.sh ./artifacts
USAGE
}

log() {
  printf "[import_images] %s\n" "$1"
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

artifacts_dir="$1"
if [[ ! -d "$artifacts_dir" ]]; then
  echo "Artifacts directory not found: ${artifacts_dir}" >&2
  exit 1
fi

manifest_path="$(cd "$artifacts_dir/.." && pwd)/manifest.json"
if [[ -f "$manifest_path" ]]; then
  log "Verifying sha256 checksums via manifest.json"
  python - <<PY
import hashlib
import json
from pathlib import Path

artifacts_dir = Path("${artifacts_dir}").resolve()
manifest_path = Path("${manifest_path}")

payload = json.loads(manifest_path.read_text())
checksums = {entry["path"]: entry["sha256"] for entry in payload.get("files", [])}

errors = []
for tar_path in sorted(artifacts_dir.glob("*.tar")):
    rel_path = tar_path.relative_to(manifest_path.parent).as_posix()
    expected = checksums.get(rel_path)
    if not expected:
        errors.append(f"Missing checksum for {rel_path}")
        continue
    digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    if digest != expected:
        errors.append(f"Checksum mismatch for {rel_path}")

if errors:
    for error in errors:
        print(error)
    raise SystemExit(1)
print("Checksums verified")
PY
fi

shopt -s nullglob
for tar_path in "${artifacts_dir}"/*.tar; do
  log "Loading ${tar_path}"
  docker load -i "$tar_path"
 done

log "All images loaded"
