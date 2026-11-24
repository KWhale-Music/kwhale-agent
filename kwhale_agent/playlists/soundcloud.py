"""SoundCloud playlist (set) parser — api-v2 with a scraped client_id.

URLs:
  * https://soundcloud.com/<user>/sets/<slug>
  * https://on.soundcloud.com/<short> (and /s/ short links, resolved via redirect)

Flow: resolve short link if needed -> scrape client_id from the site's JS
bundles -> GET https://api-v2.soundcloud.com/resolve?url=... -> playlist.tracks[].
Without a resolvable client_id the caller can fall back to ytdlp_fallback.
"""

from __future__ import annotations

import re

import httpx

from .base import ParsedPlaylist, ParseError, PlaylistParser, TrackRef

_SC_URL_RE = re.compile(r"soundcloud\.com/[\w.-]+/sets/[\w.-]+", re.IGNORECASE)
_SC_SHORT_RE = re.compile(
    r"https?://(?:on\.soundcloud\.com/[\w-]+|(?:m\.)?soundcloud\.com/.+/s/[\w-]+)",
    re.IGNORECASE,
)
_CLIENT_ID_RE = re.compile(r'client_id[=:]\s*["\']([\w-]{16,})["\']')
_ASSET_RE = re.compile(r'https://a-v2\.sndcdn\.com/assets/[^"\']+\.js')

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}


async def scrape_client_id(http: httpx.AsyncClient) -> str | None:
    """Find a working api-v2 client_id in the site's script bundles."""
    r = await http.get("https://soundcloud.com/", headers=_UA)
    if r.status_code != 200:
        return None
    scripts = _ASSET_RE.findall(r.text)
    for asset in scripts[:8]:  # the id lives in one of the big bundles
        try:
            sr = await http.get(asset, headers=_UA)
        except httpx.HTTPError:
            continue
        m = _CLIENT_ID_RE.search(sr.text)
        if m:
            return m.group(1)
    return None


class SoundcloudPlaylistParser(PlaylistParser):
    platform = "soundcloud"
    aliases = ("sc", "саундклауд", "sound-cloud")
    url_hosts = ("soundcloud.com", "on.soundcloud.com")

    def can_parse(self, ref: str) -> bool:
        return bool(_SC_URL_RE.search(ref) or _SC_SHORT_RE.search(ref))

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        m = _SC_URL_RE.search(ref)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
            if m:
                url = "https://" + m.group(0)
            elif _SC_SHORT_RE.search(ref):
                try:
                    rr = await http.get(ref.strip(), headers=_UA)
                except httpx.HTTPError as e:
                    raise ParseError(f"soundcloud short-link resolve failed: {e}") from e
                resolved = str(getattr(rr, "url", "") or "")
                rm = _SC_URL_RE.search(resolved)
                if not rm:
                    raise ParseError(f"soundcloud: short link {ref!r} did not resolve to a playlist set")
                url = "https://" + rm.group(0)
            else:
                raise ParseError(f"soundcloud: cannot parse playlist ref {ref!r}")

            cid = await scrape_client_id(http)
            if not cid:
                raise ParseError("soundcloud: client_id scrape failed (use ytdlp fallback)")
            r = await http.get(
                "https://api-v2.soundcloud.com/resolve",
                params={"url": url, "client_id": cid},
                headers=_UA,
            )
            if r.status_code != 200:
                raise ParseError(f"soundcloud resolve: HTTP {r.status_code}")
            pl = r.json() or {}

        if pl.get("kind") != "playlist":
            raise ParseError(f"soundcloud: resolved to {pl.get('kind')!r}, not a playlist")

        tracks: list[TrackRef] = []
        for i, t in enumerate(pl.get("tracks") or []):
            if not isinstance(t, dict) or not t.get("title"):
                continue
            label = t.get("title") or ""
            uploader = ((t.get("user") or {}).get("username")) or ""
            artists, title = PlaylistParser.artist_title_from_label(label, uploader)
            if not artists:
                artists = [uploader or "Unknown"]
            tracks.append(
                TrackRef(
                    title=title or label,
                    artists=artists,
                    duration_sec=int(round((t.get("duration") or 0) / 1000)),
                    external_id=str(t.get("id") or ""),
                    url=t.get("permalink_url") or "",
                    cover_url=(t.get("artwork_url") or "").replace("-large.", "-t500x500."),
                    position=i,
                )
            )
        return ParsedPlaylist(
            platform=self.platform,
            ref=url,
            url=pl.get("permalink_url") or url,
            title=pl.get("title") or "SoundCloud set",
            owner=((pl.get("user") or {}).get("username")) or "",
            description=pl.get("description") or "",
            tracks=tracks,
            truncated=bool(pl.get("track_count") and int(pl["track_count"]) > len(tracks)),
        )
