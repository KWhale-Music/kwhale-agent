"""Plain-text / CSV / M3U8 tracklist parser (no auth, no network).

Covers Spotify/Apple Music CSV exports (e.g. Exportify, TuneMyMusic, Soundiiz),
M3U/M3U8 playlists (#EXTINF:<sec>,<Artist> - <Title>), and pasted track lists
like '1. Artist - Title [03:45]'.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .base import ParsedPlaylist, ParseError, PlaylistParser, TrackRef, seconds_from_ms

_PREFIX_NUM_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)\]])\s+")
_TRAIL_DUR_RE = re.compile(r"\s*[\[(](\d+):(\d{2})[\])]\s*$")
_EXTINF_RE = re.compile(r"^#EXTINF:\s*(-?\d+)\s*,\s*(.+)$")
_DASH_SEP_RE = re.compile(r"\s+(?:-|—|–)\s+")


def _load_source(ref: str) -> tuple[str, str]:
    raw = (ref or "").strip()
    if not raw:
        return "", ""
    if "\n" not in raw and "\r" not in raw and len(raw) < 512 and not raw.startswith(("http://", "https://")):
        p = Path(raw)
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8-sig"), p.stem
        except OSError:
            pass
    return raw, ""


def _split_line_track(line: str, position: int, duration_sec: int = 0) -> TrackRef | None:
    cleaned = _PREFIX_NUM_RE.sub("", line.strip())
    if not cleaned:
        return None
    m_dur = _TRAIL_DUR_RE.search(cleaned)
    if m_dur:
        if not duration_sec:
            duration_sec = int(m_dur.group(1)) * 60 + int(m_dur.group(2))
        cleaned = cleaned[: m_dur.start()].strip()

    parts = _DASH_SEP_RE.split(cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        artists = PlaylistParser.split_artists(parts[0])
        title = PlaylistParser.clean_title(parts[1])
    else:
        artists = ["Unknown"]
        title = PlaylistParser.clean_title(cleaned)
    if not title:
        return None
    return TrackRef(
        title=title,
        artists=artists or ["Unknown"],
        duration_sec=duration_sec,
        position=position,
    )


_CSV_KNOWN_HEADERS = {
    "track name",
    "title",
    "song",
    "name",
    "название",
    "трек",
    "artist name(s)",
    "artist(s)",
    "artists",
    "artist",
    "исполнитель",
    "артист",
    "album name",
    "album",
    "альбом",
    "isrc",
    "track uri",
    "spotify id",
    "duration (ms)",
    "duration_ms",
    "track duration (ms)",
}


def _looks_like_csv(text: str) -> bool:
    stripped = text.lstrip("\ufeff").strip()
    if not stripped:
        return False
    first = stripped.splitlines()[0]
    if "," not in first:
        return False
    try:
        cols = [c.strip().lower() for c in next(csv.reader([first]))]
    except Exception:  # noqa: BLE001
        return False
    return len(cols) >= 2 and sum(c in _CSV_KNOWN_HEADERS for c in cols) >= 2


def _parse_csv(text: str, fallback_title: str) -> ParsedPlaylist:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    headers = {h.strip().lower(): h for h in (reader.fieldnames or []) if h}

    def pick(row: dict, *names: str) -> str:
        for n in names:
            col = headers.get(n)
            if col and row.get(col) is not None:
                val = str(row[col]).strip()
                if val:
                    return val
        return ""

    tracks: list[TrackRef] = []
    for i, row in enumerate(reader):
        title = PlaylistParser.clean_title(
            pick(row, "track name", "title", "song", "name", "название", "трек")
        )
        if not title:
            continue
        raw_artist = pick(row, "artist name(s)", "artist(s)", "artists", "artist", "исполнитель", "артист")
        artists = PlaylistParser.split_artists(raw_artist) or ["Unknown"]
        album = pick(row, "album name", "album", "альбом")
        isrc = pick(row, "isrc") or None
        dur_ms = pick(row, "duration (ms)", "duration_ms", "track duration (ms)")
        dur_s = pick(row, "duration_sec", "duration", "seconds")
        duration_sec = 0
        if dur_ms.isdigit():
            duration_sec = seconds_from_ms(int(dur_ms))
        elif dur_s.isdigit():
            duration_sec = int(dur_s)
        tracks.append(
            TrackRef(
                title=title,
                artists=artists,
                album=album,
                duration_sec=duration_sec,
                isrc=isrc,
                external_id=pick(row, "track uri", "spotify id", "id"),
                position=i,
            )
        )
    if not tracks:
        raise ParseError("text: CSV contained no tracks")
    return ParsedPlaylist(
        platform="text",
        ref="csv",
        title=fallback_title or "Imported CSV",
        tracks=tracks,
    )


def _parse_m3u(text: str, fallback_title: str) -> ParsedPlaylist:
    tracks: list[TrackRef] = []
    pending_dur = 0
    pending_title: str | None = None
    playlist_name = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#PLAYLIST:"):
            playlist_name = s.split(":", 1)[1].strip()
            continue
        m = _EXTINF_RE.match(s)
        if m:
            pending_dur = max(0, int(m.group(1)))
            pending_title = m.group(2).strip()
            continue
        if s.startswith("#"):
            continue
        label = pending_title or Path(s).stem
        tr = _split_line_track(label, len(tracks), duration_sec=pending_dur)
        pending_dur = 0
        pending_title = None
        if tr is not None:
            tr.url = s
            tracks.append(tr)
    if pending_title:
        tr = _split_line_track(pending_title, len(tracks), duration_sec=pending_dur)
        if tr is not None:
            tracks.append(tr)
    if not tracks:
        raise ParseError("text: M3U contained no tracks")
    return ParsedPlaylist(
        platform="text",
        ref="m3u",
        title=playlist_name or fallback_title or "Imported M3U",
        tracks=tracks,
    )


class TextListParser(PlaylistParser):
    platform = "text"
    aliases = ("csv", "m3u", "m3u8", "tracklist", "list", "spotify-csv")
    url_hosts = ()

    def can_parse(self, ref: str) -> bool:
        s = (ref or "").strip()
        if not s or s.startswith(("http://", "https://")):
            return False
        if "\n" in s or "#EXTM3U" in s or "#EXTINF:" in s:
            return True
        if s.lower().endswith((".txt", ".csv", ".m3u", ".m3u8")):
            return True
        return _looks_like_csv(s)

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        text, file_title = _load_source(ref)
        if not text:
            raise ParseError("text: empty tracklist")
        if "#EXTM3U" in text or "#EXTINF:" in text:
            return _parse_m3u(text, file_title)
        if _looks_like_csv(text):
            return _parse_csv(text, file_title)

        tracks: list[TrackRef] = []
        for raw_line in text.splitlines():
            s = raw_line.strip()
            if not s or s.startswith("#"):
                continue
            tr = _split_line_track(s, len(tracks))
            if tr is not None:
                tracks.append(tr)
        if not tracks:
            raise ParseError("text: no valid 'Artist - Title' lines found")
        return ParsedPlaylist(
            platform=self.platform,
            ref="text",
            title=file_title or "Imported tracklist",
            tracks=tracks,
        )
