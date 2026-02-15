# Офлайн-модели

## Как выбирается модель

Порядок разрешения:
1. `SEMANTIC_MODEL_PATH`, если путь существует.
2. `./models/<SEMANTIC_MODEL_NAME>`, если директория существует.
3. иначе используется значение `SEMANTIC_MODEL_NAME` как remote model id.

Source: apps/analysis_app/semantic_model_resolver.py (`resolve_semantic_model_path`)

## Что значит offline в коде

Offline определяется флагами:
- `HF_HUB_OFFLINE=1|true|yes`, или
- `TRANSFORMERS_OFFLINE=1|true|yes`.

При offline и отсутствии локальной модели загрузка прерывается с RuntimeError.

Source: apps/analysis_app/semantic_model_resolver.py (`is_offline_mode`)  
Source: apps/analysis_app/semantic.py (`get_sentence_model`)

## Рекомендация для закрытого контура

- Храните модель на хосте и монтируйте в контейнер, например `/opt/models/<SEMANTIC_MODEL_NAME>`.
- Выставьте `SEMANTIC_MODEL_PATH` в смонтированный путь.
- Включите `HF_HUB_OFFLINE=1` и `TRANSFORMERS_OFFLINE=1`.

Source: Dockerfile (`SEMANTIC_MODEL_PATH` env)  
Source: config/settings.py (`SEMANTIC_MODEL_*`, `OFFLINE_MODE`)
