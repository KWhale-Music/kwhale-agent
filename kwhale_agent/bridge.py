"""HTTP bridge to the kwhale server (/v1 public API + Bearer auth).

The agent layer talks to kwhale ONLY through the public API — no direct DB or
in-process imports — so nothing in the server needs to change.

Auth: login with email/password -> short Bearer access JWT + rotating refresh
token (refresh-on-401 via /auth/refresh, fallback to re-login). Credentials and
base URL can come from env (KWHALE_BASE_URL, KWHALE_EMAIL, KWHALE_PASSWORD) or
be supplied at runtime by the user via MCP login() / bridge.configure().
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:19001/v1"


def normalize_base_url(raw: str | None) -> str:
    """Normalize a KWhale server URL so it ends with '/v1' (without trailing slash)."""
    s = (raw or "").strip().rstrip("/")
    if not s:
        return ""
    if not s.endswith("/v1"):
        s = f"{s}/v1"
    return s


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
        refresh_token: str | None = None,
    ):
        env_url = normalize_base_url(os.environ.get("KWHALE_BASE_URL"))
        arg_url = normalize_base_url(base_url)
        self.has_explicit_url = bool(arg_url or env_url)
        self.base_url = arg_url or env_url or DEFAULT_LOCAL_BASE_URL
        self.email = (email if email is not None else os.environ.get("KWHALE_EMAIL") or "").strip()
        self.password = password if password is not None else (os.environ.get("KWHALE_PASSWORD") or "")
        self.token = token or ""
        self.refresh_token = refresh_token or ""
        self._http = httpx.AsyncClient(timeout=30.0)

    def configure(
        self,
        *,
        base_url: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        """Update connection URL and/or account credentials in memory."""
        if base_url is not None:
            normalized = normalize_base_url(base_url)
            if not normalized:
                raise BridgeError("base_url must not be empty")
            if normalized != self.base_url:
                self.token = ""
                self.refresh_token = ""
            self.base_url = normalized
            self.has_explicit_url = True
        if email is not None:
            clean_email = email.strip()
            if clean_email != self.email:
                self.token = ""
                self.refresh_token = ""
            self.email = clean_email
        if password is not None:
            self.password = password

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── core request handling ───────────────────────────────────────────

    async def _send(self, method: str, path: str, **kw: Any) -> httpx.Response:
        headers = dict(kw.pop("headers", {}))
        retry_ok = kw.pop("auth_retry", True)  # internal flag, never reaches httpx
        if self.token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.base_url}{path}"
        r = await self._http.request(method, url, headers=headers, **kw)
        if r.status_code == 401 and retry_ok:
            refreshed = False
            if self.refresh_token:
                try:
                    await self.refresh()
                    refreshed = True
                except BridgeError:
                    self.refresh_token = ""
                    self.token = ""
            if not refreshed and self.email and self.password:
                await self.login()
                refreshed = True
            if refreshed:
                return await self._send(method, path, auth_retry=False, **kw)
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
        return r

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        r = await self._send(method, path, **kw)
        if not r.content:
            return None
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return r.content

    @staticmethod
    def _idempotency_headers(idempotency_key: str | None) -> dict[str, str]:
        key = (idempotency_key or "").strip() or str(uuid.uuid4())
        return {"Idempotency-Key": key}

    # ── auth & profile ──────────────────────────────────────────────────

    async def login(self) -> dict:
        if not self.email or not self.password:
            raise BridgeError("no credentials: pass email/password to login() or set KWHALE_EMAIL/KWHALE_PASSWORD")
        out = await self._request(
            "POST",
            "/auth/login",
            json={"email": self.email, "password": self.password},
            auth_retry=False,
        )
        data = out or {}
        self.token = data.get("accessToken") or data.get("access_token") or ""
        self.refresh_token = data.get("refreshToken") or data.get("refresh_token") or ""
        return data

    async def refresh(self) -> dict:
        if not self.refresh_token:
            raise BridgeError("no refresh token")
        out = await self._request(
            "POST",
            "/auth/refresh",
            json={"refreshToken": self.refresh_token},
            auth_retry=False,
        )
        data = out or {}
        self.token = data.get("accessToken") or data.get("access_token") or ""
        if data.get("refreshToken") or data.get("refresh_token"):
            self.refresh_token = data.get("refreshToken") or data.get("refresh_token") or ""
        return data

    async def logout(self) -> None:
        rt = self.refresh_token
        self.token = ""
        self.refresh_token = ""
        self.password = ""
        if rt:
            try:
                await self._request("POST", "/auth/logout", json={"refreshToken": rt}, auth_retry=False)
            except BridgeError:
                pass

    async def me(self) -> dict:
        return await self._request("GET", "/me") or {}

    async def update_profile(self, display_name: str) -> dict:
        return await self._request("PATCH", "/me", json={"displayName": display_name}) or {}

    # ── catalog / search ────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        limit: int = 10,
        *,
        wait: bool = True,
        search_type: str = "all",
    ) -> list[dict]:
        params: dict[str, Any] = {"q": query, "limit": limit}
        if search_type and search_type != "all":
            params["type"] = search_type
        if wait:
            params["wait"] = "true"
        out = await self._request("GET", "/search", params=params)
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

    async def get_track_info(self, track_id: int | str) -> dict:
        return await self._request("GET", f"/tracks/{track_id}/info") or {}

    async def get_lyrics(self, track_id: int | str) -> dict:
        return await self._request("GET", f"/tracks/{track_id}/lyrics") or {}

    async def similar_tracks(self, track_id: int | str, limit: int = 20) -> list[dict]:
        out = await self._request("GET", f"/tracks/{track_id}/similar", params={"limit": limit}) or {}
        return out.get("items") or []

    async def like_track(self, track_id: int | str) -> None:
        await self._request("PUT", f"/tracks/{track_id}/like")

    async def unlike_track(self, track_id: int | str) -> None:
        await self._request("DELETE", f"/tracks/{track_id}/like")

    async def dislike_track(self, track_id: int | str) -> None:
        await self._request("PUT", f"/tracks/{track_id}/dislike")

    async def undislike_track(self, track_id: int | str) -> None:
        await self._request("DELETE", f"/tracks/{track_id}/dislike")

    async def health(self) -> dict:
        return await self._request("GET", "/health") or {}

    async def config(self) -> dict:
        return await self._request("GET", "/config") or {}

    # ── playlists (profile) ─────────────────────────────────────────────

    async def _paginate(self, path: str, params: dict[str, Any] | None = None, *, max_pages: int = 50) -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        for _ in range(max_pages):
            q = dict(params or {})
            if cursor:
                q["cursor"] = cursor
            page = await self._request("GET", path, params=q) or {}
            chunk = page.get("items") or []
            items.extend(chunk)
            cursor = page.get("nextCursor")
            if not cursor or not chunk:
                break
        return items

    async def list_playlists(self, owner: str = "me", limit: int = 100) -> list[dict]:
        return await self._paginate("/playlists", {"owner": owner, "limit": min(max(1, limit), 100)})

    async def create_playlist(
        self,
        title: str,
        description: str = "",
        visibility: str = "private",
        idempotency_key: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"title": title, "description": description}
        if visibility != "private":
            payload["visibility"] = visibility
        return (
            await self._request(
                "POST",
                "/playlists",
                json=payload,
                headers=self._idempotency_headers(idempotency_key),
            )
            or {}
        )

    async def update_playlist(
        self,
        playlist_id: int | str,
        *,
        title: str | None = None,
        description: str | None = None,
        visibility: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if visibility is not None:
            payload["visibility"] = visibility
        return await self._request("PATCH", f"/playlists/{playlist_id}", json=payload) or {}

    async def delete_playlist(self, playlist_id: int | str) -> None:
        await self._request("DELETE", f"/playlists/{playlist_id}")

    async def add_tracks(
        self,
        playlist_id: int | str,
        track_ids: list[int | str],
        *,
        position: int | None = None,
        chunk_size: int = 500,
    ) -> dict:
        if not track_ids:
            return {}
        # Server enforces PlaylistTracksAdd.trackIds max_length=1000
        step = max(1, min(int(chunk_size), 1000))
        last: dict = {}
        next_pos = position
        for start in range(0, len(track_ids), step):
            batch = [str(t) for t in track_ids[start : start + step]]
            payload: dict[str, Any] = {"trackIds": batch}
            if next_pos is not None:
                payload["position"] = next_pos
                next_pos += len(batch)
            last = (
                await self._request(
                    "POST",
                    f"/playlists/{playlist_id}/tracks",
                    json=payload,
                    headers=self._idempotency_headers(None),
                )
                or {}
            )
        return last

    async def remove_track(self, playlist_id: int | str, track_id: int | str) -> None:
        await self._request("DELETE", f"/playlists/{playlist_id}/tracks/{track_id}")

    async def reorder_tracks(self, playlist_id: int | str, track_ids: list[int | str]) -> dict:
        return (
            await self._request(
                "PUT",
                f"/playlists/{playlist_id}/tracks/order",
                json={"trackIds": [str(t) for t in track_ids]},
            )
            or {}
        )

    async def follow_playlist(self, playlist_id: int | str) -> None:
        await self._request("PUT", f"/playlists/{playlist_id}/follow")

    async def unfollow_playlist(self, playlist_id: int | str) -> None:
        await self._request("DELETE", f"/playlists/{playlist_id}/follow")

    async def like_playlist_tracks(
        self, playlist_id: int | str, idempotency_key: str | None = None
    ) -> dict:
        return (
            await self._request(
                "PUT",
                f"/playlists/{playlist_id}/tracks/like",
                headers=self._idempotency_headers(idempotency_key),
            )
            or {}
        )

    async def list_playlist_tracks(self, playlist_id: int | str) -> list[dict]:
        return await self._paginate(f"/playlists/{playlist_id}/tracks", {"limit": 100})

    async def get_playlist(self, playlist_id: int | str, *, full_tracks: bool = True) -> dict:
        pl = await self._request("GET", f"/playlists/{playlist_id}") or {}
        if full_tracks and int(pl.get("trackCount") or 0) > len(pl.get("tracks") or []):
            pl = {**pl, "tracks": await self.list_playlist_tracks(playlist_id)}
        return pl

    # ── uploads, library, recommendations, shares ──────────────────────

    async def upload_track(
        self,
        file_path: str | Path,
        *,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
    ) -> dict:
        p = Path(file_path)
        if not p.is_file():
            raise BridgeError(f"audio file not found: {file_path}")
        data: dict[str, str] = {}
        if title:
            data["title"] = title
        if artist:
            data["artist"] = artist
        if album:
            data["album"] = album
        with p.open("rb") as fh:
            return (
                await self._request(
                    "POST",
                    "/uploads/tracks",
                    files={"file": (p.name, fh, "application/octet-stream")},
                    data=data,
                    timeout=120.0,
                )
                or {}
            )

    async def list_enrichments(self) -> list[dict]:
        out = await self._request("GET", "/uploads/enrichments") or {}
        return out.get("items") or []

    async def confirm_enrichment(self, proposal_id: int | str) -> dict:
        return await self._request("POST", f"/uploads/enrichments/{proposal_id}/confirm") or {}

    async def reject_enrichment(self, proposal_id: int | str) -> dict:
        return await self._request("POST", f"/uploads/enrichments/{proposal_id}/reject") or {}

    async def list_library(self, section: str = "tracks", *, limit: int = 50, query: str | None = None) -> dict:
        sec = section.strip().lower()
        lim = min(max(1, limit), 100)
        if sec == "history":
            return await self._request("GET", "/history", params={"limit": lim}) or {}
        if sec not in ("tracks", "playlists", "albums"):
            raise BridgeError(f"unknown library section: {section}")
        params: dict[str, Any] = {"limit": lim}
        if query and sec == "tracks":
            params["q"] = query
        return await self._request("GET", f"/library/{sec}", params=params) or {}

    async def list_mixes(self) -> list[dict]:
        out = await self._request("GET", "/mixes") or {}
        return out.get("items") or []

    async def get_mix_tracks(self, mix_id: str, limit: int = 40) -> list[dict]:
        out = await self._request("GET", f"/mixes/{mix_id}/tracks", params={"limit": limit}) or {}
        return out.get("items") or []

    async def prompt_mix(
        self,
        prompt: str,
        *,
        size: int = 40,
        llm_api_key: str | None = None,
        llm_endpoint: str | None = None,
        llm_model: str | None = None,
    ) -> list[dict]:
        payload: dict[str, Any] = {"prompt": prompt, "size": size}
        if llm_api_key:
            payload["llmApiKey"] = llm_api_key
        if llm_endpoint:
            payload["llmEndpoint"] = llm_endpoint
        if llm_model:
            payload["llmModel"] = llm_model
        out = await self._request("POST", "/mixes/prompt", json=payload, timeout=60.0) or {}
        return out.get("items") or []

    async def create_share(self, kind: str, entity_id: int | str) -> dict:
        return await self._request("POST", "/share", json={"kind": kind, "id": str(entity_id)}) or {}

    async def get_share(self, share_id: str) -> dict:
        return await self._request("GET", f"/share/{share_id}") or {}

    # ── downloads ───────────────────────────────────────────────────────

    async def request_library_download(self, track_id: int | str) -> dict:
        """Put the track into the server's library download queue.

        Server semantics: liking a track enqueues its library download
        (favorites -> downloader.enqueue_if_needed), so this is a like.
        """
        return await self._request("PUT", f"/tracks/{track_id}/like") or {}

    async def download_file(self, track_id: int | str, dest_dir: str) -> str:
        """Download the audio file via /tracks/{id}/download to dest_dir."""
        r = await self._send("GET", f"/tracks/{track_id}/download", timeout=120.0)
        cd = r.headers.get("content-disposition", "")
        raw_name = f"track-{track_id}.mp3"
        if "filename=" in cd:
            candidate = cd.split("filename=")[-1].strip().strip('"; ')
            if candidate:
                raw_name = candidate
        safe_name = Path(raw_name).name or f"track-{track_id}.mp3"
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / safe_name
        path.write_bytes(r.content)
        return str(path)
