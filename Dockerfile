FROM python:3.11-slim AS web

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

ARG SEMANTIC_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2
ARG MODEL_DIR=/opt/models
ENV SEMANTIC_MODEL_NAME=$SEMANTIC_MODEL_NAME
ENV SEMANTIC_MODEL_PATH=$MODEL_DIR/$SEMANTIC_MODEL_NAME

RUN mkdir -p "$MODEL_DIR" \
    && python manage.py warmup_models

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["bash", "-c", "./scripts/bootstrap.sh"]
