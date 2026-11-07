# kwhale-agent — агент-слой KWhale

Пак скиллов + MCP для работы LLM-агента с KWhale: ориентация в кодовой базе,
ручные поиски/скачивания, парсинг плейлистов из названных пользователем
платформ и перенос их в профиль KWhale.

## Структура

```
kwhale_agent/
├── playlists/        # независимые парсеры платформ (не трогают серверные коннекторы!)
│   ├── base.py       # TrackRef/ParsedPlaylist + нормализация + fuzzy-match
│   ├── yandex.py     # публичный JSON API, без auth
│   ├── soundcloud.py # api-v2 + скрейп client_id (из RU — через прокси)
│   ├── ytm.py        # InnerTube WEB_REMIX browse
│   ├── vk.py         # audio.get (нужен Kwhale_AGENT_VK_TOKEN)
│   └── ytdlp_fallback.py  # любая ссылка через yt-dlp (опциональная зависимость)
├── bridge.py         # мост в /v1 API (поиск, плейлисты, скачивания) — только публичный API
├── importer.py       # acceptance-логика: парсинг → матч → плейлист в профиле
└── mcp_server.py     # MCP (stdio): python -m kwhale_agent.mcp_server
tests/                # тест-стенд: 21 test, без сети и БД
scripts/smoke_playlists.py   # живой read-only smoke парсеров
skills/               # kwhale-codebase, kwhale-ops, kwhale-connectors, kwhale-proxy
```

## Установка и запуск

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"      # + ".[fallback]" для yt-dlp
.venv/bin/python -m pytest tests -q                              # тест-стенд
.venv/bin/python scripts/smoke_playlists.py <playlist-url>       # живой smoke
.venv/bin/python -m kwhale_agent.mcp_server                      # MCP (stdio)
```

MCP зарегистрирован в `../.opencode/opencode.json`; скиллы подключены
симлинками в `../.opencode/skills/`.

## Конфигурация (env)

| Переменная | Назначение |
|---|---|
| `KWHALE_BASE_URL` | API KWhale (дефолт `http://127.0.0.1:19001/v1`) |
| `KWHALE_EMAIL` / `KWHALE_PASSWORD` | аккаунт для операций с профилем |
| `KWHALE_DOWNLOAD_DIR` | куда складывать файлы (`download_track mode=file`) |
| `Kwhale_AGENT_VK_TOKEN` | токен VK для нативного парсинга VK-плейлистов |
| `HTTPS_PROXY` | прокси для парсеров из RU (см. скилл kwhale-proxy) |

## MCP-тулзы

`list_supported_platforms`, `detect_playlist_platform`, `parse_playlist`,
`import_playlist_to_profile` (acceptance), `search_tracks`, `download_track`,
`download_status`, `kwhale_status`.

Сценарии — скилл `kwhale-ops`. Правило: импорт в профиль — только с подтверждения
пользователя; ошибки тулзы отдают `{"error": ...}`, а не падают.

## Дизайн-решения

- **Парслеры независимы от серверных коннекторов** — сначала тест-стенд
  (`tests/`, `scripts/smoke_playlists.py`), потом интеграция; серверный код не
  меняется.
- **Интеграция только через публичный API** (`/v1`): поиск, создание плейлистов,
  добавление треков. Скачивание в библиотеку = `PUT /tracks/{id}/like`
  (семантика сервиса: лайк ставит ingest-джобу).
- Матч треков: fuzzy «artist - title» (порог 62) + точный ISRC.

## Приёмка (пройдена 2026-11-07)

Сценарий «перенеси плейлист с Яндекс Музыки в профиль KWhale» выполнен через
MCP-тулзы end-to-end: `music.yandex.ru/users/414787002/playlists/1024`
(«Джаз: лучшее», 100 треков) → **98 совпадений** в каталоге → плейлист
**id=13 «Джаз: лучшее (Yandex)» (97 уникальных треков)** в профиле
`dueattendant149`; 2 трека честно в unmatched («no catalog match»).
Живой smoke парсера Яндекса: 100/100 треков разобраны.
