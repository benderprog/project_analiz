#!/usr/bin/env bash
set -euo pipefail

# Download and cache a SentenceTransformer model for offline use.

usage() {
  cat <<'USAGE'
Usage: ./scripts/prefetch_model.sh --model paraphrase-multilingual-MiniLM-L12-v2 --out models/paraphrase-multilingual-MiniLM-L12-v2
USAGE
}

log() {
  printf "[prefetch_model] %s\n" "$1"
}

model_name=""
output_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      model_name="$2"
      shift 2
      ;;
    --out)
      output_dir="$2"
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

if [[ -z "$model_name" ]]; then
  echo "--model is required." >&2
  usage
  exit 1
fi

if [[ -z "$output_dir" ]]; then
  output_dir="models/${model_name}"
fi

log "Downloading model ${model_name}"
python - <<PY
from pathlib import Path
from sentence_transformers import SentenceTransformer

model_name = "${model_name}"
output_dir = Path("${output_dir}")
output_dir.mkdir(parents=True, exist_ok=True)

model = SentenceTransformer(model_name)
model.save(str(output_dir))

# Verify the saved model can be loaded offline.
SentenceTransformer(str(output_dir))
print(f"Model saved to {output_dir}")
PY

log "Model cached at ${output_dir}"
