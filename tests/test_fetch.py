from fetch import channel_videos_url, error_line

COOKIES = "hint: rerun with --cookies-from-browser"
UPDATE = "hint: YouTube changed something; run: yt-dlp -U"


def test_doubled_prefix_stripped_last_line():
    out = error_line("noise\nERROR: [youtube] x: unavailable")
    assert out == "[youtube] x: unavailable"


def test_single_prefix_stripped():
    assert error_line("ERROR: boom") == "boom"
    assert error_line("error:   boom\n\n") == "boom"


def test_cookies_hint():
    out = error_line("Sign in to confirm your age")
    assert COOKIES in out and "\n" not in out


def test_update_hint():
    assert UPDATE in error_line("Unable to extract uploader id")


def test_no_cookies_hint_on_message():
    assert error_line("bad message here") == "bad message here"


def test_extraction_wins_over_cookies():
    out = error_line("Unable to extract player; sign in required")
    assert UPDATE in out and COOKIES not in out


def test_channel_urls():
    assert channel_videos_url("https://www.youtube.com/@foo") == "https://www.youtube.com/@foo/videos"
    assert channel_videos_url("https://www.youtube.com/@foo/") == "https://www.youtube.com/@foo/videos"
    assert channel_videos_url("https://www.youtube.com/@foo/videos") == "https://www.youtube.com/@foo/videos"
    assert channel_videos_url("https://www.youtube.com/@foo/streams") == "https://www.youtube.com/@foo/streams"
    u = "https://www.youtube.com/playlist?list=PL123"
    assert channel_videos_url(u) == u
