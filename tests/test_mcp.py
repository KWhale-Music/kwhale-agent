"""MCP server tool tests (in-session login, playlist editing, uploads, shares)."""

import httpx
import pytest

from kwhale_agent import mcp_server
from kwhale_agent.bridge import KwhaleBridge


@pytest.fixture(autouse=True)
def _reset_bridge(monkeypatch):
    monkeypatch.delenv("KWHALE_BASE_URL", raising=False)
    monkeypatch.delenv("KWHALE_EMAIL", raising=False)
    monkeypatch.delenv("KWHALE_PASSWORD", raising=False)
    mcp_server._bridge = None
    yield
    mcp_server._bridge = None


@pytest.mark.asyncio
async def test_login_requires_explicit_url_when_env_missing():
    res = await mcp_server.login("user@example.com", "secret")
    assert "error" in res and "base_url" in res["error"]


@pytest.mark.asyncio
async def test_login_and_playlist_editing_tools(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(
                200,
                json={"accessToken": "JWT1", "refreshToken": "RT1", "user": {"id": "1", "email": "u@x.org"}},
            )
        if request.url.path == "/v1/playlists" and request.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "10", "title": "Favs"}], "nextCursor": None})
        if request.url.path == "/v1/playlists/10/tracks" and request.method == "POST":
            return httpx.Response(200, json={"id": "10", "trackCount": 2})
        if request.url.path == "/v1/uploads/tracks" and request.method == "POST":
            return httpx.Response(201, json={"id": "99", "title": "Uploaded"})
        if request.url.path == "/v1/share" and request.method == "POST":
            return httpx.Response(200, json={"id": "abc", "shareUrl": "https://music.example.org/share/s/abc"})
        return httpx.Response(200, json={})

    b = KwhaleBridge()
    b._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    mcp_server._bridge = b

    out = await mcp_server.login("u@x.org", "secret123", base_url="https://music.example.org")
    assert out["ok"] is True
    assert out["baseUrl"] == "https://music.example.org/v1"
    assert "secret123" not in str(out)
    assert "JWT1" not in str(out)

    pls = await mcp_server.list_playlists()
    assert pls == [{"id": "10", "title": "Favs"}]

    added = await mcp_server.add_tracks_to_playlist("10", ["5", "6"])
    assert added["trackCount"] == 2

    audio = tmp_path / "demo.mp3"
    audio.write_bytes(b"ID3...")
    uploaded = await mcp_server.upload_track(str(audio), title="Uploaded")
    assert uploaded["id"] == "99"

    shared = await mcp_server.create_share_link("track", "99")
    assert shared["shareUrl"].endswith("/share/s/abc")


@pytest.mark.asyncio
async def test_parse_track_list_tool():
    res = await mcp_server.parse_track_list("Artist A - Track One\nArtist B - Track Two", title="My List")
    assert res["title"] == "My List"
    assert res["trackCount"] == 2
