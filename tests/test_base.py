"""Test stand: parser normalisation + URL detection (no network, no DB)."""

from kwhale_agent.playlists import detect_platform, get_parser
from kwhale_agent.playlists.base import ParsedPlaylist, PlaylistParser, TrackRef, seconds_from_ms


def test_split_artists():
    split = PlaylistParser.split_artists
    assert split("A feat. B") == ["A", "B"]
    assert split("A, B & C") == ["A", "B", "C"]
    assert split("A vs B") == ["A", "B"]
    assert split("Solo") == ["Solo"]
    assert split("") == []


def test_artist_title_from_label():
    f = PlaylistParser.artist_title_from_label
    artists, title = f("Artist - Title")
    assert artists == ["Artist"] and title == "Title"
    artists, title = f("Just A Title", uploader="Uploader")
    assert artists == ["Uploader"] and title == "Just A Title"


def test_clean_title():
    assert PlaylistParser.clean_title("  Song   Name - Topic ") == "Song Name"


def test_strip_match_noise():
    s = PlaylistParser.strip_match_noise("Track Name (2021 Remaster) [Explicit] (feat. Guest)")
    assert s == "Track Name"
    assert PlaylistParser.strip_match_noise("Song ft. Someone") == "Song"


def test_seconds_from_ms():
    assert seconds_from_ms(215000) == 215
    assert seconds_from_ms(None) == 0


def test_track_ref_match_key():
    t = TrackRef(title="Song", artists=["A", "B"])
    assert t.match_key == "a, b - song"


def test_parsed_playlist_dict():
    pl = ParsedPlaylist(platform="yandex", ref="u/1", title="T", tracks=[TrackRef(title="x", artists=["y"])])
    d = pl.to_dict()
    assert d["trackCount"] == 1 and d["platform"] == "yandex"
    assert d["tracks"][0]["title"] == "x"


def test_detect_platform():
    assert detect_platform("https://music.yandex.ru/playlist/user-42") == "yandex"
    assert detect_platform("https://music.yandex.ru/users/user/playlists/42") == "yandex"
    assert detect_platform("https://music.yandex.ru/playlists/lk.12345") == "yandex"
    assert detect_platform("https://soundcloud.com/artist/sets/my-set") == "soundcloud"
    assert detect_platform("https://on.soundcloud.com/abc123") == "soundcloud"
    assert detect_platform("https://music.youtube.com/playlist?list=PLabc1234567890") == "ytm"
    assert detect_platform("https://vk.com/music/album/123_456") == "vk"
    assert detect_platform("Artist A - Song 1\nArtist B - Song 2") == "text"
    assert detect_platform("#EXTM3U\n#EXTINF:200,Artist - Song\nsong.mp3") == "text"
    assert detect_platform("https://example.com/some/other/url") == "ytdlp"


def test_aliases_resolve():
    assert get_parser("яндекс").platform == "yandex"
    assert get_parser("sc").platform == "soundcloud"
    assert get_parser("ютуб-музыка").platform == "ytm"
    assert get_parser("вк").platform == "vk"
    assert get_parser("csv").platform == "text"
    assert get_parser("m3u8").platform == "text"


def test_yandex_ref_parse():
    p = get_parser("yandex")
    assert p._parse_ref("https://music.yandex.ru/playlist/alice-100500") == ("alice", "100500")
    assert p._parse_ref("https://music.yandex.ru/users/bob.playlists".replace(".playlists", "/playlists") + "/7") == ("bob", "7")
    assert p._parse_ref("uid/123") == ("uid", "123")
