#!/usr/bin/env python3
"""Live smoke of the playlist parsers — READ-ONLY against the platforms.

Usage:
    python scripts/smoke_playlists.py [--platform yandex] <playlist-url> [...]
    python scripts/smoke_playlists.py --selftest   # built-in sample URLs

Prints a per-platform report: parsed title, track count, first tracks, errors.
Never writes anywhere — the test stand for parsers before any integration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

sys.path.insert(0, ".")

from kwhale_agent.playlists import ParseError, detect_platform, fetch_playlist, list_platforms  # noqa: E402

SELFTEST = [
    "https://music.yandex.ru/users/yandex-music/playlists/1",  # public curated
    "https://soundcloud.com/search/sounds?q=test",  # expected to FAIL (not a set) — error path
]


async def _one(platform: str, ref: str, show: int) -> dict:
    detected = detect_platform(ref)
    out: dict = {"ref": ref, "platform": platform or detected}
    try:
        parsed = await fetch_playlist(platform, ref)
    except ParseError as e:
        out["error"] = str(e)
        return out
    out.update(
        {
            "title": parsed.title,
            "owner": parsed.owner,
            "trackCount": parsed.track_count,
            "truncated": parsed.truncated,
            "firstTracks": [
                f"{t.artist_str} - {t.title} [{t.duration_sec}s]" for t in parsed.tracks[:show]
            ],
        }
    )
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("refs", nargs="*", help="playlist URLs (or ids with --platform)")
    ap.add_argument("--platform", default="", help="force platform (default: auto-detect)")
    ap.add_argument("--show", type=int, default=5, help="tracks to print per playlist")
    ap.add_argument("--selftest", action="store_true", help="run built-in sample URLs")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    refs = list(args.refs)
    if args.selftest:
        refs += SELFTEST
    if not refs:
        ap.print_help()
        print("\nSupported platforms:", json.dumps(list_platforms(), ensure_ascii=False))
        return 2

    reports = []
    for ref in refs:
        reports.append(await _one(args.platform, ref, args.show))

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            if "error" in r:
                print(f"FAIL  [{r['platform']}] {r['ref']}\n      {r['error']}")
            else:
                print(f"OK    [{r['platform']}] {r['title']} — {r['trackCount']} tracks"
                      + (" (truncated)" if r["truncated"] else ""))
                for line in r["firstTracks"]:
                    print(f"      {line}")
    return 0 if all("error" not in r for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
