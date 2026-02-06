# Docker offline setup with model warm-up

## Overview

The Docker image now prefetches and warms the sentence-transformers model during
the build stage, so runtime can stay fully offline and the first request does not
incur model download latency.

## Build (online) with warmup

```bash
docker compose build --no-cache web
```

The build runs `python manage.py warmup_models`, which:

- Loads the model from `SEMANTIC_MODEL_PATH` if it exists.
- Falls back to `SEMANTIC_MODEL_NAME` if the path is missing.
- Encodes a few short strings to materialize weights and cache.
- Prints `OK` on success.

## Verify warmed model in a running container

```bash
docker compose exec web python manage.py warmup_models
```

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

If you want to override the baked-in model without rebuilding, uncomment the bind
mount in `docker-compose.yml`:

```yaml
    # volumes:
    #   - ./models:/opt/models
```
