from src.message import format_message


def test_format_message_basic():
    assert format_message("Frame {frame_number}", {"frame_number": 5}) == "Frame 5"


def test_missing_placeholder_is_preserved():
    assert format_message("Frame {unknown}", {}) == "Frame {unknown}"


def test_newline_alias():
    assert format_message("a{br}b", {}) == "a\nb"


def test_newline_long_alias():
    assert format_message("a{newline}b", {}) == "a\nb"


def test_none_message_returns_empty():
    assert format_message(None, {}) == ""
