---
name: kwhale-proxy
description: Подключение коннекторов KWhale и агент-парсеров к VPN/proxy — sing-box, SOURCE_PROXY_* маршрутизация, domains.lst, диагностика «источник не ходит». Использовать, когда источник недоступен из RU, стримы падают по таймауту или нужно настроить/проверить проксирование.
---

# VPN/proxy для источников KWhale

Часть сервисов (SoundCloud, YouTube, Deezer, Tidal, Qobuz) из RU напрямую не
идут или режутся. Всё проксирование — через локальный **sing-box** (socks5) с
построчной маршрутизацией по источникам.

## 1. Топология

```
kwhale api (контейнер) ──socks5h://singbox:2080──> sing-box (контейнер/хост) ──> мир
        │
        └── прямые запросы (Zvuk/VK/Яндекс — идут из RU)
```

- sing-box: socks5 на `:2080`, конфиги в `~/singbox-domains/`;
- контейнер api в external-сети `singbox_net` (docker-compose.singbox.yml),
  на хосте — `socks5h://127.0.0.1:2080`;
- **не стопать sing-box**: через него ходят SoundCloud/YouTube и все
  `SOURCE_PROXY_*`.

## 2. Маршрутизация по источникам: `SOURCE_PROXY_*`

В `.env` (см. `.env.example`):

```
SOURCE_PROXY_SOUNDCLOUD=socks5h://singbox:2080
SOURCE_PROXY_YTMUSIC=socks5h://singbox:2080
SOURCE_PROXY_TIDAL=socks5h://singbox:2080
SOURCE_PROXY_QOBUZ=socks5h://singbox:2080
SOURCE_PROXY_DEEZER=socks5h://singbox:2080
```

Читает `httpcore.proxy_for(connector_name)` (`app/httpcore.py`) — источник без
переменной идёт напрямую. Правило: проксировать только то, что не идёт из RU.
Текущий дефолт (recovery-конфиг): бесплатные источники включены напрямую
(soundcloud/yandex/ytmusic/vk), paid-источники выключены.

## 3. domains.lst — маршруты sing-box

В `~/singbox-domains/domains.lst` должны присутствовать домены источников:

```
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

После правки — перезапустить sing-box. Проверка: `curl -x socks5h://127.0.0.1:2080 https://soundcloud.com/ -o /dev/null -w '%{http_code}'`.

## 4. Агент-парслеры (kwhale_agent) и прокси

Парсеры в `agent/kwhale_agent/playlists/` ходят напрямую (httpx). httpx по
умолчанию уважает стандартные переменные окружения:

```bash
export HTTPS_PROXY=socks5h://127.0.0.1:2080   # нужен socksio: pip install 'httpx[socks]'
# или HTTP-прокси:
export HTTPS_PROXY=http://127.0.0.1:8080
python scripts/smoke_playlists.py <url>
```

VK-парсер ищет токен в `Kwhale_AGENT_VK_TOKEN` (VK из RU идёт напрямую — прокси
не нужен). Для yt-dlp-фолбэка прокси передаётся опцией `proxy` (env
`YTDLP_PROXY`).

## 5. Диагностика «источник не ходит»

1. `curl -sS --connect-timeout 5 https://<host>/ -o /dev/null -w '%{http_code}\n'`
   напрямую → `000` = таймаут/блок;
2. то же через `-x socks5h://127.0.0.1:2080` → работает = нужен `SOURCE_PROXY_*`;
3. sing-box жив? `curl -x socks5h://127.0.0.1:2080 https://www.google.com -o /dev/null -w '%{http_code}'`;
4. домен есть в `domains.lst`? (иначе трафик пойдёт мимо туннеля);
5. в контейнере адрес прокси другой: `socks5h://singbox:2080` (не 127.0.0.1);
6. токены/cookies протухли — 401/403, а не таймаут (это не про прокси).

## 6. Правила

- Проксируем минимально: только нужные источники (шифрование/латентность).
- Секреты и signed-URL никогда не логируем (`_safe_url`).
- sing-box и api не перезапускать без нужды — живая бета.
