# Аудит документации

## Что уже есть

- Короткий `README.md` с заметками про `PORTAL_DB_TEST_*` и `PORTAL_DB_FERNET_KEY`.
- Папка `doc/` с разрозненными материалами (архитектура, локальный запуск, offline-сценарии, smoke test и т.д.).
- `docker/offline/README.md` и related файлы для offline bundle/compose.

Source: README.md (до обновления)  
Source: doc/01_architecture.md  
Source: doc/02_local_setup.md  
Source: doc/offline/README.md

## Что отсутствовало/требовало обновления

- Единой структуры `docs/` под эксплуатацию в закрытом контуре.
- Сводной документации по runtime-настройке Portal DB из админки (TEST/PROD, read-only, кнопки, проверка подключения, поведение пароля).
- Явной карты env-переменных с обязательностью, значениями по умолчанию и offline-флагами.
- Проверяемой инструкции по Docker-сценариям (обычный compose + offline compose).
- Централизованного troubleshooting по типовым ошибкам подключения/зависимостей.

## Что сделано в этом PR

- Пересобрана корневая навигация документации.
- Добавлен пакет эксплуатационных документов в `docs/`.
- Актуализирован `.env.example` под TEST/PROD и offline-контур.

Source: README.md  
Source: docs/*.md  
Source: .env.example
