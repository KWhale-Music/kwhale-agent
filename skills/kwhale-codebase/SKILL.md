---
name: kwhale-codebase
description: Карта кодовой базы KWhale для LLM-агента — модули сервера (kwhale-v3), Android-клиента (kwhale-android), агент-слоя (agent/) и публикационного комплекта (release/), команды сборки/тестов и инварианты. Активировать в начале любой работы с исходным кодом проекта.
---

# KWhale — карта кодовой базы

Переносимая карта относительно корня проекта `<kwhale-root>/`: все пути ниже указаны от корня `kwhale/` без привязки к локальной ФС.
Сервис: self-hosted музыкальный агрегатор 9 источников + локальная библиотека + Android-клиент + агент-слой.

## Каталоги проекта

| Каталог | Что это | Стек |
|---|---|---|
| `kwhale-v3/` | сервер + БД-схема + админка + индексатор | Python 3.12, FastAPI, Postgres 16 + pgvector (`asyncpg`), `asyncio` |
| `kwhale-android/` | Android-клиент | Kotlin 2.1, Compose Material 3, Media3, 5 Gradle-модулей |
| `agent/` | агент-слой: парсеры плейлистов, HTTP-bridge, MCP, скиллы | Python 3.11+, `httpx[socks]`, `fastmcp`, опционально `yt-dlp` |
| `release/` | публикационный self-hosted комплект (CLI `kwhale`, `compose`, `server/`, `agent/`, APK) | Docker / Podman + OpenCode config template |
| `docs/` | архитектурные доки (`EDGE_INFRASTRUCTURE.md`, `ONBOARDING_NEW_SERVICE.md`, исторический UI-архив) | Markdown |
| `builds/` | локальные артефакты APK (не исходники) | — |

Не изменять сторонние/референсные архивы (если присутствуют рядом): `kwhale-v3/client_NOT_USE/` (референсный Android-форк), `kwhale-android/re/` и внешние RE-дампы.

## Сервер: `kwhale-v3/server/`

```text
app/
├── main.py             # FastAPI entrypoint, lifespan, CORS, error handlers, /healthz
├── config.py           # env-настройки, validate_security(), SOURCE_PROXY_*
├── auth.py             # scrypt-пароли, access JWT (15m) + refresh rotation (30d), invite-only
├── httpcore.py         # пулы httpx, per-host rate limiter, SOURCE_PROXY_*
├── schema.sql          # схема таблиц + pgvector
├── public_share.py     # публичный SSR роутер /share/* (OG-карточки, TTL 7д)
├── connectors/         # 9 источников — детали в скилле kwhale-connectors
│   ├── base.py hybrids.py __init__.py
│   └── icm | yandex_direct (+yandex) | soundcloud_direct (+soundcloud) | ytm_direct (+ytmusic) | deezer | zvuk | vk | qobuz | tidal + dash | deezer_crypto | qobuz_creds | ytdlp_helper
├── services/
│   ├── search_service.py   # fan-out, first-wave (1.5с) vs wait=true (8с) + upsert + search_cache
│   ├── stream_service.py   # локальный Range / проксирование / DASH+HLS сборка / Deezer дешифровка
│   ├── downloader.py       # asyncio-очередь download_jobs
│   ├── manual.py           # ручные загрузки и _dropbox/ (fingerprint → upsert → finalize)
│   ├── enrichment.py       # предложения обогащения метаданных загруженных треков
│   ├── dedup.py            # ISRC + normalized(artist+title)+duration ±2с (ICM > quality)
│   ├── normalize.py tagging.py providers.py (iTunes/Genius/Musixmatch)
│   ├── playlists.py favorites.py library.py collections.py albums.py artists.py
│   ├── share_service.py share_card.py gc.py maintenance.py repair.py quality.py releases.py
│   └── rec/                # рекомендательный движок (scoring, profile, candidates, mixes, llm, stats, queue)
├── v1/                 # публичный контракт /v1 (auth, catalog, search, playlists, share, misc, uploads, images) + admin
├── mcp_rec.py          # MCP рекомендаций (stdio: python -m app.mcp_rec)
├── indexer.py          # Essentia DSP + тегирование (python -m app.indexer --enqueue --once)
└── tests/              # pytest против изолированной тестовой БД (kwhale_test)
```

Ключевые факты сервера:
- API-контракт: `kwhale-android/api/openapi.yaml` (**56 paths, 64 schemas**, OpenAPI 3.1). `test_contract.py` контролирует расхождения с роутерами; подробный разбор ручек для агента — в скиллах `kwhale-api` и `kwhale-ops`.
- Однопоточный `http://127.0.0.1:19001/v1` (или адрес пользовательского прод-прокси): обложки и потоки проксируются через один origin без 302 наружу.
- Команды сервера:
  - Тесты: `cd kwhale-v3/server && .venv/bin/python -m pytest tests -q` (только в `kwhale_test`, никогда не писать тесты в боевую БД).
  - Линтеры: `.venv/bin/ruff check app tests` и `.venv/bin/python -m mypy ...`.
  - Админские CLI: `python -m app.repair --dry-run` (слияние дублей), `python -m app.quality --scan`, `python -m app.indexer --enqueue --once`.

## Android-клиент: `kwhale-android/`

```text
core/model/     # чистые JVM-модели (Track, Album, Artist, Playlist)
core/design/    # KwhaleTheme (M3, Dark/Light/AMOLED/Monet, 129 акцентов, VK Sans)
core/player/    # PlaybackState (чистый JVM)
core/network/   # KwhaleApi, ApiClient (refresh-on-401), HostPolicyInterceptor, DTO
app/            # UI (Compose), Media3Player + PlaybackService, DownloadWorker, Glance Widget
api/            # openapi.yaml + mock (Prism)
```

- Пакет `org.dueattendant149.kwhale`. `debug` URL по умолчанию указывает на LAN-dev хост; `release` URL настраивается при сборке через `BuildConfig.API_BASE_URL` в `app/build.gradle.kts`.
- Проверки: `JAVA_HOME=<path-to-jdk17> ./gradlew :app:testDebugUnitTest :core:network:testDebugUnitTest --no-daemon -Dorg.gradle.workers.max=2`.

## Агент-слой: `agent/`

```text
kwhale_agent/
├── playlists/        # standalone парсеры: base|yandex|soundcloud|ytm|vk|textlist|ytdlp_fallback
├── bridge.py         # async HTTP-мост в /v1 API (auth/refresh, search?wait=true, playlists CRUD, uploads, mixes, shares)
├── importer.py       # параллельный матч (ISRC + duration + fallback) → создание/дозапись плейлиста
└── mcp_server.py     # stdio MCP kwhale-agent (python -m kwhale_agent.mcp_server / kwhale-agent-mcp)
scripts/smoke_playlists.py   # read-only smoke парсеров
tests/                       # 36 изолированных юнит-тестов без сети и БД
skills/                      # переносимый пак скиллов: kwhale-api, kwhale-ops, kwhale-codebase, kwhale-connectors, kwhale-proxy
```

- Команды агента:
  - Установка: `cd agent && python3 -m venv .venv && .venv/bin/pip install -e ".[dev,fallback]"`
  - Тесты: `cd agent && .venv/bin/python -m pytest tests -v`
  - Подключение к MCP-клиенту: см. шаблон `release/.opencode/opencode.json.example` (симлинки скиллов в `release/.opencode/skills/`).
- Конфигурация (может задаваться через env или интерактивно через MCP `login` — публичный URL всегда задаёт пользователь):
  - `KWHALE_BASE_URL`, `KWHALE_EMAIL`, `KWHALE_PASSWORD`, `KWHALE_DOWNLOAD_DIR`, `KWHALE_AGENT_VK_TOKEN` (и legacy `Kwhale_AGENT_VK_TOKEN`), `HTTPS_PROXY` / `YTDLP_PROXY`.

## Правила изменений, БД и релиза

- **Сохранность БД (красные линии):**
  - Перед любыми миграциями/операциями с БД сделать проверенный бэкап: `./kwhale backup` (внутри `pg_dump -Fc` + валидация `pg_restore -l` ключевых таблиц; удалять битый дамп вместо 20-байтных заглушек).
  - Восстановление — только через `./kwhale restore <dump>` или staging-БД (`kwhale_restore`) с `psql -v ON_ERROR_STOP=1`, проверкой таблиц (`tracks`, `users`, `favorites`, `playlists`) и атомарным `ALTER DATABASE ... RENAME`. **Никогда** не запускать `docker compose down -v`, не удалять volume `pgdata` и не проливать `pg_restore --clean` поверх прод-БД при ошибках.
  - Инвариант `schema.sql` / `db.py`: вызовы `public.unaccent`, `public.artist_norm`, `public.artist_tokens`, `public.artist_norm_imm`, `public.artists_text_imm` в функциях и `GENERATED ALWAYS` обязаны явно ссылаться на `public.*`, чтобы дамп корректно восстанавливался под `search_path = ''` из `pg_dump`.
  - При пересоздании docker-сетей с внешним reverse-proxy проверять подключение прокси-контейнера к compose-сети стека. Подробный runbook (если доступен в репозитории проекта): `docs/OPS_AND_RECOVERY.md`.
- Одна правка — одна задача — прогон релевантных тестов (`kwhale-v3/server` строго в `kwhale_test`).
- Обязательная синхронизация `release/` (см. также `kwhale-v3/AGENTS.md`):
  - изменения в `kwhale-v3/server/` → синхронизировать `release/server/`;
  - изменения в `agent/` → синхронизировать `release/agent/`, симлинки `release/.opencode/skills/`, архив `release/agent.zip`, при необходимости `release/README.md` и `release/kwhale`.
- Секреты (`.env`, токены источников, пароли пользователей) никогда не коммитить и не логировать; старые имена стороннего бренда в код не возвращать.
