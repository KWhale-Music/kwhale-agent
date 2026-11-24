# kwhale-agent — агент-слой KWhale

Переносимый набор **LLM-скиллов**, **standalone-парсеров плейлистов** и **MCP-сервера** для полного управления данными пользователя и кодовой базой KWhale: от переноса плейлистов и загрузки локальных треков до редактирования коллекций, рекомендаций и шеринга.

## Структура

```text
agent/
├── kwhale_agent/
│   ├── playlists/           # независимые парсеры (без зависимости от сервера)
│   │   ├── base.py          # TrackRef/ParsedPlaylist, нормализация, strip_match_noise
│   │   ├── yandex.py        # публичные плейлисты Яндекс Музыки + редиректы + догидрация >150
│   │   ├── soundcloud.py    # api-v2 + скрейп client_id + on.soundcloud.com/s/ редиректы
│   │   ├── ytm.py           # YouTube Music InnerTube WEB_REMIX
│   │   ├── vk.py            # VK audio.get (KWHALE_AGENT_VK_TOKEN / Kwhale_AGENT_VK_TOKEN)
│   │   ├── textlist.py      # списки 'Artist - Title', CSV (Exportify/Spotify), M3U/M3U8
│   │   └── ytdlp_fallback.py # универсальный fallback по URL через yt-dlp (+ YTDLP_PROXY/HTTPS_PROXY)
│   ├── bridge.py            # async HTTP-мост в /v1 API (login/refresh, search?wait=true, playlists CRUD, uploads, mixes, share)
│   ├── importer.py          # параллельный матч (ISRC + duration + fallback) → новый или существующий плейлист
│   └── mcp_server.py        # stdio MCP (python -m kwhale_agent.mcp_server / kwhale-agent-mcp)
├── scripts/smoke_playlists.py # read-only smoke парсеров
├── tests/                     # изолированный тест-стенд без сети и БД
└── skills/                    # переносимый пак скиллов для любого LLM-агента:
    ├── kwhale-api/            # прямой /v1 HTTP-протокол без MCP (для внешнего агента)
    ├── kwhale-ops/            # операционные сценарии поверх MCP + ссылка на kwhale-api
    ├── kwhale-codebase/       # переносимая карта репозитория
    ├── kwhale-connectors/     # внутренний контракт 9 серверных коннекторов
    └── kwhale-proxy/          # sing-box и проксирование источников
```

## Установка и подключение к агенту

```bash
cd agent
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,fallback]"   # ставит httpx[socks], fastmcp, pytest, yt-dlp
.venv/bin/python -m pytest tests -v          # проверка тест-стенда без сети
.venv/bin/python -m kwhale_agent.mcp_server  # запуск MCP (stdio)
```

Подключение пака к OpenCode / MCP-клиенту:
- Скиллы можно подключать отдельно и переносимо — скопируй или прилинкуй подпапки `agent/skills/*` в каталог скиллов своего агента (например `.opencode/skills/`).
- Шаблон конфига MCP лежит в `../release/.opencode/opencode.json.example`. В нём задаются путь к `<path-to-agent>/.venv/bin/python` и при желании env-параметры.
- Для подключения внешнего агента **без MCP** достаточно приложить скилл `skills/kwhale-api/SKILL.md` — публичный URL сервиса, email и пароль агент запросит у пользователя сам (на проде `/openapi.json` и `/docs` могут отдавать `404`).

## Конфигурация (опционально через env, или через MCP `login`)

| Переменная | Назначение |
|---|---|
| `KWHALE_BASE_URL` | API URL инстанса (пользовательский публичный URL с `/v1`; локальный пример: `http://127.0.0.1:19001/v1`) |
| `KWHALE_EMAIL` / `KWHALE_PASSWORD` | учётные данные аккаунта (вход строго по **email**, не по `username`) |
| `KWHALE_DOWNLOAD_DIR` | каталог для `download_track(mode="file")` (по умолчанию `./downloads`) |
| `KWHALE_AGENT_VK_TOKEN` | токен VK для `VkPlaylistParser` (поддерживается legacy-алиас `Kwhale_AGENT_VK_TOKEN`) |
| `HTTPS_PROXY` / `YTDLP_PROXY` | прокси для парсеров и `ytdlp_fallback` (см. скилл `kwhale-proxy`) |

Если `KWHALE_BASE_URL`, `KWHALE_EMAIL` и `KWHALE_PASSWORD` не заданы в env заранее, LLM-агент должен запросить их у пользователя и вызвать MCP-тулзу `login(email, password, base_url)` (либо выполнить `POST /v1/auth/login` по скиллу `kwhale-api`).

## Возможности MCP `kwhale-agent`

- **Auth и инфо:** `login`, `logout`, `kwhale_status`
- **Парсинг и перенос плейлистов:** `list_supported_platforms`, `detect_playlist_platform`, `parse_playlist`, `parse_track_list`, `import_playlist_to_profile` (новый плейлист или дозапись в `playlist_id`, `dry_run`)
- **CRUD и редактирование плейлистов:** `list_playlists`, `get_playlist` (полная пагинация >200 треков), `create_playlist`, `update_playlist`, `delete_playlist`, `add_tracks_to_playlist` (батчинг до 500 при серверном лимите 1000), `remove_track_from_playlist`, `reorder_playlist_tracks`, `like_playlist_tracks`
- **Каталог, загрузки и библиотека:** `search_tracks` (с `wait=true` по умолчанию), `get_track_details`, `like_track`, `download_track`, `download_status`, `upload_track`, `manage_enrichments`, `list_library`
- **Рекомендации и шеринг:** `list_mixes`, `get_mix_tracks`, `prompt_mix`, `create_share_link`
