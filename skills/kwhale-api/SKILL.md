---
name: kwhale-api
description: Самодостаточный HTTP-протокол KWhale Core v1 (/v1) для LLM-агента без MCP или без доступа к репозиторию сервера — аутентификация (email/password + refresh), поиск (?wait=true), полный CRUD/редактирование плейлистов, загрузка своих треков, библиотека, лайки, миксы, события и шеринг. Активировать, когда агент работает с пользовательскими данными KWhale напрямую через HTTP или когда MCP kwhale-agent не подключён.
---

# KWhale Core v1 — HTTP API для LLM-агента

Использовать этот скилл, когда агент взаимодействует с сервисом KWhale от имени пользователя **напрямую по HTTP** (curl / Python `httpx` / JS `fetch`), без доступа к локальной БД, без `/admin` и независимо от наличия MCP.

> **Важно:** на публичных инстансах `/openapi.json`, `/docs` и `/redoc` часто закрыты обратным прокси (отдают `404`). Опирайся на этот контракт, а не на скачивание схемы.

## 1. Адрес инстанса и аутентификация

1. **URL задаёт пользователь.** Никогда не угадывай и не зашивай публичный домен. Если `KWHALE_BASE_URL` не передан в окружении/контексте, запроси у пользователя адрес сервиса и нормализуй суффикс до `<origin>/v1` (без завершающего `/`).
2. **Вход принимает строго `email` (НЕ `username`):**
   - `POST /v1/auth/login` → `{"email": "<email>", "password": "<password>"}`
   - Ответ `200`: `{"accessToken": "<jwt>", "refreshToken": "<opaque>", "expiresIn": 900, "tokenType": "Bearer", "user": {...}}`
   - Throttle: **5 неудачных попыток за 300 с с одного IP → `HTTP 429 rate_limited`**. Не ретраить неверный пароль в цикле.
3. **Регистрация (invite-only):**
   - `POST /v1/auth/register` → `{"email", "password" (>=8), "displayName", "inviteToken"}` → `201 AuthResponse`.
4. **Продление и выход:**
   - Access JWT живёт ~15 минут; при `401 token_expired` вызови `POST /v1/auth/refresh` с `{"refreshToken": "<rt>"}` (refresh одноразовый — сохрани новый `refreshToken` из ответа).
   - `POST /v1/auth/logout` → `{"refreshToken": "<rt>"}` → `204`.
   - Заголовок на всех защищённых ручках: `Authorization: Bearer <accessToken>`.
5. **Конфиденциальность:** пароли и токены никогда не печатай в ответы пользователю и не сохраняй в текстовые логи.

## 2. Базовые правила контракта `/v1`

- Все `id` в JSON — **строки** (`"123"`). Поля в `camelCase`.
- Один origin: пути из JSON (`/v1/images/{id}`, `/v1/tracks/{id}/stream`) относительны выбранного `<origin>`; не ходи напрямую на сторонние CDN.
- Пагинация: `?cursor=<opaque>&limit=<1..100>` → `{"items": [...], "nextCursor": "..." | null}`. Повторяй с `cursor=nextCursor`, пока `nextCursor` не `null`.
- Ошибки: RFC 7807 `application/problem+json` → `{"type", "title", "status", "detail", "code", "fields"}`.
- Идемпотентность: передавай заголовок `Idempotency-Key: <uuid4>` для `POST /playlists`, `POST /playlists/{id}/tracks`, `PUT /albums/{id}/tracks/like`, `PUT /playlists/{id}/tracks/like`, `POST /tracks/{id}/censorship`.

## 3. Полная карта ручек пользователя

### Профиль и сервис
- `GET /v1/health` → `{"status":"ok"}` (без auth — используй первой проверкой доступности URL)
- `GET /v1/config` → лимиты (`maxPlaylistTracks`, `maxUploadBytes`, `eventBatchSize`) и `media.supportedFormats`
- `GET /v1/me`, `PATCH /v1/me` `{"displayName": "..."}` → профиль `User`

### Поиск каталога (критический параметр `wait=true`)
- `GET /v1/search?q=<query>&type=all|tracks|albums|artists|playlists|mixes&limit=<1..100>&wait=true`
  - **Правило:** при программном поиске и переносе плейлистов **всегда** передавай `wait=true`! По умолчанию (`wait=false`) сервер ждёт первую волну коннекторов лишь `1.5 с` и возвращает `partial=true`; с `wait=true` дожидается медленных/зарубежных источников (до `8 с`).
- `GET /v1/search/suggestions?q=<prefix>`
- `GET /v1/search/history`, `DELETE /v1/search/history` (`204`)

### Треки: инфо, тексты, реакции, скачивание, загрузка
- `GET /v1/tracks/{trackId}` → `Track` (`isLiked`, `isDownloaded`, `downloadStatus`: `pending|downloading|ready|failed`)
- `GET /v1/tracks/{trackId}/info` → `{"track", "isrc", "quality", "sources": [{"connector", "available", "qualityTier"}]}`
- `GET /v1/tracks/{trackId}/lyrics` → `{"plain", "synced": [{"startMs", "endMs", "text"}]}`
- `GET /v1/tracks/{trackId}/similar?limit=40` → список `TrackRecommendation`
- `GET` / `HEAD /v1/tracks/{trackId}/stream` → поток аудио (`Range` / `206`, `Bearer` или `?exp=&sig=`)
- `GET /v1/tracks/{trackId}/download` → файл аудио (`Content-Disposition: attachment`)
- `PUT /v1/tracks/{trackId}/like` (`204`) — лайкает **и ставит скачивание в локальную библиотеку сервера** (если файла ещё нет); `DELETE /v1/tracks/{trackId}/like` (`204`)
- `PUT` / `DELETE /v1/tracks/{trackId}/dislike` (`204`)
- `POST /v1/tracks/{trackId}/censorship` `{"reason", "comment", "positionMs"}` / `DELETE .../censorship`

### Загрузка своих аудиофайлов и подтверждение обогащения
- `POST /v1/uploads/tracks` — `multipart/form-data`:
  - `file` (обязательно, макс. `100 MB`, расширения: `.mp3`, `.flac`, `.m4a`, `.mp4`, `.ogg`, `.opus`, `.wav`, `.aac`)
  - опциональные form-поля: `title`, `artist`, `album` (помогают, если у файла пустые ID3/Vorbis теги или не сработал Shazam/AcoustID фингерпринт; при провале матчинга вернёт `422 validation_failed`).
  - успешный ответ: `201 Track` (помечается `permanent=true`, сервер в фоне ищет предложения обогащения метаданных).
- `GET /v1/uploads/enrichments` → `{"items": [...]}` (ожидающие предложения метаданных)
- `POST /v1/uploads/enrichments/{proposalId}/confirm` / `.../reject`

### Плейлисты: создание и полное редактирование
- `GET /v1/playlists?owner=me|all&cursor=&limit=` → `PlaylistsPage`
- `POST /v1/playlists` (`Idempotency-Key`) → `{"title": "...", "description": "...", "visibility": "private|unlisted|public"}` → `201 Playlist`
- `GET /v1/playlists/{playlistId}` → `Playlist` (**внимание:** поле `tracks` обрезано первыми **200** треками! Для плейлистов >200 треков читай пагинацию `GET /v1/playlists/{playlistId}/tracks?cursor=&limit=100`)
- `PATCH /v1/playlists/{playlistId}` → `{"title"?, "description"?, "visibility"?}`
- `DELETE /v1/playlists/{playlistId}` → `204` (только с подтверждения пользователя)
- `POST /v1/playlists/{playlistId}/tracks` (`Idempotency-Key`) → `{"trackIds": ["1", "2", ...], "position"?: 0}`
  - **Лимит:** максимум **1000** ID за один POST! Длинные списки режь чанками (по 200–500 шт.). Дубликаты сервер пропускает идемпотентно.
- `DELETE /v1/playlists/{playlistId}/tracks/{trackId}` → `204`
- `PUT /v1/playlists/{playlistId}/tracks/order` → `{"trackIds": [...]}` (до `5000` ID; неуказанные треки остаются в хвосте в прежнем порядке)
- `POST /v1/playlists/{playlistId}/cover` (`multipart` image `<= 10 MB`) / `DELETE .../cover` (`204`)
- `PUT` / `DELETE /v1/playlists/{playlistId}/follow` (`204`)
- `PUT /v1/playlists/{playlistId}/tracks/like` (`Idempotency-Key`) → `202 LikeAllResult {"requested", "liked", "alreadyLiked", "queued", "failed"}` (лайк + скачивание всего плейлиста на сервер)

### Альбомы, артисты, библиотека, рекомендации, шеринг
- `GET /v1/albums/{id}`, `/albums/{id}/tracks`, `PUT/DELETE /albums/{id}/like`, `PUT /albums/{id}/tracks/like` (`202`)
- `GET /v1/artists/{id}`, `/artists/{id}/albums`, `/artists/{id}/tracks` (все известные треки в БД), `/artists/{id}/top-tracks`, `POST/GET /artists/{id}/sync`, `PUT/DELETE /artists/{id}/like`
- `GET /v1/home`
- `GET /v1/library/tracks?cursor=&limit=&sort=default|added|title|artist&q=`, `GET /v1/library/playlists`, `GET /v1/library/albums`
- `GET /v1/history`, `DELETE /v1/history` (`204`)
- `GET /v1/recommendations/top-artists|genres|onboarding`, `PUT /v1/recommendations/onboarding`
- `GET /v1/mixes`, `GET /v1/mixes/{mixId}/tracks`, `POST /v1/mixes/prompt` `{"prompt", "size"?: 40, "llmApiKey"?, "llmEndpoint"?, "llmModel"?}`
- `POST /v1/share` `{"kind": "track|album|artist", "id": "..."}` → `ShareLink` (`shareUrl`, `cardUrl`, `deepLink`, `platforms`); `GET /v1/share/{shareId}`
- `GET /v1/images/{imageId}?size=xs|sm|md|lg|original` (обложки)
- `POST /v1/events` `{"events": [...]}` (`<= 100`, `202`)

## 4. Алгоритм переноса плейлиста без MCP

1. **Проверить параметры:** убедись, что от пользователя получены `base_url`, `email`, `password` и источник (публичная ссылка / текст `Artist - Title` / CSV / M3U).
2. **Получить треклист источника:**
   - **Яндекс Музыка** (публичный плейлист): `GET https://api.music.yandex.net/users/{uid}/playlists/{kind}` с заголовком `X-Yandex-Music-Client: YandexMusicAndroid/24023231` (короткие ссылки сначала развернуть редиректом).
   - **YouTube Music**: `POST https://music.youtube.com/youtubei/v1/browse?prettyPrint=false` или модуль парсера `kwhale_agent.playlists`.
   - **Spotify / Apple Music / приватные подборки / «Мне нравится»**: нативно без пользовательской авторизации не скрейпятся. Попроси пользователя либо открыть временный публичный доступ, либо экспортировать список (CSV через Exportify / список строк `Исполнитель - Название`).
3. **Залогиниться и проверить существующие плейлисты:** `POST /v1/auth/login` → `GET /v1/playlists?owner=me` (чтобы при дозаписи не плодить дубли).
4. **Сматчить треки через поиск (`wait=true`):**
   - Для каждого трека: `GET /v1/search?q=<artist> <title>&limit=10&wait=true`.
   - Оценка кандидата: точное совпадение `isrc` → 100%; иначе сравнение нормализованных `artist - title` с контролем длительности (`durationMs` отличается `>30с` → штраф, чтобы ремикс/сниппет не перебил оригинал).
   - Если основной запрос ничего не дал — второй запрос без хвостов `(feat. ...)`, `(Remaster)`, `(Explicit)` и только с первым артистом.
5. **Показать пользователю preview и дождаться подтверждения**, если плейлист создаётся впервые и содержит много треков или часть не найдена.
6. **Создать/дополнить плейлист чанками `<=500` ID с `Idempotency-Key`**, вернуть отчёт: `playlistId`, `matchedCount`, `unmatchedCount`, список `unmatched` с предложением найти вручную или загрузить свой файл через `POST /v1/uploads/tracks`. По желанию пользователя вызвать `PUT /v1/playlists/{id}/tracks/like` для скачивания на сервер.
