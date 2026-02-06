# Docker offline setup with model warm-up

## Overview

There are two supported approaches:

1) **Lightweight image + mounted model directory (recommended)**
2) **Heavier image with model baked in (optional)**

The recommended path keeps the Docker image small by mounting the model at
runtime. The optional profile bakes the model into the image during build, which
increases image size and build time.

By default, the Docker images are CPU-only and do not include CUDA/NVIDIA
libraries. A GPU-enabled build would require a separate, explicit profile and
would significantly increase image size.

If a build fails with timeouts to `download.pytorch.org`, rerun the build or
ensure network access; pip now uses a 120s timeout to improve resilience.

## Option 1: lightweight image + mounted model directory (recommended)

Prepare the model directory on the host and run with the offline override:

```bash
docker compose -f docker-compose.yml -f docker-compose.offline.yml up --build
```

This configuration:

- Mounts `./models` into the container at `/opt/models`.
- Sets `WARMUP_ON_START=1` so the container warms the model once at startup.
- Forces offline behavior (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`).
- Keeps the image small (model is not baked in).

## Option 2: heavy image with model baked in (optional)

Build and run with the baked-in model profile:

```bash
docker compose -f docker-compose.yml -f docker-compose.with-model.yml build --no-cache web
docker compose -f docker-compose.yml -f docker-compose.with-model.yml up
```

This build runs `python manage.py warmup_models`, which:

- Loads the model from `SEMANTIC_MODEL_PATH` if it exists.
- Falls back to `SEMANTIC_MODEL_NAME` if the path is missing.
- Encodes a few short strings to materialize weights and cache.
- Prints `OK` on success.

The image already contains the model at:

```
/opt/models/<MODEL_NAME>
```

## Runtime (offline)

Runtime environment variables force offline behavior:

- `HF_HUB_OFFLINE=1`
- `TRANSFORMERS_OFFLINE=1`

`SEMANTIC_MODEL_PATH` is set to `/opt/models/<MODEL_NAME>` so the app never tries
to hit the network.

## Static/templates parity with local runserver

- WhiteNoise serves static files in Docker (no nginx required).
- `collectstatic` runs in the image build and at container startup.
- `.env.docker` sets `DJANGO_DEBUG=true` so rendering matches local runserver.
- The app keeps the existing `TIME_ZONE=Europe/Moscow` setting for consistency.
