"""Yandex Music playlist parser — public JSON API, no auth for public playlists.

URLs:
  * https://music.yandex.ru/playlist/<uid>-<kind>
  * https://music.yandex.ru/users/<uid>/playlists/<kind>
  * https://music.yandex.ru/playlists/<share-id> (and music.yandex.* short redirects)

API: GET https://api.music.yandex.net/users/{uid}/playlists/{kind}
Large playlists may omit inline track objects after ~150 entries; when track
stubs carry numeric ids we resolve them via POST /tracks in batches.
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
_YANDEX_URL_RE = re.compile(
    r"^https?://(?:(?:[\w-]+\.)?music\.yandex\.(?:ru|com|by|kz|ua)|ya\.cc)/",
    re.IGNORECASE,
)


def _track_ref_from_dict(t: dict, position: int) -> TrackRef | None:
    if not isinstance(t, dict) or t.get("error"):
        return None
    title = PlaylistParser.clean_title(t.get("title") or "")
    if not title:
        return None
    artists = [a.get("name", "") for a in (t.get("artists") or []) if a.get("name")]
    albums = t.get("albums") or []
    album = (albums[0].get("title") if albums else "") or ""
    cover = ""
    cover_obj = t.get("coverUri") or (albums[0].get("coverUri") if albums else "")
    if cover_obj:
        cover = f"https://{str(cover_obj).replace('%%', '400x400')}"
    return TrackRef(
        title=title,
        artists=artists or ["Unknown"],
        album=album,
        duration_sec=seconds_from_ms(t.get("durationMs") or t.get("duration_ms")),
        isrc=(t.get("isrc") or None),
        external_id=str(t.get("id") or ""),
        cover_url=cover,
        position=position,
    )


async def _hydrate_missing_tracks(
    http: httpx.AsyncClient, stubs: list[tuple[int, str]]
) -> dict[str, dict]:
    """Fetch full track payloads when Yandex returns id-only stubs on large playlists."""
    by_id: dict[str, dict] = {}
    for start in range(0, len(stubs), 100):
        chunk = [tid for _, tid in stubs[start : start + 100]]
        try:
            r = await http.post(f"{_API}/tracks", data={"track-ids": ",".join(chunk)})
            if r.status_code >= 400:
                continue
            body = r.json() or {}
            result = body.get("result") if isinstance(body, dict) else body
            if not isinstance(result, list):
                continue
            for item in result:
                if isinstance(item, dict) and item.get("id") is not None:
                    by_id[str(item["id"])] = item
        except Exception:  # noqa: BLE001 — best-effort hydration
            continue
    return by_id


class YandexPlaylistParser(PlaylistParser):
    platform = "yandex"
    aliases = ("ym", "yandex-music", "яндекс", "яндекс-музыка")
    url_hosts = ("music.yandex.ru", "music.yandex.com", "music.yandex.by", "music.yandex.kz")

    def can_parse(self, ref: str) -> bool:
        s = (ref or "").strip()
        if _PLAYLIST_RE.search(s):
            return True
        return bool(_YANDEX_URL_RE.match(s)) and ("playlist" in s.lower() or "ya.cc/" in s.lower())

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_CLIENT_HEADERS
        ) as http:
            try:
                uid, kind = self._parse_ref(ref)
            except ParseError:
                uid, kind = await self._resolve_short_ref(http, ref)

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

            raw_tracks = pl.get("tracks") or []
            parsed_by_pos: dict[int, TrackRef] = {}
            missing_stubs: list[tuple[int, str]] = []
            for i, item in enumerate(raw_tracks):
                if not isinstance(item, dict):
                    continue
                t = item.get("track") if "track" in item else item
                tr = _track_ref_from_dict(t, i) if isinstance(t, dict) else None
                if tr is not None:
                    parsed_by_pos[i] = tr
                elif item.get("id") is not None and not (isinstance(t, dict) and t.get("error")):
                    missing_stubs.append((i, str(item["id"])))

            if missing_stubs:
                hydrated = await _hydrate_missing_tracks(http, missing_stubs)
                for pos, raw_id in missing_stubs:
                    item_dict = hydrated.get(raw_id)
                    if item_dict:
                        tr = _track_ref_from_dict(item_dict, pos)
                        if tr is not None:
                            parsed_by_pos[pos] = tr

        tracks = [parsed_by_pos[i] for i in sorted(parsed_by_pos)]
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

    async def _resolve_short_ref(self, http: httpx.AsyncClient, ref: str) -> tuple[str, str]:
        s = (ref or "").strip()
        if not s.startswith(("http://", "https://")):
            raise ParseError(f"yandex: cannot parse playlist ref {ref!r}")
        try:
            r = await http.get(s)
        except httpx.HTTPError as e:
            raise ParseError(f"yandex redirect resolve failed: {e}") from e
        final_url = str(getattr(r, "url", "") or s)
        m = _PLAYLIST_RE.search(final_url) or _PLAYLIST_RE.search(getattr(r, "text", "") or "")
        if m:
            uid = m.group("uid1") or m.group("uid2")
            kind = m.group("kind1") or m.group("kind2")
            return uid, kind
        raise ParseError(
            f"yandex: cannot resolve playlist uid/kind from {ref!r} "
            "(make sure the playlist is public or provide a /users/<uid>/playlists/<kind> URL)"
        )

    def _parse_ref(self, ref: str) -> tuple[str, str]:
        m = _PLAYLIST_RE.search(ref)
        if m:
            uid = m.group("uid1") or m.group("uid2")
            kind = m.group("kind1") or m.group("kind2")
            return uid, kind
        parts = re.split(r"[-/]", ref.strip())
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], parts[1]
        raise ParseError(f"yandex: cannot parse playlist ref {ref!r}")
