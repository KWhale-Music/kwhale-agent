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
    def __init__(self, payload, status=200, url="", text=""):
        self._payload = payload
        self.status_code = status
        self.url = url
        self.text = text

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
    monkeypatch.delenv("KWHALE_AGENT_VK_TOKEN", raising=False)
    monkeypatch.delenv("Kwhale_AGENT_VK_TOKEN", raising=False)
    with pytest.raises(ParseError, match="KWHALE_AGENT_VK_TOKEN"):
        await get_parser("vk").fetch_playlist("https://vk.com/music/album/1_2")


@pytest.mark.asyncio
async def test_vk_uses_canonical_and_legacy_env(monkeypatch):
    import httpx

    seen = []

    def fake_client(*a, **kw):
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, params=None, **kw):
                seen.append((params or {}).get("access_token"))
                return _FakeResp({"response": {"items": [{"id": 1, "artist": "Art", "title": "Song", "duration": 90}]}})

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.delenv("Kwhale_AGENT_VK_TOKEN", raising=False)
    monkeypatch.setenv("KWHALE_AGENT_VK_TOKEN", "tok-upper")
    pl = await get_parser("vk").fetch_playlist("https://vk.com/music/album/1_2")
    assert pl.track_count == 1 and seen[-1] == "tok-upper"

    monkeypatch.delenv("KWHALE_AGENT_VK_TOKEN", raising=False)
    monkeypatch.setenv("Kwhale_AGENT_VK_TOKEN", "tok-legacy")
    await get_parser("vk").fetch_playlist("1_2")
    assert seen[-1] == "tok-legacy"


@pytest.mark.asyncio
async def test_yandex_short_redirect_and_stub_hydration(monkeypatch):
    import httpx

    pl_with_stub = {
        "result": {
            "title": "Long Mix",
            "trackCount": 2,
            "owner": {"name": "Bob"},
            "tracks": [
                {"id": 11, "track": {"id": 11, "title": "Inline", "artists": [{"name": "A"}], "durationMs": 120000}},
                {"id": 22, "albumId": 5},
            ],
        }
    }
    hydrated_resp = {
        "result": [
            {"id": 22, "title": "Hydrated Song", "artists": [{"name": "B"}], "durationMs": 180000},
        ]
    }

    def fake_client(*a, **kw):
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, **kw):
                if "playlists/lk.short" in url:
                    return _FakeResp({}, url="https://music.yandex.ru/users/bob/playlists/77")
                return _FakeResp(pl_with_stub)

            async def post(self, url, data=None, **kw):
                assert data == {"track-ids": "22"}
                return _FakeResp(hydrated_resp)

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    pl = await get_parser("yandex").fetch_playlist("https://music.yandex.ru/playlists/lk.short")
    assert pl.ref == "bob/77"
    assert pl.track_count == 2
    assert [t.title for t in pl.tracks] == ["Inline", "Hydrated Song"]


@pytest.mark.asyncio
async def test_soundcloud_short_link_redirect(monkeypatch):
    import httpx

    from kwhale_agent.playlists import soundcloud as sc

    monkeypatch.setattr(sc, "scrape_client_id", lambda http: _async_cid())
    calls = []

    def fake_client(*a, **kw):
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, params=None, **kw):
                calls.append((url, params))
                if "on.soundcloud.com" in url:
                    return _FakeResp({}, url="https://soundcloud.com/artist/sets/my-set")
                return _FakeResp(SC_PL)

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    pl = await get_parser("soundcloud").fetch_playlist("https://on.soundcloud.com/xyz")
    assert pl.title == "My Set"
    assert calls[1][1]["url"] == "https://soundcloud.com/artist/sets/my-set"


@pytest.mark.asyncio
async def test_textlist_plain_csv_m3u_and_file(tmp_path):
    from kwhale_agent.playlists import fetch_playlist

    plain = "1. Artist A, Artist B — First Track [03:20]\n- Artist C - Second Track"
    p_plain = await fetch_playlist("text", plain)
    assert [t.title for t in p_plain.tracks] == ["First Track", "Second Track"]
    assert p_plain.tracks[0].artists == ["Artist A", "Artist B"]
    assert p_plain.tracks[0].duration_sec == 200

    csv_payload = (
        "Track Name,Artist Name(s),Album Name,Duration (ms),ISRC\n"
        "\"Song CSV\",\"Solo\",Album X,210000,USUM70000009\n"
    )
    p_csv = await fetch_playlist("", csv_payload)
    assert p_csv.platform == "text"
    assert p_csv.tracks[0].isrc == "USUM70000009"
    assert p_csv.tracks[0].duration_sec == 210

    m3u_file = tmp_path / "Roadtrip.m3u8"
    m3u_file.write_text("#EXTM3U\n#EXTINF:185,Band One - Highway\n/music/highway.flac\n", encoding="utf-8")
    p_m3u = await fetch_playlist("", str(m3u_file))
    assert p_m3u.title == "Roadtrip"
    assert p_m3u.tracks[0].duration_sec == 185
    assert p_m3u.tracks[0].title == "Highway"


@pytest.mark.asyncio
async def test_spotify_url_gives_actionable_hint(monkeypatch):
    from kwhale_agent.playlists import fetch_playlist
    from kwhale_agent.playlists import ytdlp_fallback as fb

    async def fail_ytdlp(self, ref):
        raise ParseError("unsupported")

    monkeypatch.setattr(fb.YtdlpFallbackParser, "fetch_playlist", fail_ytdlp)
    with pytest.raises(ParseError, match="platform='text'"):
        await fetch_playlist("", "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
