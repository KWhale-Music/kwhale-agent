"""Import flow test: parse -> fuzzy match -> playlist in the profile (fake bridge)."""

import pytest

from kwhale_agent.importer import best_match, import_playlist
from kwhale_agent.playlists.base import ParsedPlaylist, TrackRef


class FakeBridge:
    def __init__(self, catalog):
        self.catalog = catalog  # query-substring -> track dicts
        self.created = []
        self.added = []

    async def search(self, query, limit=10):
        q = query.lower()
        return [t for k, v in self.catalog.items() if k in q for t in v]

    async def create_playlist(self, title, description=""):
        self.created.append({"title": title, "description": description})
        return {"id": 42, "title": title}

    async def add_tracks(self, playlist_id, track_ids):
        self.added.append((playlist_id, list(track_ids)))
        return {"id": playlist_id}


def _pl(*tracks):
    return ParsedPlaylist(platform="yandex", ref="u/1", title="My Mix", tracks=list(tracks))


def test_best_match_threshold():
    ref = TrackRef(title="Song", artists=["Artist"])
    candidates = [
        {"id": 1, "title": "Song", "artists": ["Artist"]},
        {"id": 2, "title": "Totally Different", "artists": ["Nobody"]},
    ]
    hit = best_match(ref, candidates)
    assert hit and hit["id"] == 1
    near = [{"id": 3, "title": "Song", "artists": ["Artis"]}]  # fuzzy, not exact
    assert best_match(ref, near, threshold=99) is None


def test_best_match_isrc_exact():
    ref = TrackRef(title="Wrong Title", artists=["Wrong"], isrc="USUM70000001")
    candidates = [{"id": 7, "title": "Real", "artists": ["Real"], "isrc": "USUM70000001"}]
    hit = best_match(ref, candidates)
    assert hit and hit["id"] == 7


@pytest.mark.asyncio
async def test_import_creates_playlist_and_reports():
    bridge = FakeBridge(
        {
            "artist a": [{"id": 100, "title": "First Song", "artists": ["Artist A"]}],
            "artist c": [{"id": 200, "title": "Second Song", "artists": ["Artist C"]}],
        }
    )
    parsed = _pl(
        TrackRef(title="First Song", artists=["Artist A"], position=0),
        TrackRef(title="Missing Song", artists=["Nobody Here"], position=1),
    )
    report = await import_playlist(bridge, parsed)

    assert report["playlistId"] == 42
    assert report["matchedCount"] == 1 and report["unmatchedCount"] == 1
    assert report["matched"][0]["trackId"] == 100
    assert report["unmatched"][0]["reason"] == "no catalog match"
    assert bridge.created and bridge.created[0]["title"] == "My Mix (yandex)"
    assert bridge.added == [(42, [100])]


@pytest.mark.asyncio
async def test_import_dry_run_touches_nothing():
    bridge = FakeBridge({"artist a": [{"id": 100, "title": "First Song", "artists": ["Artist A"]}]})
    parsed = _pl(TrackRef(title="First Song", artists=["Artist A"]))
    report = await import_playlist(bridge, parsed, dry_run=True)
    assert report["playlistId"] is None
    assert report["matchedCount"] == 1
    assert bridge.created == [] and bridge.added == []
