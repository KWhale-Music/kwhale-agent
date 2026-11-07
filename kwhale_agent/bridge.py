"""HTTP bridge to the kwhale server (/v1 public API + Bearer auth).

The agent layer talks to kwhale ONLY through the public API — no direct DB or
in-process imports — so nothing in the server needs to change.

Auth: login with email/password -> Bearer token (refresh handled naively:
re-login on 401). Env defaults: KWHALE_BASE_URL, KWHALE_EMAIL, KWHALE_PASSWORD.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class BridgeError(RuntimeError):
    def __init__(self, message: str, status: int = 0, problem: dict | None = None):
        super().__init__(message)
        self.status = status
        self.problem = problem or {}


class KwhaleBridge:
    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        password: str | None = None,
        token: str | None = None,
    ):
        self.base_url = (base_url or os.environ.get("KWHALE_BASE_URL") or "http://127.0.0.1:19001/v1").rstrip("/")
        self.email = email or os.environ.get("KWHALE_EMAIL") or ""
        self.password = password or os.environ.get("KWHALE_PASSWORD") or ""
        self.token = token or ""
        self._http = httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── core request handling ───────────────────────────────────────────

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}))
        retry_ok = kw.pop("auth_retry", True)  # internal flag, never reaches httpx
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.base_url}{path}"
        r = await self._http.request(method, url, headers=headers, **kw)
        if r.status_code == 401 and self.email and self.password and retry_ok:
            await self.login()
            return await self._request(method, path, auth_retry=False, **kw)
        if r.status_code >= 400:
            try:
                problem = r.json()
            except Exception:  # noqa: BLE001
                problem = {"detail": r.text[:200]}
            raise BridgeError(
                f"{method} {path} -> HTTP {r.status_code}: {problem}",
                status=r.status_code,
                problem=problem if isinstance(problem, dict) else {},
            )
        if not r.content:
            return None
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return r.content

    # ── auth ────────────────────────────────────────────────────────────

    async def login(self) -> dict:
        if not self.email or not self.password:
            raise BridgeError("no credentials: set KWHALE_EMAIL/KWHALE_PASSWORD")
        out = await self._request(
            "POST", "/auth/login", json={"email": self.email, "password": self.password}, auth_retry=False
        )
        self.token = (out or {}).get("accessToken") or (out or {}).get("access_token") or ""
        return out or {}

    async def me(self) -> dict:
        return await self._request("GET", "/me")

    # ── catalog / search ────────────────────────────────────────────────

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        out = await self._request("GET", "/search", params={"q": query, "limit": limit})
        tracks = (out or {}).get("tracks") or []
        if isinstance(tracks, dict):  # section shape {items: [...]}
            tracks = tracks.get("items") or []
        normalized = []
        for t in tracks:
            artists = t.get("artists") or []
            names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in artists]
            normalized.append({**t, "artists": [n for n in names if n]})
        return normalized

    async def get_track(self, track_id: int | str) -> dict:
        return await self._request("GET", f"/tracks/{track_id}") or {}

    async def health(self) -> dict:
        return await self._request("GET", "/health") or {}

    async def config(self) -> dict:
        return await self._request("GET", "/config") or {}

    # ── playlists (profile) ─────────────────────────────────────────────

    async def list_playlists(self) -> list[dict]:
        out = await self._request("GET", "/playlists")
        return (out or {}).get("items") or []

    async def create_playlist(self, title: str, description: str = "") -> dict:
        return await self._request(
            "POST", "/playlists", json={"title": title, "description": description}
        ) or {}

    async def add_tracks(self, playlist_id: int | str, track_ids: list[int]) -> dict:
        if not track_ids:
            return {}
        return await self._request(
            "POST",
            f"/playlists/{playlist_id}/tracks",
            json={"trackIds": [str(t) for t in track_ids]},
        ) or {}

    async def get_playlist(self, playlist_id: int | str) -> dict:
        return await self._request("GET", f"/playlists/{playlist_id}") or {}

    # ── downloads ───────────────────────────────────────────────────────

    async def request_library_download(self, track_id: int | str) -> dict:
        """Put the track into the server's library download queue.

        Server semantics: liking a track enqueues its library download
        (favorites -> downloader.enqueue_if_needed), so this is a like.
        """
        return await self._request("PUT", f"/tracks/{track_id}/like") or {}

    async def download_file(self, track_id: int | str, dest_dir: str) -> str:
        """Download the audio file via /tracks/{id}/download to dest_dir."""
        import os as _os
        from pathlib import Path

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        r = await self._http.get(f"{self.base_url}/tracks/{track_id}/download", headers=headers)
        if r.status_code >= 400:
            raise BridgeError(f"download {track_id} -> HTTP {r.status_code}", status=r.status_code)
        cd = r.headers.get("content-disposition", "")
        name = f"track-{track_id}.mp3"
        if "filename=" in cd:
            name = cd.split("filename=")[-1].strip('"; ') or name
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / name
        path.write_bytes(r.content)
        return str(path)
