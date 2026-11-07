"""Universal playlist fallback via yt-dlp (optional dependency).

Works for any URL yt-dlp understands (YouTube, SoundCloud, VK pages, ...).
Used when a native parser is unavailable or fails. Entries are extracted flat
(no media download); artists/titles are split from the entry label.
"""

from __future__ import annotations

from .base import ParsedPlaylist, ParseError, PlaylistParser, TrackRef

try:
    import yt_dlp  # type: ignore

    HAVE_YTDLP = True
except ImportError:  # pragma: no cover - optional dep
    yt_dlp = None
    HAVE_YTDLP = False


class YtdlpFallbackParser(PlaylistParser):
    platform = "ytdlp"
    aliases = ("fallback", "url", "ссылка")

    def can_parse(self, ref: str) -> bool:
        return ref.startswith(("http://", "https://"))

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        if not HAVE_YTDLP:
            raise ParseError("yt-dlp is not installed (pip install yt-dlp)")
        import asyncio

        def _extract() -> dict:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": "in_playlist",
                "skip_download": True,
                "playlistend": 500,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(ref, download=False) or {}

        try:
            info = await asyncio.to_thread(_extract)
        except Exception as e:  # noqa: BLE001 — yt-dlp raises many types
            raise ParseError(f"yt-dlp extraction failed: {e}") from e

        entries = info.get("entries")
        if entries is None:
            entries = [info]  # single video: treat as one-track playlist
        tracks: list[TrackRef] = []
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            label = e.get("title") or ""
            uploader = e.get("uploader") or e.get("channel") or ""
            artists, title = PlaylistParser.artist_title_from_label(label, uploader)
            tracks.append(
                TrackRef(
                    title=title or label,
                    artists=artists or ["Unknown"],
                    duration_sec=int(e.get("duration") or 0),
                    external_id=str(e.get("id") or ""),
                    url=e.get("url") or e.get("webpage_url") or "",
                    cover_url=e.get("thumbnail") or "",
                    position=i,
                )
            )
        host = ref.split("/")[2] if ref.count("/") > 2 else "web"
        return ParsedPlaylist(
            platform=self.platform,
            ref=ref,
            url=info.get("webpage_url") or ref,
            title=info.get("title") or f"Playlist on {host}",
            owner=info.get("uploader") or "",
            tracks=tracks,
        )
