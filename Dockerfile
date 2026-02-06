# syntax=docker/dockerfile:1.4
FROM python:3.11-slim AS web

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY manage.py /app/
COPY apps /app/apps
COPY config /app/config
COPY scripts /app/scripts
COPY static /app/static
COPY templates /app/templates

ARG SEMANTIC_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2
ARG MODEL_DIR=/opt/models
ARG INCLUDE_MODEL=0
ENV SEMANTIC_MODEL_NAME=$SEMANTIC_MODEL_NAME
ENV SEMANTIC_MODEL_PATH=$MODEL_DIR/$SEMANTIC_MODEL_NAME

RUN if [ "$INCLUDE_MODEL" = "1" ]; then \
        mkdir -p "$MODEL_DIR" \
        && python manage.py warmup_models; \
    fi

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["bash", "-c", "./scripts/bootstrap.sh"]
