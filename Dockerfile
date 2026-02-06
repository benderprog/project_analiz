# syntax=docker/dockerfile:1.4
FROM python:3.11-slim AS web

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

ARG TORCH_CHANNEL=cpu
ARG TORCH_VERSION=""

COPY requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -z "$TORCH_VERSION" ]; then \
        pip install --no-cache-dir --index-url "https://download.pytorch.org/whl/${TORCH_CHANNEL}" torch torchvision torchaudio; \
    else \
        pip install --no-cache-dir --index-url "https://download.pytorch.org/whl/${TORCH_CHANNEL}" torch=="${TORCH_VERSION}" torchvision torchaudio; \
    fi

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

RUN python -c "import pkgutil, sys; bad=[m.name for m in pkgutil.iter_modules() if m.name.startswith('nvidia')]; sys.exit(1 if bad else 0)" \
    && python -c "import torch; print('torch', torch.__version__, 'cuda_available', torch.cuda.is_available()); assert torch.cuda.is_available() is False"

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
