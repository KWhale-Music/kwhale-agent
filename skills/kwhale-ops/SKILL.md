---
name: kwhale-ops
description: Операционный регламент LLM-агента поверх MCP kwhale-agent (и серверного MCP kwhale-recommendations) — интерактивный вход по пользовательскому URL и email/паролю, парсинг и перенос плейлистов, полное редактирование плейлистов, загрузка своих треков, скачивание, библиотека, миксы и шеринг. Активировать, когда пользователь просит работать со своим аккаунтом или музыкальной коллекцией в KWhale. Если MCP kwhale-agent не подключён — переключаться на скилл kwhale-api.
---

# KWhale-ops — работа агента через MCP

Основной MCP: `python -m kwhale_agent.mcp_server` (или команда `kwhale-agent-mcp`).
Рекомендательный MCP на стороне сервера (при наличии доступа к окружению сервера): `python -m app.mcp_rec` (`kwhale-recommendations`).

- **Никаких зашитых публичных доменов:** публичный URL инстанса задаёт пользователь. Если `KWHALE_BASE_URL` не задан в env, спроси URL и передай его в `login(email, password, base_url)`.
- **Вход строго по email:** сервер аутентифицирует по `email`, не по `username` (5 ошибок подряд за 5 минут → блокировка `429`). Никогда не выводи пароль или токены в ответ.
- **Нет MCP в окружении агента?** Выполни те же действия напрямую по HTTP с опорой на скилл `kwhale-api`.

## 1. Тулзы `kwhale-agent`

### Сессия и ориентирование
| Тулза | Назначение |
|---|---|
| `login(email, password, base_url?)` | вход по URL инстанса, email и паролю (в памяти сессии, без правки env) |
| `logout()` | отзыв refresh-токена и очистка сессии в памяти |
| `kwhale_status()` | health + config + активный `baseUrl` + текущий пользователь `/v1/me` |

### Парсинг и перенос внешних плейлистов
| Тулза | Назначение |
|---|---|
| `list_supported_platforms()` | поддерживаемые парсеры, алиасы, хосты, требования к auth |
| `detect_playlist_platform(ref)` | определение парсера по URL, пути файла или тексту списка |
| `parse_playlist(platform, ref)` | разбор URL/списка БЕЗ записи в KWhale (`yandex`, `soundcloud`, `ytm`, `vk`, `text`, `ytdlp`) |
| `parse_track_list(text, title?)` | разбор текста `Artist - Title`, CSV (Exportify/Spotify) или M3U/M3U8 |
| `import_playlist_to_profile(platform, ref, title?, playlist_id?, visibility?, dry_run?)` | перенос с параллельным поиском (`wait=true`), fallback по чистому названию и duration-проверкой; если задан `playlist_id` — дозапись только недостающих треков |

Поддерживаемые источники:
- `yandex` (публичные плейлисты и короткие редиректы; гидрация длинных плейлистов до 100 за батч);
- `soundcloud` (`soundcloud.com/.../sets/...` + короткие `on.soundcloud.com` / `/s/`);
- `ytm` (YouTube Music / YouTube плейлисты через InnerTube);
- `vk` (`KWHALE_AGENT_VK_TOKEN`, поддерживается legacy-алиас `Kwhale_AGENT_VK_TOKEN`; без токена — `ytdlp`);
- `text` (мультистрочные списки, CSV-экспорт из Spotify/Apple Music, M3U/M3U8);
- `ytdlp` (универсальный fallback для URL; проксируется через `YTDLP_PROXY` / `HTTPS_PROXY`).

### Полное управление плейлистами
| Тулза | Назначение |
|---|---|
| `list_playlists(owner="me")` | список своих (`me`) или всех видимых (`all`) плейлистов |
| `get_playlist(playlist_id)` | метаданные + **полный** список треков с пагинацией (>200 тоже) |
| `create_playlist(title, description?, visibility?)` | создание (`private|unlisted|public`) |
| `update_playlist(playlist_id, title?, description?, visibility?)` | переименование, описание, смена видимости |
| `delete_playlist(playlist_id)` | удаление плейлиста (только после явного подтверждения пользователя!) |
| `add_tracks_to_playlist(playlist_id, track_ids, position?)` | добавление треков чанками `<=500` (обходит лимит API `1000`) |
| `remove_track_from_playlist(playlist_id, track_id)` | удаление трека из плейлиста |
| `reorder_playlist_tracks(playlist_id, track_ids)` | задание нового порядка треков |
| `like_playlist_tracks(playlist_id)` | «лайкнуть все треки» → ставит скачивание недостающих файлов на сервер |

### Каталог, загрузка своих треков, библиотека, рекомендации, шеринг
| Тулза | Назначение |
|---|---|
| `search_tracks(query, limit=10, wait=true)` | поиск по 9 источникам; для полного результата оставлять `wait=true` |
| `get_track_details(track_id)` | `/info` (ISRC, битрейт/кодек, источники) + доступность текста `/lyrics` |
| `like_track(track_id, liked=true)` | лайк/анлайк (лайк триггерит серверный ingest-download) |
| `download_track(track_id, mode="library")` | `library` (на сервер через лайк) или `file` (в `KWHALE_DOWNLOAD_DIR`) |
| `download_status(track_ids)` | опрос `pending|downloading|ready|failed` |
| `upload_track(file_path, title?, artist?, album?)` | загрузка локального аудиофайла (`<=100MB`) в библиотеку (`POST /v1/uploads/tracks`) |
| `manage_enrichments(action="list|confirm|reject", proposal_id?)` | просмотр и подтверждение/отклонение обогащения загруженных треков |
| `list_library(section="tracks|playlists|albums|history", limit=50, query?)` | чтение лайков, плейлистов, альбомов и истории пользователя |
| `list_mixes()`, `get_mix_tracks(mix_id, limit=40)`, `prompt_mix(prompt, size=40)` | персональные и промпт-миксы |
| `create_share_link(kind, entity_id)` | публичная короткая ссылка `/share/s/<id>` на `track|album|artist` |

## 2. Серверный MCP `kwhale-recommendations` (для админа/сервера)

Запускается внутри `kwhale-v3/server`: `python -m app.mcp_rec`. Инструменты:
`list_mixes`, `mix_tracks`, `prompt_mix`, `explain_prompt_mix` (полный `QueryPlan` + audio/tag фичи), `similar_tracks`, `get_scoring_profile`, `set_scoring_profile`, `refresh_stats`.

## 3. Типовые сценарии агента

### Сценарий A — Подключение нового пользователя (есть только URL, email, пароль)
1. Проверь `kwhale_status()`. Если `explicitBaseUrl=false` или `me.authorized=false`, запроси у пользователя URL сервера, `email` и `password`.
2. Вызови `login(email, password, base_url)` — URL автоматически нормализуется с `/v1`, в памяти сохранятся access и refresh токены.

### Сценарий B — Перенос плейлиста
1. Вызови `detect_playlist_platform(ref)`:
   - Если ссылка на Spotify/Apple Music или приватный плейлист упала — сообщи прямо, предложи открыть публичный доступ или попросить пользователя вставить список `Artist - Title` / CSV-экспорт (и распарсь через `parse_track_list` / `platform="text"`).
2. Вызови `parse_playlist(platform, ref)` — покажи пользователю заголовок, количество треков, флаг `truncated` (если платформа урезала), первые позиции. Получи подтверждение перед записью.
3. Проверь `list_playlists("me")` — уточни, создавать новый или дописать в существующий (`playlist_id`).
4. Вызови `import_playlist_to_profile(...)` и передай краткий отчёт (`matchedCount/unmatchedCount`, `playlistId`).
5. Для позиций из `unmatched`:
   - Попробуй альтернативный запрос в `search_tracks` (транслит, без фитов/ремиксов) и докинь найденные `trackId` через `add_tracks_to_playlist(playlist_id, [...])`!
   - Если трека нет ни в одном источнике — предложи загрузить локальный аудиофайл через `upload_track`.
6. По запросу пользователя вызови `like_playlist_tracks(playlist_id)` для кеширования треков в библиотеку сервера.

### Сценарий C — Редактирование существующих плейлистов и загрузка файлов
- Перед `delete_playlist`, массовым `remove_track_from_playlist` или `reorder_playlist_tracks` сначала прочти актуальное состояние через `get_playlist(playlist_id)` и подтверди деструктивные изменения у пользователя.
- После `upload_track(file_path, ...)` проверь `manage_enrichments("list")` и согласуй подтверждение предложенных метаданных с пользователем.
- Не вызывай массово `download_track(..., mode="library")` на сотнях треков без спроса пользователя.
