"""Playlist import: parse -> match against kwhale library -> create/update playlist.

Acceptance flow: a playlist from a platform or tracklist the user provides is
parsed into normalised TrackRefs, each entry is matched against the kwhale
catalog via /v1/search (fuzzy artist+title + duration guard + ISRC + fallback
query without feat/remaster suffixes), and matched tracks are added in order to
a new or existing playlist in the user's profile.
"""

from __future__ import annotations

import asyncio

from .bridge import KwhaleBridge
from .playlists.base import ParsedPlaylist, PlaylistParser, TrackRef

MATCH_THRESHOLD = 62  # same spirit as the server's fuzzy-match cutoff


def _candidate_duration_sec(c: dict) -> int:
    if c.get("durationSec"):
        try:
            return int(c["durationSec"])
        except (TypeError, ValueError):
            pass
    if c.get("durationMs"):
        try:
            return int(round(int(c["durationMs"]) / 1000))
        except (TypeError, ValueError):
            pass
    return 0


def best_match(ref: TrackRef, candidates: list[dict], threshold: float = MATCH_THRESHOLD) -> dict | None:
    """Pick the best catalog track for a playlist entry, or None."""
    want = ref.match_key
    clean_title = PlaylistParser.strip_match_noise(ref.title)
    lead_artist = ref.artists[0] if ref.artists else ""
    clean_want = f"{ref.artist_str} - {clean_title}".lower()
    lead_want = f"{lead_artist} - {clean_title}".lower() if lead_artist else clean_want

    best: tuple[float, dict] | None = None
    for c in candidates:
        artists = c.get("artists") or []
        if isinstance(artists, str):
            artists = [artists]
        title = c.get("title") or ""
        key = f"{', '.join(artists)} - {title}".lower()
        cand_clean = f"{', '.join(artists)} - {PlaylistParser.strip_match_noise(title)}".lower()

        score = max(
            PlaylistParser.similarity(want, key),
            PlaylistParser.similarity(clean_want, cand_clean) - (1.0 if want != clean_want else 0.0),
            PlaylistParser.similarity(lead_want, cand_clean) - (2.0 if want != lead_want else 0.0),
        )

        if ref.duration_sec > 0:
            cand_dur = _candidate_duration_sec(c)
            if cand_dur > 0:
                diff = abs(ref.duration_sec - cand_dur)
                if diff <= 3:
                    score = min(99.9, score + 4.0)
                elif diff > 30:
                    score -= 15.0

        # ISRC is an exact identity when both sides carry it
        if ref.isrc and c.get("isrc") and ref.isrc == c.get("isrc"):
            score = 100.0
        if best is None or score > best[0]:
            best = (score, c)
    if best and best[0] >= threshold:
        return best[1]
    return None


def _search_queries(t: TrackRef) -> list[str]:
    queries: list[str] = []
    primary = f"{t.artist_str} {t.title}".strip()
    if primary:
        queries.append(primary)
    clean_title = PlaylistParser.strip_match_noise(t.title)
    lead_artist = t.artists[0] if t.artists and t.artists[0].lower() != "unknown" else ""
    fallback = f"{lead_artist} {clean_title}".strip()
    if fallback and fallback.lower() != primary.lower():
        queries.append(fallback)
    return queries


async def _match_one(
    bridge: KwhaleBridge, t: TrackRef, sem: asyncio.Semaphore
) -> tuple[bool, dict]:
    queries = _search_queries(t)
    if not queries:
        return False, {**t.to_dict(), "reason": "empty query"}
    async with sem:
        last_err: Exception | None = None
        for idx, query in enumerate(queries):
            try:
                candidates = await bridge.search(query, limit=10 if idx == 0 else 10)
            except Exception as e:  # noqa: BLE001 — one bad search must not kill the import
                last_err = e
                continue
            hit = best_match(t, candidates)
            if hit is not None:
                tid = int(hit["id"])
                return True, {
                    **t.to_dict(),
                    "trackId": tid,
                    "kwhaleTitle": hit.get("title"),
                    "kwhaleArtists": hit.get("artists"),
                }
        if last_err is not None:
            return False, {**t.to_dict(), "reason": f"search failed: {last_err}"}
        return False, {**t.to_dict(), "reason": "no catalog match"}


async def import_playlist(
    bridge: KwhaleBridge,
    parsed: ParsedPlaylist,
    title: str | None = None,
    dry_run: bool = False,
    *,
    playlist_id: int | str | None = None,
    visibility: str = "private",
    concurrency: int = 4,
) -> dict:
    """Match parsed tracks into the catalog and save them into a profile playlist.

    When playlist_id is supplied, appends missing matched tracks into that
    existing playlist instead of creating a new one.
    Returns {"playlistId", "playlistTitle", "matched": [...], "unmatched": [...]}.
    """
    sem = asyncio.Semaphore(max(1, concurrency))
    outcomes = await asyncio.gather(*(_match_one(bridge, t, sem) for t in parsed.tracks))

    matched: list[dict] = []
    unmatched: list[dict] = []
    existing_ids: set[int] = set()
    target_id: Any = playlist_id
    target_title = title or f"{parsed.title} ({parsed.platform})"

    if not dry_run and target_id is not None:
        existing_pl = await bridge.get_playlist(target_id)
        target_title = title or existing_pl.get("title") or target_title
        for tr in existing_pl.get("tracks") or []:
            try:
                existing_ids.add(int(tr["id"]))
            except (KeyError, TypeError, ValueError):
                pass

    seen: set[int] = set(existing_ids)
    new_track_ids: list[int] = []

    for ok, payload in outcomes:
        if not ok:
            unmatched.append(payload)
            continue
        matched.append(payload)
        tid = int(payload["trackId"])
        if tid not in seen:
            seen.add(tid)
            new_track_ids.append(tid)

    if not dry_run and new_track_ids:
        if target_id is None:
            pl = await bridge.create_playlist(
                target_title,
                description=f"Imported from {parsed.platform}: {parsed.url or parsed.ref}",
                visibility=visibility,
            )
            target_id = pl.get("id")
        if target_id is not None:
            await bridge.add_tracks(target_id, new_track_ids)

    return {
        "platform": parsed.platform,
        "sourceUrl": parsed.url or parsed.ref,
        "playlistId": target_id,
        "playlistTitle": target_title if target_id else None,
        "sourceCount": parsed.track_count,
        "matchedCount": len(matched),
        "unmatchedCount": len(unmatched),
        "addedCount": len(new_track_ids),
        "matched": matched,
        "unmatched": unmatched,
    }
