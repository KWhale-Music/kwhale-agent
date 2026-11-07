"""VK Music playlist parser — audio.get via api.vk.ru, needs a user token.

URLs:
  * https://vk.com/music/album/<owner_id>_<playlist_id>
  * https://vk.com/audio?z=audio_playlist<owner_id>_<playlist_id>
  * bare '<owner_id>_<playlist_id>'

Token: env Kwhale_AGENT_VK_TOKEN (VK access token with audio scope).
Without a token ParseError is raised — callers may use ytdlp_fallback.
"""

from __future__ import annotations

import os
import re

import httpx

from .base import ParsedPlaylist, ParseError, PlaylistParser, TrackRef

_API = "https://api.vk.ru/method/audio.get"
_V = "5.131"
_REF_RE = re.compile(r"(?:audio_playlist|album/)?(-?\d+)[_-](\d+)")


class VkPlaylistParser(PlaylistParser):
    platform = "vk"
    aliases = ("вк", "vk-music", "vk-музыка", "вконтакте")
    url_hosts = ("vk.com", "m.vk.com")
    needs_auth = True

    def can_parse(self, ref: str) -> bool:
        return "vk.com" in ref or bool(_REF_RE.fullmatch(ref.strip()))

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        token = os.environ.get("Kwhale_AGENT_VK_TOKEN", "")
        if not token:
            raise ParseError("vk: set Kwhale_AGENT_VK_TOKEN (or use the ytdlp fallback)")
        m = _REF_RE.search(ref)
        if not m:
            raise ParseError(f"vk: cannot parse playlist ref {ref!r}")
        owner_id, playlist_id = m.group(1), m.group(2)

        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(
                _API,
                params={
                    "owner_id": owner_id,
                    "playlist_id": playlist_id,
                    "access_token": token,
                    "v": _V,
                },
            )
        body = r.json() or {}
        if "error" in body:
            raise ParseError(f"vk api error: {body['error'].get('error_msg')}")
        resp = body.get("response") or {}
        items = resp.get("items") or []

        tracks: list[TrackRef] = []
        for i, t in enumerate(items):
            if not isinstance(t, dict) or not t.get("title"):
                continue
            tracks.append(
                TrackRef(
                    title=PlaylistParser.clean_title(t.get("title") or ""),
                    artists=PlaylistParser.split_artists(t.get("artist") or "") or ["Unknown"],
                    duration_sec=int(t.get("duration") or 0),
                    external_id=f"{t.get('owner_id', owner_id)}_{t.get('id', '')}",
                    url=t.get("url") or "",
                    position=i,
                )
            )
        return ParsedPlaylist(
            platform=self.platform,
            ref=f"{owner_id}_{playlist_id}",
            url=f"https://vk.com/music/album/{owner_id}_{playlist_id}",
            title=f"VK playlist {playlist_id}",
            tracks=tracks,
        )
