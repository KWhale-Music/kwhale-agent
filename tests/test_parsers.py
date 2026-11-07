"""Parser tests on recorded payloads — no network (test stand)."""

import pytest

from kwhale_agent.playlists import get_parser
from kwhale_agent.playlists.base import ParseError

YANDEX_PL = {
    "result": {
        "title": "Мой плейлист",
        "description": "тест",
        "trackCount": 2,
        "owner": {"uid": "alice", "name": "Alice"},
        "tracks": [
            {
                "track": {
                    "id": 11,
                    "title": "First Song",
                    "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                    "albums": [{"title": "Album 1", "coverUri": "avatars.yandex.net/x/%%"}],
                    "durationMs": 215000,
                }
            },
            {
                "track": {
                    "id": 12,
                    "title": "Second Song",
                    "artists": [{"name": "Artist C"}],
                    "albums": [{"title": "Album 2"}],
                    "durationMs": 180000,
                    "error": "not-available",
                }
            },
        ],
    }
}

SC_PL = {
    "kind": "playlist",
    "title": "My Set",
    "description": "desc",
    "permalink_url": "https://soundcloud.com/artist/sets/my-set",
    "track_count": 1,
    "user": {"username": "Artist"},
    "tracks": [
        {
            "id": 1,
            "title": "Someone - Great Track",
            "duration": 125000,
            "permalink_url": "https://soundcloud.com/artist/great-track",
            "artwork_url": "https://i1.sndcdn.com/artworks-x-large.jpg",
            "user": {"username": "Uploader"},
        }
    ],
}

YTM_BROWSE = {
    "contents": {
        "singleColumnBrowseResultsRenderer": {
            "tabs": [
                {
                    "tabRenderer": {
                        "content": {
                            "sectionListRenderer": {
                                "contents": [
                                    {
                                        "musicPlaylistShelfRenderer": {
                                            "contents": [
                                                {
                                                    "musicResponsiveListItemRenderer": {
                                                        "flexColumns": [
                                                            {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": "YTM Song"}]}}},
                                                            {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": "YTM Artist"}]}}},
                                                            {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": "YTM Album"}]}}},
                                                        ],
                                                        "fixedColumns": [
                                                            {"musicResponsiveListItemFixedColumnRenderer": {"text": {"runs": [{"text": "3:35"}]}}}
                                                        ],
                                                        "playlistItemData": {"videoId": "vid123"},
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            ]
        }
    }
}


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_yandex_parse(monkeypatch):
    import httpx

    def fake_client(*a, **kw):
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, **kw):
                return _FakeResp(YANDEX_PL)

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    pl = await get_parser("yandex").fetch_playlist("https://music.yandex.ru/playlist/alice-2")
    assert pl.title == "Мой плейлист"
    assert pl.owner == "Alice"
    # the error-marked track is dropped
    assert pl.track_count == 1
    t = pl.tracks[0]
    assert t.title == "First Song"
    assert t.artists == ["Artist A", "Artist B"]
    assert t.duration_sec == 215
    assert t.cover_url.startswith("https://avatars.yandex.net")


@pytest.mark.asyncio
async def test_soundcloud_parse(monkeypatch):
    import httpx

    from kwhale_agent.playlists import soundcloud as sc

    monkeypatch.setattr(sc, "scrape_client_id", lambda http: _async_cid())

    def fake_client(*a, **kw):
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, **kw):
                return _FakeResp(SC_PL)

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    pl = await get_parser("soundcloud").fetch_playlist("https://soundcloud.com/artist/sets/my-set")
    assert pl.title == "My Set"
    assert pl.track_count == 1
    t = pl.tracks[0]
    assert t.artists == ["Someone"] and t.title == "Great Track"
    assert t.duration_sec == 125


async def _async_cid():
    return "cid"


@pytest.mark.asyncio
async def test_ytm_parse(monkeypatch):
    import httpx

    def fake_client(*a, **kw):
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def post(self, url, **kw):
                return _FakeResp(YTM_BROWSE)

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    pl = await get_parser("ytm").fetch_playlist("https://music.youtube.com/playlist?list=PLabc1234567890")
    assert pl.track_count == 1
    t = pl.tracks[0]
    assert t.title == "YTM Song" and t.artists == ["YTM Artist"]
    assert t.album == "YTM Album"
    assert t.duration_sec == 215
    assert t.external_id == "vid123"


@pytest.mark.asyncio
async def test_vk_without_token_errors(monkeypatch):
    monkeypatch.delenv("Kwhale_AGENT_VK_TOKEN", raising=False)
    with pytest.raises(ParseError, match="Kwhale_AGENT_VK_TOKEN"):
        await get_parser("vk").fetch_playlist("https://vk.com/music/album/1_2")
