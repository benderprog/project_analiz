# Docker в закрытом контуре

## Доступные сценарии в репозитории

1. Базовый `docker-compose.yml` (web + app_db + portal_db).
2. Отдельный offline-стек в `docker/offline/compose.yml`.

Source: docker-compose.yml  
Source: docker/offline/compose.yml

## Важно для закрытого контура

`Dockerfile` по умолчанию пытается ставить PyTorch и зависимости из внешних индексов. Для действительно изолированного сегмента используйте заранее подготовленный registry/wheelhouse или offline-сценарии из `docker/offline/*`.

Source: Dockerfile (pip install с `download.pytorch.org` и `pypi.org`)  
Source: docker/offline/README.md

## Быстрый старт (базовый compose, Ubuntu)

```bash
cp .env.docker.example .env.docker
docker compose up --build
```

Проверка healthcheck:

```bash
docker compose ps
docker compose logs web --tail=100
```

Source: docker-compose.yml (`web.healthcheck`, env_file, depends_on)

## Томы/данные

В `docker-compose.yml` определены volume'ы:
- `app_db_data`
- `portal_db_data`

Для offline-моделей рекомендуется дополнительно примонтировать каталог моделей в `web` и пробросить `SEMANTIC_MODEL_PATH`.

Source: docker-compose.yml (`volumes`)  
Source: apps/analysis_app/semantic_model_resolver.py (`resolve_semantic_model_path`)

## Static/media

- `collectstatic` вызывается в bootstrap и Dockerfile.
- `MEDIA_ROOT` = `BASE_DIR/media`, `STATIC_ROOT` = `BASE_DIR/staticfiles`.

Если нужно долговременное хранение media/static вне контейнера — добавьте bind mounts в compose.

Source: scripts/bootstrap.sh  
Source: Dockerfile  
Source: config/settings.py (`MEDIA_ROOT`, `STATIC_ROOT`)

## TEST/PROD portal DB в Docker

- По умолчанию `.env.example`: test БД `portal_db_test`.
- В `docker-compose.yml` сервис `portal_db` поднимает БД `portal_db`.
- Для админ-кнопки «Тестовая БД» задайте `PORTAL_DB_TEST_*` отдельно, если тестовая БД отличается от `PORTAL_DB_*`.

Source: .env.example  
Source: docker-compose.yml (`portal_db.environment.POSTGRES_DB`)  
Source: apps/analysis_app/portal_db_settings_service.py (`get_test_portal_db_params`)
