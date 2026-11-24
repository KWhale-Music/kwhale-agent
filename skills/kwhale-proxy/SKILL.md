---
name: kwhale-proxy
description: Подключение коннекторов KWhale и агент-парсеров к VPN/proxy — sing-box, SOURCE_PROXY_* маршрутизация, domains.lst, диагностика «источник не ходит». Использовать, когда источник недоступен из текущего региона, стримы падают по таймауту или нужно настроить/проверить проксирование.
---

# VPN/proxy для источников KWhale

Часть сервисов (SoundCloud, YouTube, Deezer, Tidal, Qobuz) в отдельных регионах режется или не ходит напрямую. Проксирование в сервисе — через локальный **sing-box** (`socks5`) с построчной маршрутизацией по источникам.

## 1. Топология

```text
kwhale api (контейнер) ──socks5h://singbox:2080──> sing-box (контейнер/хост) ──> внешняя сеть
        │
        └── прямые запросы (Zvuk/VK/Яндекс — при локальной доступности)
```

- Конфиги `domains.lst` монтируются для sing-box (`docker-compose.singbox.yml`); на хосте socks5 слушает `:2080` (`socks5h://127.0.0.1:2080`), из docker-сети `singbox_net` — `socks5h://singbox:2080`.
- **Не стопать sing-box** во время работы живого API: через него ходят SoundCloud/YouTube и проксируемые коннекторы.

## 2. Маршрутизация по источникам: `SOURCE_PROXY_*`

В `.env` сервера (см. `.env.example`):

```env
SOURCE_PROXY_SOUNDCLOUD=socks5h://singbox:2080
SOURCE_PROXY_YTMUSIC=socks5h://singbox:2080
SOURCE_PROXY_TIDAL=socks5h://singbox:2080
SOURCE_PROXY_QOBUZ=socks5h://singbox:2080
SOURCE_PROXY_DEEZER=socks5h://singbox:2080
```

Значения читает `httpcore.proxy_for(connector_name)` (`kwhale-v3/server/app/httpcore.py`) — источник без переменной идёт напрямую. Проксировать минимально: только те источники, что не ходят напрямую.

## 3. `domains.lst` — маршруты sing-box

```text
soundcloud.com
sndcdn.com
youtube.com
googlevideo.com
ytimg.com
amp.shazam.com        # фингерпринт загрузок (Shazam)
music.youtube.com
api.tidal.com
api.qobuz.com
media.deezer.com
```

После правки — перезапустить sing-box. Проверка с хоста:
`curl -x socks5h://127.0.0.1:2080 https://soundcloud.com/ -o /dev/null -w '%{http_code}'`

## 4. Агент-парсеры (`kwhale_agent`) и прокси

Парсеры в `agent/kwhale_agent/playlists/` используют `httpx` с поддержкой `socksio` (`httpx[socks]`):

```bash
export HTTPS_PROXY=socks5h://127.0.0.1:2080
# или HTTP-прокси:
export HTTPS_PROXY=http://127.0.0.1:8080
```

- Для VK-парсера токен задаётся в `KWHALE_AGENT_VK_TOKEN` (legacy-алиас `Kwhale_AGENT_VK_TOKEN`); VK обычно ходит напрямую.
- Для `ytdlp_fallback` прокси передаётся из `YTDLP_PROXY` или `HTTPS_PROXY`.

## 5. Диагностика «источник не ходит»

1. `curl -sS --connect-timeout 5 https://<host>/ -o /dev/null -w '%{http_code}\n'` напрямую → `000` = таймаут/блокировка.
2. То же через `-x socks5h://127.0.0.1:2080` → работает = нужен `SOURCE_PROXY_*` или `HTTPS_PROXY`.
3. Проверить sing-box: `curl -x socks5h://127.0.0.1:2080 https://www.google.com -o /dev/null -w '%{http_code}'`.
4. Проверить наличие домена источника в `domains.lst` (иначе трафик пойдёт мимо туннеля).
5. Убедиться, что внутри docker-контейнера указан `socks5h://singbox:2080`, а на хосте — `socks5h://127.0.0.1:2080`.
6. Ошибки `401`/`403` при быстром ответе — протухшие токены/cookies или клиентские ограничения, не прокси.

## 6. Правила

- Секреты и signed-URL никогда не логировать.
- Живой API и sing-box на проде не перезапускать без явной необходимости.
