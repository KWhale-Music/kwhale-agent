---
name: kwhale-connectors
description: Полное руководство по коннекторам источников KWhale — контракт, регистрация, инфраструктура, cookbook по всем 9 платформам, stream-хуки, секреты, тесты. Достаточно, чтобы LLM воссоздала любой коннектор с нуля. Использовать при добавлении/правке/отладке коннекторов (kwhale-v3/server/app/connectors).
---

# Коннекторы KWhale — эталонное руководство

Коннектор = адаптер музыкального сервиса-источника. Всё протокольное знание
живёт в `kwhale-v3/server/app/connectors/` — по файлу на источник. Сервисные
слои (search/stream/downloader) не знают протоколов.

## 1. Контракт: `connectors/base.py`

```python
class Connector(ABC):
    name: str = "base"          # каноническое имя = имя в track_sources

    # обязательные
    async def is_available(self) -> bool          # можно ли аутентифицироваться сейчас
    async def search(self, query: str, limit: int) -> list[TrackMeta]
    async def resolve_stream(self, external_id: str) -> StreamInfo | None
    async def download(self, external_id: str, dest_dir: Path) -> tuple[Path, str] | None

    # учётные записи (аккаунтные источники)
    async def connect(self, payload: dict[str, str]) -> AccountState   # валидация введённых кредов
    async def check_account(self) -> AccountState                      # рефреш токенов
    async def keepalive(self) -> bool                                  # периодический пинг (ICM)

    # каталог (ленивые, дефолты — пустые/None)
    async def search_albums(self, query, limit) -> list[AlbumMeta]
    async def search_artists(self, query, limit) -> list[ArtistMeta]
    async def album_tracks(self, external_id) -> list[TrackMeta] | None
    async def artist_top_tracks(self, external_id, limit=20) -> list[TrackMeta] | None
    async def artist_albums(self, external_id, limit=50) -> list[AlbumMeta] | None
    async def album_track_number_by_source(self, external_id) -> int | None   # ICM

    # stream-хуки (трансформы — зона ответственности коннектора!)
    def needs_assembly(self, info: StreamInfo) -> bool        # сегментный стрим → собрать в файл
    async def assemble_stream(self, info: StreamInfo, dest: Path) -> None
    def stream_decoder(self, info: StreamInfo, url: str) -> Any | None  # потоковая дешифровка
```

**Dataclass'ы** (все в base.py):
- `TrackMeta`: connector, external_id, title, artists(list[str]), album, duration_sec,
  isrc, cover_url, quality_tier, year, track_number/total, disc_number/total,
  explicit, genre, raw: dict
- `AlbumMeta`: connector, external_id, title, artist_name, year, cover_url, track_count, genre, raw
- `ArtistMeta`: connector, external_id, name, cover_url, genre, raw
- `StreamInfo(url | file_path, mime, transform, segment_urls)` — transform:
  тег коннектора (`dash_concat`, `hls_concat`, `vk_hls`, `dzr_stripe`), сервис его
  НЕ интерпретирует — спрашивает хуки. `segment_urls` — готовые сегменты для concat.
- `AccountState(ok, status, message, profile, payload_updates)` — секреты только в
  `payload_updates` (сервис сам их зашифрует и сохранит).

**Tier-шкала** (формат > сервис): `TIER_LOCAL=100, TIER_HIREZ=95 (24-bit FLAC),
TIER_FLAC=85, TIER_MP3_320=65, TIER_MP3_128=50, TIER_AAC=40`.

## 2. Регистрация: `connectors/__init__.py`

```python
REGISTRY: dict[str, Connector] = {}
def get_connectors(): ...   # ленивая инициализация, _register() по каноническому имени
def get_connector(name): ...
```

Канонические имена (НЕ менять — это ключи в `track_sources`):
`icm, yandex, soundcloud, ytmusic, deezer, zvuk, vk, qobuz, tidal`.

Гибриды (`connectors/hybrids.py`): `yandex`/`soundcloud` = direct-варианты под
каноническим именем; `ytmusic` = InnerTube-поиск (ytm_direct) + yt-dlp стримы
(ytmusic.py) в одном классе, stream-хуки проксируются стримовому делегату.

## 3. Инфраструктура

- **HTTP**: `app/httpcore.py` — `httpcore.client(name)` (per-source клиент),
  `httpcore.proxy_for(name)` (читает `SOURCE_PROXY_<ИСТОЧНИК>` env, напр.
  `socks5h://singbox:2080`), `httpcore.throttle(host)` (per-host rate limit;
  значения восстановлены из RE-архива, см. `RateLimitInterceptor`),
  `httpcore.CHROME_UA`. ВАЖНО: тянуть httpcore из коннекторов — верхний уровень
  приложения, циклов нет; сервисы из коннекторов импортировать ВНУТРИ функций.
- **Кэш**: `services.search_service.cache_get/cache_put(key, connector, ttl_hours)` —
  TTL-кэш в таблице `search_cache`; использовать для ленивых fetch альбомов и т.п.
- **Секреты**: `services/source_accounts.py` — `SOURCE_SPECS` (label, auth-форма
  `cookie|token|password|env`, поля, справка → поднимается в `/admin`),
  `save_account` шифрует через `services/secrets.py` (AES-GCM, ключ
  `ACCOUNTS_ENC_KEY`). Секреты НИКОГДА не пишутся в логи/код — в логах URL
  обрезаются через `_safe_url` / strip query.
- **Аккаунты**: `enabled_connectors()` — какие источники участвуют в поиске
  (включает админ через `/admin`). `connect()` возвращает `AccountState` с
  `payload_updates` (новые токены/cookies) — сервис пересохраняет их сам.

## 4. Stream-хуки (трансформы)

Сервис (`services/stream_service.py`) спрашивает коннектор:

1. `connector.needs_assembly(info)` → True: `_assembled_response` пишет собранный
   файл в LRU-кэш `_stream_cache/` и отдаёт FileResponse. Внутри вызывается
   `connector.assemble_stream(info, part_path)` — коннектор сам решает КАК.
   - Tidal (`dash_concat`): `dash.assemble_concat(self.name, info, dest)` —
     data-uri/BTS/MPD манифест → список сегментов → `fetch_concat`.
   - SoundCloud (`hls_concat`): тот же `assemble_concat` с `segment_urls`.
   - VK (`vk_hls`): ffmpeg-сборка HLS (`_download_hls_ffmpeg`).
2. Иначе `_proxy_response` стримит URL; если `connector.stream_decoder(info, url)`
   возвращает объект с `.process(chunk, abs_offset)` — каждый чанк проходит через
   него (Deezer `dzr_stripe`: `deezer_crypto.StripeDecryptor`).
3. `download()` коннектора — всегда самостоятелен (сам собирает/дешифрует).

## 5. Cookbook по источникам

| Источник | Файл | Auth | Протокол / грабли |
|---|---|---|---|
| ICM | icm.py | Partner API key (env) | byicloud.online Partner API = Apple Music; всегда mp3 320 (LOSSLESS-флаг игнорируется); обязателен keepalive раз в сутки (`ICM_KEEPALIVE_HOURS`) |
| Яндекс | yandex_direct.py (+yandex.py fallback=lib) | OAuth-токен | прямой HTTP + HMAC `get-file-info`; ISRC не отдаёт; FLAC только с Plus; канонич. имя `yandex` |
| SoundCloud | soundcloud_direct.py (+soundcloud.py fallback=yt-dlp) | client_id (скрейпится из JS-бандлов sndcdn.com — перебирать ВСЕ бандлы!) | api-v2; стримы = HLS AAC (m3u8 → сегменты); токен из env протухает — fallback yt-dlp |
| YouTube Music | ytm_direct.py (поиск) + ytmusic.py (стримы yt-dlp) | — | InnerTube WEB_REMIX; n-param подпись НЕ расшифровываем (нужен внешний sig-сервис) — стримы через yt-dlp; AAC ~128k потолок |
| Deezer | deezer.py + deezer_crypto.py | cookie `arl` | gw-light (`search.music` → TRACK_TOKEN) + `media.get_url` → CDN URL `...#<SNG_ID>`; байты BF_CBC_STRIPE (Blowfish, каждый 3-й блок 2048B — `StripeDecryptor`); FLAC нужен Hi-Fi |
| Звук | zvuk.py | email/пароль | GraphQL поиск/batch + tiny REST; FLAC в MP4 (`.m4a`); free = MP3 128 |
| VK | vk.py | cookies `p`+`remixnttpid` → токены | `api.vk.ru/method/*`; SITE-токен через `act=web_token`; MUSIC/CALLS-токены best-effort (TODO verify); url стрима может быть `.m3u8` → `vk_hls` ffmpeg-сборка; альбомы/артисты без MUSIC-токена — пусто |
| Qobuz | qobuz.py + qobuz_creds.py | аккаунт (app_id/secret скрейпятся из play.qobuz.com bundle.js) | `api.json/0.2` + `request_sig` (md5); стриминг только с подпиской (гейт) |
| Tidal | tidal.py + dash.py | OAuth2 refresh token (client_id без секрета, scope r_usr w_usr) | `openapi.tidal.com/v2` JSON:API; `playbackinfo` → base64 манифест (MPD/BTS) → `dash_concat`; поиск/ISRC без Premium, стрим — Premium; DASH-сборка в dash.py |

## 6. Паттерны (обязательные)

1. **Импорты без циклов**: коннекторы импортируют сервисы ТОЛЬКО внутри функций
   (история: цикл `connectors → services → downloader → connectors`).
2. **Ленивые fetch**: `album_tracks/artist_*` — по требованию UI, кэш 24ч через
   `cache_put/cache_get`.
3. **Fallback-варианты**: медленный/ненадёжный протокол → держать второй класс
   (lib vs direct, native vs yt-dlp), выбор — в `hybrids.py` или через
   `is_available()`.
4. **URL в логи — без query** (`_safe_url`), секреты — мимо логов.
5. **Нормализация метаданных** — через `services/normalize.py`
   (feat-суффиксы, мульти-артисты `split_artists`, NFKC) — не писать своё.

## 7. Тесты и приёмка

1. **Юниты** — синтетические payload'ы, без сети (см. tests/test_qobuz.py,
   test_deezer_crypto.py, test_dash.py, test_hybrids.py, test_stream_transforms.py).
   Тестовая БД изолирована: `tests/conftest.py` → `kwhale_test` (guard от боевой!).
2. **Live-smoke**: `scripts/smoke_sources.py [--download]` в контейнере
   (анонимные проверки + по подключённым аккаунтам; без аккаунта — SKIP).
3. **Сравнение вариантов**: `scripts/compare_sources.py [--resolve]`.
4. Полный прогон: `python -m pytest tests -q` + `ruff check app tests` + `mypy app`.
5. Тир при resolve/download пересчитывается (формат реального файла > заявка поиска).

## 8. Чек-лист нового коннектора

- [ ] `connectors/<name>.py`: подкласс Connector, docstring с протоколом
- [ ] `connect()` + `check_account()` (если аккаунтный) + `SOURCE_SPECS` в source_accounts.py
- [ ] search/search_albums/search_artists + resolve_stream (+stream-хуки при сегментах)
- [ ] download() — самостоятельный (сборка/дешифровка внутри)
- [ ] регистрация в `get_connectors()` под каноническим именем
- [ ] `SOURCE_PROXY_<NAME>` в .env.example + документация в AGENTS.md
- [ ] юниты + smoke_sources + полный прогон зелёный
