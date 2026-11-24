"""Playlist parsing core: normalised models + shared helpers.

The agent layer parses playlists from external platforms WITHOUT touching the
server connectors (kwhale-v3/server/app/connectors). Parsers are standalone,
verified on their own test stand, and only then wired into the import flow.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone


class ParseError(RuntimeError):
    """Playlist could not be parsed (bad ref, network, missing auth...)."""


@dataclass
class TrackRef:
    """One playlist entry, normalised across platforms."""

    title: str
    artists: list[str]
    album: str = ""
    duration_sec: int = 0
    isrc: str | None = None
    external_id: str = ""
    url: str = ""
    cover_url: str = ""
    position: int = 0

    @property
    def artist_str(self) -> str:
        return ", ".join(self.artists)

    @property
    def match_key(self) -> str:
        return f"{self.artist_str} - {self.title}".lower()

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "artists": self.artists,
            "album": self.album,
            "durationSec": self.duration_sec,
            "isrc": self.isrc,
            "externalId": self.external_id,
            "url": self.url,
            "coverUrl": self.cover_url,
            "position": self.position,
        }


@dataclass
class ParsedPlaylist:
    """A parsed playlist: metadata + ordered track list."""

    platform: str
    ref: str
    title: str
    tracks: list[TrackRef]
    url: str = ""
    owner: str = ""
    description: str = ""
    truncated: bool = False
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "ref": self.ref,
            "url": self.url,
            "title": self.title,
            "owner": self.owner,
            "description": self.description,
            "trackCount": self.track_count,
            "truncated": self.truncated,
            "fetchedAt": self.fetched_at,
            "tracks": [t.to_dict() for t in self.tracks],
        }


class PlaylistParser:
    """Base class: one platform parser per module."""

    platform: str = ""
    aliases: tuple[str, ...] = ()
    url_hosts: tuple[str, ...] = ()
    needs_auth: bool = False

    def can_parse(self, ref: str) -> bool:
        """True when this parser recognises the ref (URL or id)."""
        return False

    async def fetch_playlist(self, ref: str) -> ParsedPlaylist:
        raise NotImplementedError

    # ── shared normalisation helpers ─────────────────────────────────────

    @staticmethod
    def split_artists(text: str) -> list[str]:
        """'A feat. B, C & D' -> ['A', 'B', 'C', 'D'] (same spirit as the server)."""
        if not text:
            return []
        parts = re.split(
            r"\s*(?:,|;|/|&|,?\s+(?:feat|ft|featuring|with|vs|vs\.|x)\.?\s+)\s*",
            text,
            flags=re.IGNORECASE,
        )
        return [p.strip() for p in parts if p and p.strip()]

    @staticmethod
    def clean_title(title: str) -> str:
        """Strip trailing ' - Topic'-style noise and collapse whitespace."""
        t = unicodedata.normalize("NFKC", title or "")
        t = re.sub(r"\s+", " ", t).strip()
        t = re.sub(r"\s*-\s*Topic$", "", t)
        return t

    @staticmethod
    def strip_match_noise(title: str) -> str:
        """Strip parenthetical edition/feat suffixes for fallback catalog search."""
        t = PlaylistParser.clean_title(title)
        noise_re = re.compile(
            r"\s*[\(\[](?:feat\.?|ft\.?|featuring|with|remaster(?:ed)?(?:\s+\d{4})?|"
            r"\d{4}\s+remaster(?:ed)?|explicit|clean|deluxe(?:\s+edition)?|"
            r"bonus\s+track|official\s+(?:video|audio|music\s+video|lyric\s+video)|lyrics?)"
            r"[^\)\]]*[\)\]]\s*$",
            re.IGNORECASE,
        )
        while True:
            updated = noise_re.sub("", t).strip()
            if updated == t:
                break
            t = updated
        t = re.sub(r"\s+(?:feat|ft)\.?\s+.+$", "", t, flags=re.IGNORECASE).strip()
        return t

    @staticmethod
    def artist_title_from_label(label: str, uploader: str = "") -> tuple[list[str], str]:
        """'Artist - Title' -> (['Artist'], 'Title'); falls back to uploader."""
        label = (label or "").strip()
        if " - " in label:
            left, _, right = label.partition(" - ")
            if left.strip() and right.strip():
                return PlaylistParser.split_artists(left), PlaylistParser.clean_title(right)
        return ([uploader] if uploader else []), PlaylistParser.clean_title(label)

    @staticmethod
    def similarity(a: str, b: str) -> float:
        """0..100 fuzzy ratio (difflib stands in for the server's fuzzywuzzy WRatio)."""
        return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio() * 100


def seconds_from_ms(ms: int | float | None) -> int:
    try:
        return int(round((ms or 0) / 1000))
    except (TypeError, ValueError):
        return 0
