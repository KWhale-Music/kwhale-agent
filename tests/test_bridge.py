"""Bridge request handling tests (httpx.MockTransport, no network)."""

import json

import httpx
import pytest

from kwhale_agent.bridge import KwhaleBridge, normalize_base_url


def _bridge_with_transport(handler) -> KwhaleBridge:
    b = KwhaleBridge(base_url="http://test/v1", email="u@x.ru", password="pw")
    b._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


@pytest.mark.asyncio
async def test_request_retries_on_401_after_relogin():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"accessToken": "T2"})
        if request.headers.get("Authorization") == "Bearer T2":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401, json={"detail": "expired"})

    b = _bridge_with_transport(handler)
    out = await b._request("GET", "/me")
    assert out == {"ok": True}
    # GET /me (401) -> POST /auth/login -> GET /me with the fresh token
    assert [c[1] for c in calls] == ["/v1/me", "/v1/auth/login", "/v1/me"]


@pytest.mark.asyncio
async def test_request_raises_bridge_error_with_problem():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"type": "https://api.kwhale.example/problems/not-found"})

    from kwhale_agent.bridge import BridgeError

    b = _bridge_with_transport(handler)
    with pytest.raises(BridgeError) as e:
        await b._request("GET", "/tracks/1")
    assert e.value.status == 404
    assert e.value.problem.get("type", "").endswith("not-found")


@pytest.mark.asyncio
async def test_add_tracks_and_create_playlist_payloads():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = request.read()
        return httpx.Response(200, json={"id": "7"})

    b = _bridge_with_transport(handler)
    b.token = "T"
    pl = await b.create_playlist("My Mix", "desc")
    assert pl["id"] == "7"
    await b.add_tracks("7", [1, 2, 3])
    assert b'["1","2","3"]' in seen["/v1/playlists/7/tracks"]


@pytest.mark.asyncio
async def test_search_normalizes_artist_objects_and_sections():
    flat = {"tracks": [{"id": "1", "title": "T", "artists": [{"id": "9", "name": "A"}], "isrc": "X"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=flat)

    b = _bridge_with_transport(handler)
    rows = await b.search("q")
    assert rows[0]["artists"] == ["A"]

    section = {"tracks": {"items": [{"id": "2", "title": "U", "artists": [{"name": "B"}]}]}}

    def handler2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=section)

    b2 = _bridge_with_transport(handler2)
    rows2 = await b2.search("q")
    assert rows2[0]["artists"] == ["B"]


def test_normalize_base_url_and_configure():
    assert normalize_base_url("https://music.example.com/") == "https://music.example.com/v1"
    assert normalize_base_url("https://music.example.com/v1/") == "https://music.example.com/v1"

    b = KwhaleBridge()
    assert not b.has_explicit_url
    b.token = "OLD"
    b.configure(base_url="https://music.example.com", email="a@b.c", password="p")
    assert b.has_explicit_url
    assert b.base_url == "https://music.example.com/v1"
    assert b.token == ""


@pytest.mark.asyncio
async def test_refresh_token_before_relogin_on_401():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/auth/refresh"):
            return httpx.Response(200, json={"accessToken": "T2", "refreshToken": "R2"})
        if request.headers.get("Authorization") == "Bearer T2":
            return httpx.Response(200, json={"id": "1"})
        return httpx.Response(401, json={"code": "token_expired"})

    b = _bridge_with_transport(handler)
    b.token = "T1"
    b.refresh_token = "R1"
    me = await b.me()
    assert me["id"] == "1"
    assert b.refresh_token == "R2"
    assert [c[1] for c in calls] == ["/v1/me", "/v1/auth/refresh", "/v1/me"]


@pytest.mark.asyncio
async def test_search_passes_wait_true_and_add_tracks_chunks():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params), request.read(), request.headers.get("Idempotency-Key")))
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"tracks": []})
        return httpx.Response(200, json={"id": "9"})

    b = _bridge_with_transport(handler)
    await b.search("test", limit=15)
    assert seen[0][1]["wait"] == "true"

    await b.add_tracks("9", list(range(1, 1205)), position=0)
    adds = [s for s in seen if s[0].endswith("/tracks")]
    assert len(adds) == 3
    payload0 = json.loads(adds[0][2])
    payload1 = json.loads(adds[1][2])
    payload2 = json.loads(adds[2][2])
    assert len(payload0["trackIds"]) == 500 and payload0["position"] == 0
    assert len(payload1["trackIds"]) == 500 and payload1["position"] == 500
    assert len(payload2["trackIds"]) == 204 and payload2["position"] == 1000
    assert all(a[3] for a in adds)


@pytest.mark.asyncio
async def test_get_playlist_paginates_and_download_sanitizes_filename(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/playlists/5":
            return httpx.Response(200, json={"id": "5", "trackCount": 3, "tracks": [{"id": "1"}]})
        if request.url.path == "/v1/playlists/5/tracks":
            cursor = request.url.params.get("cursor")
            if not cursor:
                return httpx.Response(200, json={"items": [{"id": "1"}, {"id": "2"}], "nextCursor": "p2"})
            return httpx.Response(200, json={"items": [{"id": "3"}], "nextCursor": None})
        if request.url.path == "/v1/tracks/4/download":
            return httpx.Response(
                200,
                content=b"AUDIOBYTES",
                headers={"Content-Disposition": 'attachment; filename="../../evil.flac"'},
            )
        return httpx.Response(404)

    b = _bridge_with_transport(handler)
    pl = await b.get_playlist("5", full_tracks=True)
    assert [t["id"] for t in pl["tracks"]] == ["1", "2", "3"]

    saved = await b.download_file(4, str(tmp_path))
    assert saved == str(tmp_path / "evil.flac")
    assert (tmp_path / "evil.flac").read_bytes() == b"AUDIOBYTES"
