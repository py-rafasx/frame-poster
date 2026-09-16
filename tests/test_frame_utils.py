from src.frame_utils import (
    _build_url,
    frame_to_timestamp,
    timestamp_to_seconds,
)


def test_timestamp_to_seconds_ass():
    assert timestamp_to_seconds("0:01:02.50") == 62.5


def test_timestamp_to_seconds_srt():
    assert timestamp_to_seconds("00:00:01,500", fmt="srt") == 1.5


def test_timestamp_to_seconds_invalid():
    assert timestamp_to_seconds("not-a-time") is None


def test_frame_to_timestamp():
    assert frame_to_timestamp(7, 3.5) == "0:00:02.00"


def test_frame_to_timestamp_invalid_fps():
    assert frame_to_timestamp(10, 0) is None


def test_build_url_zero_pads_frame():
    url = _build_url("py-rafasx/season2/master/01/", 5)
    assert url == "https://raw.githubusercontent.com/py-rafasx/season2/master/01/0005.jpg"
