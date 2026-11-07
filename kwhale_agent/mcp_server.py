"""kwhale agent MCP server (stdio) — codebase-adjacent operations for an LLM.

Run:
    python -m kwhale_agent.mcp_server

Tools let the agent orient in the kwhale service and operate it by hand:
search the catalog, trigger downloads, parse playlists from platforms the user
names, and import them into a kwhale user profile (the acceptance scenario).

Config via env:
    KWHALE_BASE_URL   (default http://127.0.0.1:19001/v1)
    KWHALE_EMAIL / KWHALE_PASSWORD   account for profile operations
    Kwhale_AGENT_VK_TOKEN   optional, native VK playlist parsing
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from .bridge import KwhaleBridge
from .importer import import_playlist
from .playlists import ParseError, detect_platform, fetch_playlist, list_platforms

mcp = FastMCP("kwhale-agent")

_bridge: KwhaleBridge | None = None


def _get_bridge() -> KwhaleBridge:
    global _bridge
    if _bridge is None:
        _bridge = KwhaleBridge()
    return _bridge


def _brief(e: Exception) -> dict:
    return {"error": str(e)}


@mcp.tool()
async def list_supported_platforms() -> list[dict]:
    """Platforms whose playlists can be parsed: ids, aliases, URL hosts, auth needs."""
    return list_platforms()


@mcp.tool()
async def parse_playlist(platform: str, ref: str) -> dict:
    """Parse a playlist from a platform (yandex/soundcloud/ytm/vk/ytdlp) without importing.

    platform: platform id or alias, or "" to auto-detect from the ref URL.
    ref: playlist URL (or platform-specific id). Read-only.
    """
    try:
        parsed = await fetch_playlist(platform, ref)
    except ParseError as e:
        return _brief(e)
    out = parsed.to_dict()
    out["tracks"] = out["tracks"][:100]  # keep tool output manageable
    return out


@mcp.tool()
async def import_playlist_to_profile(
    platform: str,
    ref: str,
    title: str = "",
    dry_run: bool = False,
) -> dict:
    """Acceptance tool: parse a playlist from the user's platform and move it into their kwhale profile.

    Parses the playlist, fuzzy-matches every entry into the kwhale catalog and
    creates a playlist in the logged-in user's profile (KWHALE_EMAIL). Set
    dry_run=true to only report what would match.
    """
    bridge = _get_bridge()
    try:
        if not bridge.token:
            await bridge.login()
        parsed = await fetch_playlist(platform, ref)
        report = await import_playlist(bridge, parsed, title or None, dry_run=dry_run)
        return report
    except Exception as e:  # noqa: BLE001 — tool must report, not crash
        return _brief(e)


@mcp.tool()
async def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Search the kwhale catalog (aggregated across enabled sources)."""
    try:
        return await _get_bridge().search(query, limit)
    except Exception as e:  # noqa: BLE001
        return [_brief(e)]


@mcp.tool()
async def download_track(track_id: int, mode: str = "library") -> dict:
    """Start a download for a track.

    mode="library": enqueue the server-side library download (server semantics:
    this is a like — it pins the track and downloads it to the library).
    mode="file": save the audio file to KWHALE_DOWNLOAD_DIR (default ./downloads).
    """
    bridge = _get_bridge()
    try:
        if not bridge.token:
            await bridge.login()
        if mode == "file":
            dest = os.environ.get("KWHALE_DOWNLOAD_DIR", "./downloads")
            path = await bridge.download_file(track_id, dest)
            return {"trackId": track_id, "savedTo": path}
        await bridge.request_library_download(track_id)
        status = await bridge.get_track(track_id)
        return {
            "trackId": track_id,
            "queued": True,
            "downloadStatus": status.get("downloadStatus"),
        }
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def download_status(track_ids: list[int]) -> list[dict]:
    """Library download status for tracks: pending/downloading/ready/failed."""
    bridge = _get_bridge()
    out: list[dict] = []
    for tid in track_ids:
        try:
            t = await bridge.get_track(tid)
            out.append(
                {
                    "trackId": tid,
                    "title": t.get("title"),
                    "downloadStatus": t.get("downloadStatus"),
                    "isDownloaded": t.get("isDownloaded"),
                }
            )
        except Exception as e:  # noqa: BLE001
            out.append({"trackId": tid, **_brief(e)})
    return out


@mcp.tool()
async def kwhale_status() -> dict:
    """Server health + config + current account — for orientation."""
    bridge = _get_bridge()
    out: dict[str, Any] = {}
    try:
        out["health"] = await bridge.health()
    except Exception as e:  # noqa: BLE001
        out["health"] = _brief(e)
    try:
        out["config"] = await bridge.config()
    except Exception as e:  # noqa: BLE001
        out["config"] = _brief(e)
    try:
        if not bridge.token and bridge.email:
            await bridge.login()
        out["me"] = await bridge.me() if bridge.token else {"authorized": False}
    except Exception as e:  # noqa: BLE001
        out["me"] = _brief(e)
    return out


@mcp.tool()
async def detect_playlist_platform(ref: str) -> str | None:
    """Which platform parser would handle this playlist URL (or null)."""
    return detect_platform(ref)


if __name__ == "__main__":
    mcp.run()
