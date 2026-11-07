---
name: kwhale-ops
description: Операционные сценарии агента поверх kwhale MCP — поиск и скачивание треков, парсинг плейлистов из названной пользователем платформы, перенос плейлиста в профиль KWhale (acceptance-сценарий), статусы загрузок. Использовать, когда пользователь просит найти/скачать музыку или перенести плейлист в KWhale.
---

# KWhale-ops — сценарии поверх MCP

MCP-сервер: `python -m kwhale_agent.mcp_server` (stdio; env: `KWHALE_BASE_URL`,
`KWHALE_EMAIL`, `KWHALE_PASSWORD`). Все тулзы отвечают dict-отчётом; ошибки
приходят как `{"error": "..."}` — не падают.

## Тулзы

| Тулза | Что делает |
|---|---|
| `list_supported_platforms()` | платформы парсеров: id, алиасы, хосты, нужен ли auth |
| `detect_playlist_platform(ref)` | какой парсер обработает ссылку |
| `parse_playlist(platform, ref)` | разбор плейлиста БЕЗ импорта (read-only, отчёт по трекам) |
| `import_playlist_to_profile(platform, ref, title?, dry_run?)` | acceptance: парсинг → матч → плейлист в профиле юзера |
| `search_tracks(query, limit)` | поиск по каталогу KWhale (все включённые источники) |
| `download_track(track_id, mode)` | `library` — поставить в библиотеку (сервис: лайк = ingest-джоба); `file` — скачать аудиофайл в `KWHALE_DOWNLOAD_DIR` |
| `download_status(track_ids)` | статусы: pending/downloading/ready/failed |
| `kwhale_status()` | health + config + текущий аккаунт |

Платформы: `yandex` (публичные плейлисты без auth), `soundcloud` (api-v2,
нужен прокси из RU — см. kwhale-proxy), `ytm` (InnerTube), `vk` (нужен
`Kwhale_AGENT_VK_TOKEN`), `ytdlp` (любая ссылка, нужен `pip install yt-dlp`).
Алиасы: «яндекс», «саундклауд», «ютуб-музыка», «вк», ...

## Сценарий 1 — перенос плейлиста (ACCEPTANCE)

Пользователь: «перенеси мой плейлист с <платформы> <ссылка> в KWhale».

1. `detect_playlist_platform(ref)` — убедиться, что платформа распозналась
   (если пользователь назвал платформу — сверить/использовать её как `platform`).
2. `parse_playlist(platform, ref)` — показать пользователю: заголовок, число
   треков, первые позиции; спросить подтверждение, если плейлист большой.
3. `import_playlist_to_profile(platform, ref, title=<название>)` — импорт.
4. Отчитаться: `matchedCount/unmatchedCount`, список unmatched с причинами
   («нет в каталоге» — предложить `download_track` или поискать варианты).
5. При `dry_run=true` на шаге 3 — только показать, что сматчилось.

Критерий готовности: плейлист появился в профиле пользователя KWhale
(`playlistId` в ответе), отчёт matched/unmatched передан.

## Сценарий 2 — поиск и скачивание

«найди и скачай <трек>»:
1. `search_tracks("<artist> <title>")` — выбрать лучший (совпадение названия/артиста,
   предпочтение `isDownloaded:false` + высокий qualityTier);
2. `download_track(trackId, mode="library")` — в библиотеку (лайк-семантика
   сервиса: пин + ingest-джоба);
3. `download_status([trackId])` — опросить до `ready` (не дёргать чаще 5-10 сек);
4. нужен файл на диск агента → `mode="file"`.

## Сценарий 3 — разведка

«что со стримом/источниками» → `kwhale_status()`; глубже — скиллы
`kwhale-codebase` (карта кода) и `kwhale-proxy` (прокси/VPN).

## Правила

- Импорт — только с подтверждения пользователя (создаёт данные в его профиле).
- Не форсить `download_track` на сотнях треков без спроса (очередь/трафик).
- Если платформа не распозналась или парсер упал — сказать прямо и предложить
  альтернативу (другой парсер/ссылку), не подменять молча.
- Токены/пароли в переписку не выводить.
