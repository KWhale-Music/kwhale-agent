"""Yandex Music playlist parser — public JSON API, no auth for public playlists.

URLs:
  * https://music.yandex.ru/playlist/<uid>-<kind>
  * https://music.yandex.ru/users/<uid>/playlists/<kind>
  * short links music.yandex/... are followed (redirect) and re-parsed.

API: GET https://api.music.yandex.net/users/{uid}/playlists/{kind}
(playlist object carries tracks[] with track/albums/artists; large playlists
may be capped — the parser reports `truncated` when trackCount > len(tracks)).
"""

from __future__ import annotations

import re

import httpx

from .base import ParsedPlaylist, ParseError, PlaylistParser, TrackRef, seconds_from_ms

_API = "https://api.music.yandex.net"
_CLIENT_HEADERS = {
    "X-Yandex-Music-Client": "YandexMusicAndroid/24023231",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
}

_PLAYLIST_RE = re.compile(
    r"(?:music\.yandex\.(?:ru|com|by|kz|ua))/(?:playlist/(?P<uid1>[\w.@-]+)-(?P<kind1>\d+)"
    r"|users/(?P<uid2>[\w.@-]+)/playlists/(?P<kind2>\d+))"
)


class YandexPlaylistParser(PlaylistParser):
    platform = "yandex"
    aliases = ("ym", "yandex-music", "яндекс", "яндекс-музыка")
    url_hosts = ("music.yandex.ru", "music.yandex.com", "music.yandex.by", "music.yandex.kz")

    def can_parse(self, ref: str) -> bool:
        return bool(_PLAYLIST_RE.search(ref))

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        uid, kind = self._parse_ref(ref)
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_CLIENT_HEADERS
        ) as http:
            try:
                r = await http.get(f"{_API}/users/{uid}/playlists/{kind}")
                if r.status_code >= 400:
                    detail = ""
                    try:
                        detail = ((r.json() or {}).get("error") or {}).get("message", "")
                    except Exception:  # noqa: BLE001
                        pass
                    raise ParseError(f"yandex: HTTP {r.status_code} {detail}".strip())
                r.raise_for_status()
            except ParseError:
                raise
            except httpx.HTTPError as e:
                raise ParseError(f"yandex playlist fetch failed: {e}") from e
        body = r.json() or {}
        pl = body.get("result") or body
        if not isinstance(pl, dict) or "tracks" not in pl:
            raise ParseError(f"yandex: unexpected playlist payload for {uid}/{kind}")

        tracks: list[TrackRef] = []
        raw_tracks = pl.get("tracks") or []
        for i, item in enumerate(raw_tracks):
            t = item.get("track") if isinstance(item, dict) and "track" in item else item
            if not isinstance(t, dict) or t.get("error"):
                continue
            artists = [a.get("name", "") for a in (t.get("artists") or []) if a.get("name")]
            albums = t.get("albums") or []
            album = (albums[0].get("title") if albums else "") or ""
            cover = ""
            cover_obj = t.get("coverUri") or (albums[0].get("coverUri") if albums else "")
            if cover_obj:
                cover = f"https://{str(cover_obj).replace('%%', '400x400')}"
            tracks.append(
                TrackRef(
                    title=PlaylistParser.clean_title(t.get("title") or ""),
                    artists=artists or ["Unknown"],
                    album=album,
                    duration_sec=seconds_from_ms(t.get("durationMs") or t.get("duration_ms")),
                    isrc=(t.get("isrc") or None),
                    external_id=str(t.get("id") or ""),
                    cover_url=cover,
                    position=i,
                )
            )
        owner = ((pl.get("owner") or {}).get("name")) or str((pl.get("owner") or {}).get("uid") or "")
        track_count = int(pl.get("trackCount") or len(tracks))
        return ParsedPlaylist(
            platform=self.platform,
            ref=f"{uid}/{kind}",
            url=f"https://music.yandex.ru/users/{uid}/playlists/{kind}",
            title=pl.get("title") or f"Playlist {kind}",
            owner=owner,
            description=pl.get("description") or "",
            tracks=tracks,
            truncated=track_count > len(tracks),
        )

    def _parse_ref(self, ref: str) -> tuple[str, str]:
        m = _PLAYLIST_RE.search(ref)
        if m:
            uid = m.group("uid1") or m.group("uid2")
            kind = m.group("kind1") or m.group("kind2")
            return uid, kind
        # bare 'uid/kind' or 'uid-kind'
        parts = re.split(r"[-/]", ref.strip())
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], parts[1]
        raise ParseError(f"yandex: cannot parse playlist ref {ref!r}")
