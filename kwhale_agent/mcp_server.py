"""kwhale agent MCP server (stdio) — catalog, playlists, uploads, recommendations, sharing.

Run:
    python -m kwhale_agent.mcp_server
    # or: kwhale-agent-mcp

Credentials can come from env (KWHALE_BASE_URL, KWHALE_EMAIL, KWHALE_PASSWORD)
or be supplied in-session via login(email, password, base_url). Public instance URLs
are always provided by the user rather than hardcoded.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from .bridge import BridgeError, KwhaleBridge
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


async def _ensure_auth(bridge: KwhaleBridge) -> None:
    if bridge.token:
        return
    if not bridge.has_explicit_url:
        raise BridgeError("base_url not configured: ask the user for their KWhale service URL and call login()")
    await bridge.login()


# ── auth & orientation ──────────────────────────────────────────────────────


@mcp.tool()
async def login(email: str, password: str, base_url: str = "") -> dict:
    """Authenticate an account on the user-provided KWhale URL (email + password, never username).

    Ask the user for their KWhale server URL if KWHALE_BASE_URL is not configured yet.
    Never logs or echoes back passwords or raw tokens.
    """
    bridge = _get_bridge()
    try:
        if base_url.strip():
            bridge.configure(base_url=base_url, email=email, password=password)
        else:
            if not bridge.has_explicit_url:
                return _brief(
                    BridgeError(
                        "base_url is required when KWHALE_BASE_URL is not set; ask the user for the server URL"
                    )
                )
            bridge.configure(email=email, password=password)
        out = await bridge.login()
        return {
            "ok": True,
            "baseUrl": bridge.base_url,
            "user": out.get("user") or {},
        }
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def logout() -> dict:
    """Revoke the active session and clear cached credentials in memory."""
    bridge = _get_bridge()
    try:
        await bridge.logout()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def kwhale_status() -> dict:
    """Server health + config + active URL + current account — for orientation."""
    bridge = _get_bridge()
    out: dict[str, Any] = {
        "baseUrl": bridge.base_url,
        "explicitBaseUrl": bridge.has_explicit_url,
    }
    try:
        out["health"] = await bridge.health()
    except Exception as e:  # noqa: BLE001
        out["health"] = _brief(e)
    try:
        out["config"] = await bridge.config()
    except Exception as e:  # noqa: BLE001
        out["config"] = _brief(e)
    try:
        if not bridge.token and bridge.email and bridge.password and bridge.has_explicit_url:
            await bridge.login()
        out["me"] = await bridge.me() if bridge.token else {"authorized": False}
    except Exception as e:  # noqa: BLE001
        out["me"] = _brief(e)
    return out


# ── external playlist parsing & import ──────────────────────────────────────


@mcp.tool()
async def list_supported_platforms() -> list[dict]:
    """Platforms whose playlists can be parsed: ids, aliases, hosts, auth needs."""
    return list_platforms()


@mcp.tool()
async def detect_playlist_platform(ref: str) -> str | None:
    """Which platform parser handles this URL, file path, or pasted tracklist (or null)."""
    return detect_platform(ref)


@mcp.tool()
async def parse_playlist(platform: str, ref: str) -> dict:
    """Parse a playlist from a platform URL or tracklist text WITHOUT importing. Read-only.

    platform: yandex/soundcloud/ytm/vk/text/ytdlp (or alias), or "" to auto-detect.
    """
    try:
        parsed = await fetch_playlist(platform, ref)
    except ParseError as e:
        return _brief(e)
    out = parsed.to_dict()
    out["tracks"] = out["tracks"][:100]  # keep tool output manageable
    return out


@mcp.tool()
async def parse_track_list(text: str, title: str = "Imported tracklist") -> dict:
    """Parse a pasted tracklist ('Artist - Title'), CSV (Exportify/Spotify), or M3U8 text."""
    try:
        parsed = await fetch_playlist("text", text)
        if title.strip():
            parsed.title = title.strip()
        out = parsed.to_dict()
        out["tracks"] = out["tracks"][:100]
        return out
    except ParseError as e:
        return _brief(e)


@mcp.tool()
async def import_playlist_to_profile(
    platform: str,
    ref: str,
    title: str = "",
    playlist_id: str = "",
    visibility: str = "private",
    dry_run: bool = False,
) -> dict:
    """Parse an external playlist/tracklist, match tracks into KWhale, and save to a profile playlist.

    Set playlist_id to append only missing tracks into an existing playlist instead
    of creating a new one. Set dry_run=true to preview matched/unmatched without writes.
    """
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        parsed = await fetch_playlist(platform, ref)
        return await import_playlist(
            bridge,
            parsed,
            title or None,
            dry_run=dry_run,
            playlist_id=playlist_id or None,
            visibility=visibility or "private",
        )
    except Exception as e:  # noqa: BLE001
        return _brief(e)


# ── playlist CRUD & editing ─────────────────────────────────────────────────


@mcp.tool()
async def list_playlists(owner: str = "me") -> list[dict]:
    """List playlists in the user's profile (owner='me' or 'all')."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.list_playlists(owner=owner)
    except Exception as e:  # noqa: BLE001
        return [_brief(e)]


@mcp.tool()
async def get_playlist(playlist_id: str) -> dict:
    """Get playlist metadata and its complete ordered track list."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.get_playlist(playlist_id, full_tracks=True)
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def create_playlist(
    title: str, description: str = "", visibility: str = "private"
) -> dict:
    """Create a new playlist in the user's profile (visibility: private|unlisted|public)."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.create_playlist(title, description=description, visibility=visibility)
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def update_playlist(
    playlist_id: str,
    title: str = "",
    description: str = "",
    visibility: str = "",
) -> dict:
    """Rename a playlist or change its description/visibility (non-empty args only)."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.update_playlist(
            playlist_id,
            title=title or None,
            description=description if description != "" else None,
            visibility=visibility or None,
        )
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def delete_playlist(playlist_id: str) -> dict:
    """Delete an owned playlist (requires explicit user confirmation before calling)."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        await bridge.delete_playlist(playlist_id)
        return {"deleted": True, "playlistId": playlist_id}
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def add_tracks_to_playlist(
    playlist_id: str, track_ids: list[str], position: int | None = None
) -> dict:
    """Add tracks to an owned playlist in batches of up to 500 (position is 0-based optional)."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.add_tracks(playlist_id, track_ids, position=position)
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def remove_track_from_playlist(playlist_id: str, track_id: str) -> dict:
    """Remove a track from an owned playlist."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        await bridge.remove_track(playlist_id, track_id)
        return {"removed": True, "playlistId": playlist_id, "trackId": track_id}
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def reorder_playlist_tracks(playlist_id: str, track_ids: list[str]) -> dict:
    """Set full track order for an owned playlist (unmentioned tracks keep relative tail order)."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.reorder_tracks(playlist_id, track_ids)
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def like_playlist_tracks(playlist_id: str) -> dict:
    """Like all tracks in a playlist (triggers server-side library download for missing files)."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.like_playlist_tracks(playlist_id)
    except Exception as e:  # noqa: BLE001
        return _brief(e)


# ── catalog, downloads, uploads, library, recommendations, shares ───────────


@mcp.tool()
async def search_tracks(query: str, limit: int = 10, wait: bool = True) -> list[dict]:
    """Search the kwhale catalog across enabled sources (wait=true finishes slow connectors)."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.search(query, limit=limit, wait=wait)
    except Exception as e:  # noqa: BLE001
        return [_brief(e)]


@mcp.tool()
async def get_track_details(track_id: str) -> dict:
    """Inspect track metadata, sources, audio quality metrics, and lyrics availability."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        info = await bridge.get_track_info(track_id)
        try:
            lyrics = await bridge.get_lyrics(track_id)
        except BridgeError:
            lyrics = None
        return {**info, "lyrics": lyrics}
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def like_track(track_id: str, liked: bool = True) -> dict:
    """Like (true -> pins & queues server library download) or unlike (false) a track."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        if liked:
            await bridge.like_track(track_id)
        else:
            await bridge.unlike_track(track_id)
        return {"trackId": track_id, "liked": liked}
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def download_track(track_id: int, mode: str = "library") -> dict:
    """Start a download for a track.

    mode="library": enqueue server-side library download via PUT /tracks/{id}/like.
    mode="file": save the audio file to KWHALE_DOWNLOAD_DIR (default ./downloads).
    """
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
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
    try:
        await _ensure_auth(bridge)
    except Exception as e:  # noqa: BLE001
        return [_brief(e)]
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
async def upload_track(
    file_path: str, title: str = "", artist: str = "", album: str = ""
) -> dict:
    """Upload a local audio file (.mp3/.flac/.m4a/.ogg/.opus/.wav/.aac, <=100MB) into the library."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.upload_track(
            file_path,
            title=title or None,
            artist=artist or None,
            album=album or None,
        )
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def manage_enrichments(action: str = "list", proposal_id: int = 0) -> dict:
    """List pending upload metadata enrichments ('list') or 'confirm'/'reject' a proposal_id."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        act = action.strip().lower()
        if act == "list":
            return {"items": await bridge.list_enrichments()}
        if act == "confirm":
            return await bridge.confirm_enrichment(proposal_id)
        if act == "reject":
            return await bridge.reject_enrichment(proposal_id)
        return _brief(BridgeError(f"unknown action: {action}; use list|confirm|reject"))
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def list_library(section: str = "tracks", limit: int = 50, query: str = "") -> dict:
    """Read user library: section='tracks'|'playlists'|'albums'|'history'."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.list_library(section, limit=limit, query=query or None)
    except Exception as e:  # noqa: BLE001
        return _brief(e)


@mcp.tool()
async def list_mixes() -> list[dict]:
    """List personal/discovery/genre/artist mixes generated for the logged-in user."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.list_mixes()
    except Exception as e:  # noqa: BLE001
        return [_brief(e)]


@mcp.tool()
async def get_mix_tracks(mix_id: str, limit: int = 40) -> list[dict]:
    """Fetch ranked tracks with scores & reasons for a mix id."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.get_mix_tracks(mix_id, limit=limit)
    except Exception as e:  # noqa: BLE001
        return [_brief(e)]


@mcp.tool()
async def prompt_mix(prompt: str, size: int = 40) -> list[dict]:
    """Build a recommendation mix from a free-text prompt via /v1/mixes/prompt."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.prompt_mix(prompt, size=size)
    except Exception as e:  # noqa: BLE001
        return [_brief(e)]


@mcp.tool()
async def create_share_link(kind: str, entity_id: str) -> dict:
    """Create or renew a 7-day public share link (/share/s/<id>) for track|album|artist."""
    bridge = _get_bridge()
    try:
        await _ensure_auth(bridge)
        return await bridge.create_share(kind, entity_id)
    except Exception as e:  # noqa: BLE001
        return _brief(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
