"""Bridge request handling tests (httpx.MockTransport, no network)."""

import httpx
import pytest

from kwhale_agent.bridge import KwhaleBridge


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
