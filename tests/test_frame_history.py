from src.frame_history import FrameHistory


def test_add_and_check(tmp_path):
    history = FrameHistory(str(tmp_path / "hist.json"))
    history.add_frame(1, 10)
    assert history.is_frame_used(1, 10)
    assert history.get_used_frames_count() == 1


def test_persistence_between_instances(tmp_path):
    path = str(tmp_path / "hist.json")
    first = FrameHistory(path)
    first.add_frame("E1", 3)

    second = FrameHistory(path)
    assert second.is_frame_used("E1", 3)


def test_clear_history(tmp_path):
    history = FrameHistory(str(tmp_path / "hist.json"))
    history.add_frame(1, 1)
    history.clear_history()
    assert history.get_used_frames_count() == 0


def test_reset_keeps_triggering_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(FrameHistory, "MAX_FRAMES", 3)
    history = FrameHistory(str(tmp_path / "hist.json"))

    for number in range(1, 4):
        history.add_frame(1, number)

    assert history.get_used_frames_count() == 3
    assert history.is_frame_used(1, 3)

    history.add_frame(1, 4)

    assert history.get_used_frames_count() == 1
    assert history.is_frame_used(1, 4)
    assert not history.is_frame_used(1, 3)
