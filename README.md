<div align="center">

**English** | [Русский](README.ru.md)

<br/>

<img src="docs/images/cover.png" alt="KWhale Agent" width="100%"/>

# KWhale Agent

**An agent layer for KWhale — manage the library, edit the server, parse playlists, speak MCP.**

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio-8A2BE2.svg)](https://modelcontextprotocol.io/)
[![CI](https://github.com/KWhale-Music/kwhale-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/KWhale-Music/kwhale-agent/actions/workflows/ci.yml)

</div>

Everything an LLM agent needs to work with [KWhale Server](https://github.com/KWhale-Music/kwhale-server):
manage the music collection, **edit the server code** and **build connectors** for any service.
Inside: standalone playlist parsers (Yandex Music, SoundCloud, YouTube Music, VK,
text/CSV/M3U lists, `yt-dlp` fallback), a parallel-matching importer, a full **MCP server**
and a **portable skill pack** that works with any agent — with or without MCP.

## Features

- **Library management** — search, playlists, likes, downloads, uploads, mixes and share
  links through MCP or the plain `/v1` HTTP API.
- **Standalone playlist parsers** — no server dependency; public Yandex Music playlists
  (redirects and >150-track hydration), SoundCloud `api-v2` (client_id scraping and
  `on.soundcloud.com` redirects), YouTube Music InnerTube, VK `audio.get`, plain
  `Artist - Title` lists, Exportify/Spotify CSV, M3U/M3U8 and a universal `yt-dlp`
  fallback with optional proxy.
- **Smart importer** — parallel track matching (ISRC + duration + text fallback) into a
  new or existing playlist, with `dry_run`.
- **Code editing** — the `kwhale-codebase` skill gives the LLM a map of the server, the
  Android client and the agent layer, plus build/test commands and invariants. The agent
  can change code, not just manage the library.
- **Connector building** — the `kwhale-connectors` skill is a complete guide to the
  contract, registration, streaming, secrets and tests. It is enough to write a connector
  for any service from scratch.
- **MCP server** (`python -m kwhale_agent.mcp_server`) — ~30 tools: auth, playlist CRUD,
  catalogue search, likes, downloads, uploads, mixes, share links.
- **Portable skill pack** — `kwhale-api` (raw `/v1` protocol, works without MCP),
  `kwhale-ops` (operational scenarios), `kwhale-codebase`, `kwhale-connectors`,
  `kwhale-proxy` (sing-box / source proxying).
- **Isolated test bench** — the whole suite runs without network and without a database.

## Screenshots

<img src="docs/images/screens-terminal.png" alt="Terminal / MCP session" width="100%"/>

## Quick start

```bash
git clone https://github.com/KWhale-Music/kwhale-agent.git
cd kwhale-agent
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,fallback]"   # httpx[socks], fastmcp, pytest, yt-dlp

.venv/bin/python -m pytest tests -v          # offline tests
.venv/bin/python -m kwhale_agent.mcp_server  # start MCP (stdio)
```

Connecting an agent: copy or link `skills/*` into your agent's skills directory
(for example `.opencode/skills/`) and register the MCP server in its config.
For an external agent **without MCP**, the `skills/kwhale-api/SKILL.md` skill is enough —
the agent will ask the user for the instance URL and credentials.

## Configuration

| Variable | Purpose |
|---|---|
| `KWHALE_BASE_URL` | instance API URL with `/v1` (for example `http://127.0.0.1:19001/v1`) |
| `KWHALE_EMAIL` / `KWHALE_PASSWORD` | credentials (login by **email**) |
| `KWHALE_DOWNLOAD_DIR` | directory for `download_track(mode="file")` (default `./downloads`) |
| `KWHALE_AGENT_VK_TOKEN` | VK token for `VkPlaylistParser` |
| `HTTPS_PROXY` / `YTDLP_PROXY` | proxy for parsers and the `yt-dlp` fallback (`kwhale-proxy` skill) |

If the env is empty, the agent should ask the user and call the MCP `login(email, password, base_url)`.

## MCP tools

- **Auth and info:** `login`, `logout`, `kwhale_status`
- **Playlist parsing and import:** `list_supported_platforms`, `detect_playlist_platform`,
  `parse_playlist`, `parse_track_list`, `import_playlist_to_profile` (`dry_run`)
- **Playlist CRUD:** `list_playlists`, `get_playlist` (full pagination >200 tracks),
  `create_playlist`, `update_playlist`, `delete_playlist`, `add_tracks_to_playlist`,
  `remove_track_from_playlist`, `reorder_playlist_tracks`, `like_playlist_tracks`
- **Catalogue and downloads:** `search_tracks` (`wait=true`), `get_track_details`, `like_track`,
  `download_track`, `download_status`, `upload_track`, `manage_enrichments`, `list_library`
- **Mixes and sharing:** `list_mixes`, `get_mix_tracks`, `prompt_mix`, `create_share_link`

## Structure

```text
kwhale_agent/
├── playlists/           # standalone parsers (yandex, soundcloud, ytm, vk, textlist, ytdlp fallback)
├── bridge.py            # async HTTP bridge to the /v1 API
├── importer.py          # parallel matching (ISRC + duration + fallback)
└── mcp_server.py        # stdio MCP server
skills/                  # portable skill pack for any LLM agent
tests/                   # isolated test bench with no network and no database
```

## Status

Beta.

## License

[AGPL-3.0](LICENSE) — same terms as the server.

Fonts (when shipped with the repository) are excluded and remain under their own
licenses; they are not covered by the AGPL.

## Third-party services

The parsers work with third-party services through their existing web APIs. Use them in
accordance with those services' terms; the authors take no responsibility for misuse.
