"""Platform parser registry + one-call fetch with graceful fallback.

Usage:
    from kwhale_agent.playlists import fetch_playlist
    parsed = await fetch_playlist("yandex", "https://music.yandex.ru/playlist/u-1")
    # or let the registry detect the platform from the URL:
    parsed = await fetch_playlist("", "https://soundcloud.com/x/sets/y")
"""

from __future__ import annotations

from .base import ParsedPlaylist, ParseError, PlaylistParser, TrackRef
from .soundcloud import SoundcloudPlaylistParser
from .vk import VkPlaylistParser
from .yandex import YandexPlaylistParser
from .ytm import YtmPlaylistParser
from .ytdlp_fallback import YtdlpFallbackParser

_PARSERS: list[PlaylistParser] = [
    YandexPlaylistParser(),
    SoundcloudPlaylistParser(),
    YtmPlaylistParser(),
    VkPlaylistParser(),
    YtdlpFallbackParser(),  # catch-all, last
]

_BY_NAME: dict[str, PlaylistParser] = {}
for _p in _PARSERS:
    _BY_NAME[_p.platform] = _p
    for _a in _p.aliases:
        _BY_NAME[_a.lower()] = _p


def list_platforms() -> list[dict]:
    return [
        {
            "platform": p.platform,
            "aliases": list(p.aliases),
            "hosts": list(p.url_hosts),
            "needsAuth": p.needs_auth,
        }
        for p in _PARSERS
    ]


def detect_platform(ref: str) -> str | None:
    """Platform id recognised from a URL/id ref (native parsers first)."""
    for p in _PARSERS:
        if p.platform == "ytdlp":
            continue
        if p.can_parse(ref):
            return p.platform
    if _PARSERS[-1].can_parse(ref):
        return "ytdlp"
    return None


def get_parser(platform: str) -> PlaylistParser:
    p = _BY_NAME.get((platform or "").lower())
    if p is None:
        raise ParseError(f"unknown platform {platform!r}; one of: {', '.join(sorted(_BY_NAME))}")
    return p


async def fetch_playlist(platform: str, ref: str, *, allow_fallback: bool = True) -> ParsedPlaylist:
    """Parse a playlist ref on the given platform (or auto-detect when empty).

    Falls back to the yt-dlp parser when the native parser fails or needs
    missing auth (disable with allow_fallback=False — used by the test stand).
    """
    parser = get_parser(platform) if platform else None
    if parser is None:
        detected = detect_platform(ref)
        if detected is None:
            raise ParseError(f"cannot detect platform for {ref!r}")
        parser = get_parser(detected)

    try:
        return await parser.fetch_playlist(ref)
    except ParseError:
        if not allow_fallback or parser.platform == "ytdlp":
            raise
        return await get_parser("ytdlp").fetch_playlist(ref)


__all__ = [
    "ParsedPlaylist",
    "ParseError",
    "PlaylistParser",
    "TrackRef",
    "detect_platform",
    "fetch_playlist",
    "get_parser",
    "list_platforms",
]
