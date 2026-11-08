---
name: kwhale-codebase
description: Карта кодовой базы KWhale — репозитории, где что лежит, ключевые модули, команды сборки/тестов/запуска, договорённости. Использовать в начале любой работы по проекту, чтобы ориентироваться в server/kwhale-android/agent и не искать файлы наугад.
---

# KWhale — карта кодовой базы

Корень: `~/Документы/infra/`. Музыкальный сервис: self-hosted агрегатор 9
источников + Android-клиент + агент-слой.

## Репозитории

| Каталог | Что это | Стек |
|---|---|---|
| `kwhale-v3/` | сервер + эталонный клиент-референс | Python 3.12, FastAPI, Postgres 16 (asyncpg), asyncio |
| `kwhale-v3/server/` | API `:19001`, воркер скачивания, MCP рекомендаций | см. ниже |
| `kwhale-android/` | Android-клиент | Kotlin, Compose M3, Media3, 4 модуля |
| `agent/` | агент-слой: парсеры плейлистов, bridge, MCP, скиллы | Python 3.11+, httpx, fastmcp |
| `playlist/`, `logs/`, `release/` | рабочие данные/артефакты (не код) | — |

Не трогать: `kwhale-v3/client/` (форк Lune — референс), `RE-архив` (исторические материалы, вне деревьев; бывшие RE-дампы
протоколов), `kwhale-android/re/` (RE-артефакты декомпиляции).

## Сервер: kwhale-v3/server

```
app/
├── main.py            # FastAPI, /v1 = публичный API (KWhale Core v1)
├── config.py          # settings, validate_security()
├── httpcore.py        # httpx-клиенты, per-host throttle, SOURCE_PROXY_*
├── auth.py            # scrypt-пароли, JWT, invite-only регистрация
├── schema.sql         # библиотека + users/tokens/invites/images/events
├── connectors/        # 9 источников — см. скилл kwhale-connectors
│   ├── base.py hybrids.py __init__.py (реестр)
│   └── icm|yandex_direct|soundcloud_direct|ytm_direct|ytmusic|deezer|zvuk|vk|qobuz|tidal + dash|deezer_crypto|qobuz_creds|ytdlp_helper
├── services/
│   ├── search_service.py  # fan-out по активным источникам → dedup → upsert
│   ├── stream_service.py  # local/кэш/proxy стримы (трансформы — в коннекторах)
│   ├── downloader.py      # asyncio-очередь download_jobs (ingest в библиотеку)
│   ├── playlists.py favorites.py library.py gc.py tagging.py
│   ├── normalize.py dedup.py providers.py (iTunes/Genius/Musixmatch)
│   └── rec/           # рекомендательный слой (ранкер, профиль, миксы, LLM-патчи)
├── v1/                # роутеры: auth, catalog, search, playlists, misc, uploads, images, admin
├── mcp_rec.py         # MCP рекомендаций (stdio: python -m app.mcp_rec)
├── indexer.py         # Essentia DSP (python -m app.indexer --enqueue --once)
└── tests/             # pytest, БД kwhale_test (guard от боевой!)
```

Ключевые факты:
- Один Track — много источников (`track_sources`); скачанное играет с диска.
- API-контракт: `kwhale-android/api/openapi.yaml` (44 пути, test_contract.py
  следит за дрейфом).
- Тесты: `cd kwhale-v3/server && .venv/bin/python -m pytest tests -q`
  (или в контейнере — см. AGENTS.md). Линтеры: `ruff check app tests`, `mypy app`.
- Запуск: `docker compose up -d --build` (api :19001, postgres :5433 dev).
- Живая бета крутится ОТДЕЛЬНО от тестового прогона: не перезапускать uvicorn
  и не трогать боевую БД `kwhale` (тесты пишут только в `kwhale_test`).

## Android: kwhale-android

```
app/            # UI (Compose): MainActivity, ui/screens, player (Media3), widget, download (WorkManager)
core/model/     # доменные модели
core/design/    # тема KwhaleTheme + каталог акцентов
core/network/   # KwhaleApi (retrofit-подобный), TokenStore, ApiClient (refresh-логика)
core/player/    # PlaybackState/плеер-хелперы
api/            # openapi.yaml + examples + mock (Prism)
docs/           # PARITY/REPORT/NATIVE (RE-доки, символы оригинала маскированы `orig`)
```

- Пакет `org.dueattendant149.kwhale`, applicationId тот же.
- Сборка: `JAVA_HOME=$HOME/toolbox/jdk-17 ./gradlew :app:assembleDebug :core:network:testDebugUnitTest`
  (toolchain 17; jdk-21 НЕ подходит — gradle ищет 17).
- Base URL клиента: debug → `http://127.0.0.1:19001/v1`, release → `https://music.dueattendant149.org/v1`.

## Агент-слой: agent/

```
kwhale_agent/
├── playlists/       # независимые парсеры: base|yandex|soundcloud|ytm|vk|ytdlp_fallback
├── bridge.py        # мост в /v1 API (поиск, плейлисты, скачивания)
├── importer.py      # acceptance: парсинг → матч → плейлист в профиле
└── mcp_server.py    # MCP-тулзы (python -m kwhale_agent.mcp_server)
tests/               # тест-стенд (без сети/БД)
scripts/smoke_playlists.py   # живой smoke парсеров (read-only)
skills/              # kwhale-codebase, kwhale-ops, kwhale-connectors, kwhale-proxy
```

- Парсеры НЕ зависят от серверных коннекторов (сначала тест-стенд → потом интеграция).
- Конфиг через env: `KWHALE_BASE_URL`, `KWHALE_EMAIL`, `KWHALE_PASSWORD`,
  `Kwhale_AGENT_VK_TOKEN`, `HTTPS_PROXY` (см. kwhale-proxy).
- Тесты: `cd agent && .venv/bin/python -m pytest tests -q` (17 tests).

## Типовые команды

- сервер: pytest / ruff / mypy (выше); live-smoke источников — `scripts/smoke_sources.py` в контейнере;
- android: gradlew assembleDebug / testDebugUnitTest;
- agent: pytest, `scripts/smoke_playlists.py <url>`, MCP — `python -m kwhale_agent.mcp_server`;
- журнал работ — `PLAN.md` в корне infra (бэкапы — `../infra-backups/`).

## Договорённости

- Перед правкой — бэкап по протоколу PLAN.md; одна правка — один пункт — тесты.
- Бренд: проект = KWhale; старые имена в код не возвращаем
  (в RE-доках символы оригинала маскированы `orig`).
- Секреты: `.env` (chmod 600, не коммитить); токены источников — только через
  `source_accounts` (AES-GCM).
