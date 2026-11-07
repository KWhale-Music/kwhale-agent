"""Playlist import: parse -> match against kwhale library -> create playlist.

Acceptance flow: a playlist from a platform the user names is parsed by an
independent parser, each entry is matched into the kwhale catalog via /v1/search
(fuzzy artist+title), and matched tracks are added to a new playlist in the
user's kwhale profile. Returns a matched/unmatched report.
"""

from __future__ import annotations

from .bridge import KwhaleBridge
from .playlists.base import ParsedPlaylist, PlaylistParser, TrackRef

MATCH_THRESHOLD = 62  # same spirit as the server's fuzzy-match cutoff


def best_match(ref: TrackRef, candidates: list[dict], threshold: float = MATCH_THRESHOLD) -> dict | None:
    """Pick the best catalog track for a playlist entry, or None."""
    want = ref.match_key
    best: tuple[float, dict] | None = None
    for c in candidates:
        artists = c.get("artists") or []
        if isinstance(artists, str):
            artists = [artists]
        key = f"{', '.join(artists)} - {c.get('title') or ''}".lower()
        score = PlaylistParser.similarity(want, key)
        # ISRC is an exact identity when both sides carry it
        if ref.isrc and c.get("isrc") and ref.isrc == c.get("isrc"):
            score = 100.0
        if best is None or score > best[0]:
            best = (score, c)
    if best and best[0] >= threshold:
        return best[1]
    return None


async def import_playlist(
    bridge: KwhaleBridge,
    parsed: ParsedPlaylist,
    title: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Match parsed tracks into the catalog and put them into a profile playlist.

    Returns {"playlistId", "playlistTitle", "matched": [...], "unmatched": [...]}.
    dry_run=True only reports matches without creating anything.
    """
    matched: list[dict] = []
    unmatched: list[dict] = []
    seen: set[int] = set()
    track_ids: list[int] = []

    for t in parsed.tracks:
        query = f"{t.artist_str} {t.title}".strip()
        try:
            candidates = await bridge.search(query, limit=5)
        except Exception as e:  # noqa: BLE001 — one bad search must not kill the import
            unmatched.append({**t.to_dict(), "reason": f"search failed: {e}"})
            continue
        hit = best_match(t, candidates)
        if hit is None:
            unmatched.append({**t.to_dict(), "reason": "no catalog match"})
            continue
        tid = int(hit["id"])
        matched.append(
            {
                **t.to_dict(),
                "trackId": tid,
                "kwhaleTitle": hit.get("title"),
                "kwhaleArtists": hit.get("artists"),
            }
        )
        if tid not in seen:
            seen.add(tid)
            track_ids.append(tid)

    playlist_id = None
    playlist_title = title or f"{parsed.title} ({parsed.platform})"
    if not dry_run and track_ids:
        pl = await bridge.create_playlist(
            playlist_title,
            description=f"Imported from {parsed.platform}: {parsed.url or parsed.ref}",
        )
        playlist_id = pl.get("id")
        await bridge.add_tracks(playlist_id, track_ids)

    return {
        "platform": parsed.platform,
        "sourceUrl": parsed.url or parsed.ref,
        "playlistId": playlist_id,
        "playlistTitle": playlist_title if playlist_id else None,
        "sourceCount": parsed.track_count,
        "matchedCount": len(matched),
        "unmatchedCount": len(unmatched),
        "matched": matched,
        "unmatched": unmatched,
    }
