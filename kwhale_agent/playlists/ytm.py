"""YouTube Music playlist parser — InnerTube WEB_REMIX browse, no auth.

URLs: https://music.youtube.com/playlist?list=PL... (any youtube.com/playlist
or youtu.be list=... link works too).

Flow: POST https://music.youtube.com/youtubei/v1/browse with browseId=VL<id>
and the public WEB_REMIX client context, then walk the responsive-list items
(flexColumns: title / artists / album / duration). Falls back to
ytdlp_fallback when the response shape changes.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from .base import ParsedPlaylist, ParseError, PlaylistParser, TrackRef

_BROWSE_URL = "https://music.youtube.com/youtubei/v1/browse?prettyPrint=false"
# public client constants shipped in the WEB_REMIX bundle (not secrets)
_KEY = "AIzaSyC9XL3ZjWddXya6X74dJoCTL-WEYFDNX30"
_CONTEXT = {
    "context": {
        "client": {
            "clientName": "WEB_REMIX",
            "clientVersion": "1.20240724.00.00",
            "hl": "en",
            "gl": "US",
        }
    }
}
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

_LIST_RE = re.compile(r"[?&]list=([\w-]{10,})")
_DUR_RE = re.compile(r"^(\d+):(\d{2})(?::(\d{2}))?$")


def _playlist_id(ref: str) -> str | None:
    m = _LIST_RE.search(ref)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{10,}", ref.strip()):
        return ref.strip()
    return None


def _runs_text(node: dict) -> str:
    runs = (((node or {}).get("text")) or {}).get("runs") or []
    return "".join(r.get("text", "") for r in runs)


def _parse_duration(text: str) -> int:
    m = _DUR_RE.match((text or "").strip())
    if not m:
        return 0
    h, mm, ss = m.groups()
    if ss is not None:
        return int(h) * 3600 + int(mm) * 60 + int(ss)
    return int(h) * 60 + int(mm)


def _walk_items(obj: dict) -> list[dict]:
    """Find musicResponsiveListItemRenderer nodes anywhere in the browse tree."""
    items: list[dict] = []

    def rec(node: object) -> None:
        if isinstance(node, dict):
            item = node.get("musicResponsiveListItemRenderer")
            if isinstance(item, dict):
                items.append(item)
            for v in node.values():
                rec(v)
        elif isinstance(node, list):
            for v in node:
                rec(v)

    rec(obj)
    return items


class YtmPlaylistParser(PlaylistParser):
    platform = "ytm"
    aliases = ("ytmusic", "youtube-music", "ютуб-музыка", "yt")
    url_hosts = ("music.youtube.com", "www.youtube.com", "youtube.com", "youtu.be")

    def can_parse(self, ref: str) -> bool:
        return _playlist_id(ref) is not None and ("youtu" in ref or "list=" in ref)

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        pid = _playlist_id(ref)
        if not pid:
            raise ParseError(f"ytm: cannot parse playlist ref {ref!r}")
        body = {**_CONTEXT, "browseId": f"VL{pid}"}
        async with httpx.AsyncClient(timeout=30.0) as http:
            try:
                r = await http.post(_BROWSE_URL, params={"key": _KEY}, json=body, headers=_UA)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise ParseError(f"ytm browse failed: {e}") from e
        data = r.json() or {}
        items = _walk_items(data)
        if not items:
            raise ParseError("ytm: no playlist items in browse response (shape changed?)")

        tracks: list[TrackRef] = []
        for i, item in enumerate(items):
            cols = item.get("flexColumns") or []

            def col(idx: int) -> str:
                if idx >= len(cols):
                    return ""
                return _runs_text((cols[idx].get("musicResponsiveListItemFlexColumnRenderer") or {}))

            title = PlaylistParser.clean_title(col(0))
            if not title:
                continue
            artists = PlaylistParser.split_artists(col(1)) or ["Unknown"]
            fixed = item.get("fixedColumns") or []
            dur_text = ""
            if fixed:
                dur_text = _runs_text((fixed[0].get("musicResponsiveListItemFixedColumnRenderer") or {}))
            vid = ""
            overlay = (item.get("overlay") or {}).get("itemSectionOverlayRenderer") or {}
            vid = (
                ((overlay.get("background") or {}).get("musicPlayButtonRenderer") or {})
                .get("playNavigationEndpoint", {})
                .get("watchEndpoint", {})
                .get("videoId")
                or (item.get("playlistItemData") or {}).get("videoId")
                or ""
            )
            tracks.append(
                TrackRef(
                    title=title,
                    artists=artists,
                    album=col(2),
                    duration_sec=_parse_duration(dur_text),
                    external_id=vid,
                    url=f"https://music.youtube.com/watch?v={vid}" if vid else "",
                    position=i,
                )
            )
        return ParsedPlaylist(
            platform=self.platform,
            ref=pid,
            url=f"https://music.youtube.com/playlist?list={pid}",
            title=playlist_title_from_browse(data) or f"YouTube Music playlist {pid}",
            tracks=tracks,
        )


def playlist_title_from_browse(data: dict) -> str:
    """Extract the header title (optional nicety for the MCP report)."""

    def find_header(node: object) -> str:
        if isinstance(node, dict):
            hdr = node.get("playlistHeaderRenderer") or node.get("musicDetailHeaderRenderer")
            if isinstance(hdr, dict):
                t = _runs_text((hdr.get("title") or {}))
                if t:
                    return t
            for v in node.values():
                got = find_header(v)
                if got:
                    return got
        elif isinstance(node, list):
            for v in node:
                got = find_header(v)
                if got:
                    return got
        return ""

    return find_header(data)
