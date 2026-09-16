"""
Frame history persistence for random posts.

Keeps track of already posted (episode, frame) pairs between executions so
random mode never repeats a frame until the whole pool has been exhausted.
The history is stored as JSON under ``temp/`` and is automatically cleared
when it reaches ``MAX_FRAMES`` entries.
"""

import json

from src.logger import get_logger
from src.paths import project_path

logger = get_logger(__name__)


class FrameHistory:
    """
    Manages the history of used frames, persisting it between executions.

    Automatically clears history when reaching MAX_FRAMES entries.
    """

    MAX_FRAMES = 5000

    def __init__(self, history_file: str = "frame_history.json"):
        self.history_file = project_path("temp") / history_file
        self.used_frames: set[tuple[str | int, int]] = set()

        # Create temp directory if it doesn't exist
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()

    def _load_history(self) -> None:
        """Load the frame history from the JSON file (empty set if missing/corrupt)."""
        if not self.history_file.exists():
            self._save_history()
            return

        try:
            with self.history_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Convert the list of lists back to a set of tuples
            self.used_frames = {(item[0], item[1]) for item in data}
        except (json.JSONDecodeError, TypeError, IndexError):
            logger.warning("Corrupt frame history file %s, starting fresh", self.history_file)
            self.used_frames = set()
            self._save_history()

    def _save_history(self) -> None:
        """Save the current frame history to the JSON file."""
        data = [list(item) for item in self.used_frames]
        try:
            with self.history_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except OSError as e:
            logger.error("Failed to save frame history %s: %s", self.history_file, e)

    def add_frame(self, episode: str | int, frame_number: int) -> None:
        """
        Add a frame to the history and persist it.

        When the history reaches MAX_FRAMES it is cleared automatically,
        allowing all frames to be posted again in a new cycle. The frame that
        triggers the reset becomes the first entry of the new cycle instead of
        being lost.

        Args:
            episode: Episode identifier (number or string).
            frame_number: The frame number.
        """
        if len(self.used_frames) >= self.MAX_FRAMES:
            logger.info(
                "Frame history reached %d entries, clearing for a new cycle",
                self.MAX_FRAMES,
            )
            self.used_frames.clear()

        self.used_frames.add((episode, frame_number))
        self._save_history()

    def is_frame_used(self, episode: str | int, frame_number: int) -> bool:
        """Return True if the given (episode, frame) pair was already posted."""
        return (episode, frame_number) in self.used_frames

    def clear_history(self) -> None:
        """Clear the frame history and persist the empty state."""
        self.used_frames.clear()
        self._save_history()

    def get_used_frames_count(self) -> int:
        """Get the total number of frames that have been used."""
        return len(self.used_frames)
