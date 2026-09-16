import re
from functools import lru_cache
from pathlib import Path

from langdetect import detect

from src.frame_utils import timestamp_to_seconds
from src.logger import get_logger
from src.paths import project_path

logger = get_logger(__name__)

SUBTITLES_DIR = project_path("subtitles")

LANGUAGE_CODES = {
    "en": "English",
    "pt": "Português",
    "es": "Español",
    "spa": "Español",
    "ja": "日本語",
    "ko": "한국어",
    "zh-cn": "简体中文",
    "zh-tw": "繁體中文",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "ru": "Русский",
    "tr": "Türkçe",
    "vi": "Tiếng Việt",
    "nl": "Nederlands",
    "uk": "Українська",
    "id": "Bahasa Indonesia",
    "tl": "Tagalog",
    # add more language codes here
}


@lru_cache(maxsize=32)
def _extract_raw_text(file_path: Path) -> str | None:
    """
    Extracts raw text lines from a subtitle file (.ass or .srt).

    Args:
        file_path (Path): Path to the subtitle file.

    Returns:
        str | None: The raw text content of the file, or None on error.
    """

    if not file_path.exists() or not file_path.is_file():
        logger.warning("Subtitle file %s does not exist or is not a file", file_path)
        return None

    try:
        with file_path.open("r", encoding="utf-8") as f:
            raw_text = "".join(line for line in f)

    except (FileNotFoundError, PermissionError) as e:
        logger.error("Error occurred while reading subtitle file %s: %s", file_path, e)
        return None

    return raw_text


@lru_cache(maxsize=32)
def _remove_tags(raw_text: str) -> str:
    """Remove ASS/SSA styling tags and simple HTML tags from a subtitle string."""
    if not raw_text:
        return raw_text

    pattern = re.compile(r"\{\s*[^}]*\s*\}|<[^>]+>|\\N|\\[a-zA-Z]+\d*|\\c&H[0-9A-Fa-f]+&")
    cleaned_text = pattern.sub(" ", raw_text)

    return re.sub(r"[^\S\n]+", " ", cleaned_text).strip()


@lru_cache(maxsize=32)
def _get_lang(cleaned_text: str) -> str:
    """
    Detects the language of the cleaned subtitle text and returns the
    human-readable language name (e.g. "English", "Português", "Spanish" ...).
    """
    try:
        lang = detect(cleaned_text)
    except Exception:
        logger.error("Failed to detect language for cleaned text.")
        lang = "Unknown"

    return LANGUAGE_CODES.get(lang, lang)


@lru_cache(maxsize=32)
def _parse_ass(cleaned_text: str) -> list[dict]:
    """Parse the cleaned ASS text into a list of dialogue dictionaries."""
    dialogues_data: list[dict] = []

    for line in cleaned_text.split("\n"):
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            line_data = {
                "Layer": parts[0],
                "Start": timestamp_to_seconds(parts[1]),
                "End": timestamp_to_seconds(parts[2]),
                "Style": parts[3],
                "Actor": parts[4],
                "MarginL": parts[5],
                "MarginR": parts[6],
                "MarginV": parts[7],
                "Effect": parts[8],
                "Text": parts[9],
            }

            dialogues_data.append(line_data)

    return dialogues_data


@lru_cache(maxsize=32)
def _parse_srt(cleaned_text: str) -> list[dict]:
    """Parse the cleaned SRT text into a list of dialogue dictionaries."""
    dialogues_data: list[dict] = []

    for block in re.split(r"\n\s*\n", cleaned_text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        time_line = next((line for line in lines if "-->" in line), None)
        if not time_line:
            continue

        start_text, end_text = [part.strip() for part in time_line.split("-->", 1)]
        start = timestamp_to_seconds(start_text, fmt="srt")
        end = timestamp_to_seconds(end_text, fmt="srt")

        if start is None or end is None:
            continue

        text_lines = [line for line in lines if line != time_line and not line.isdigit()]
        text = " ".join(text_lines)

        dialogues_data.append({"Start": start, "End": end, "Text": text})

    return dialogues_data


def _ass_format(sub: dict) -> str:
    """Format a subtitle entry adding decoration for signs and music."""
    sign_expression = re.compile(r"sign|signs", re.IGNORECASE)
    music_expression = re.compile(
        r"\blyric(s)?\b|\bsong(s)?\b|\bopening\b|\bending\b|\bop\b|\bed\b",
        re.IGNORECASE,
    )

    style = sub.get("Style", "")
    actor = sub.get("Actor", "")
    text = sub.get("Text", "")

    if sign_expression.search(style) or sign_expression.search(actor):
        return f"【 {text} 】"
    if music_expression.search(style) or music_expression.search(actor):
        return f"♪ {text} ♪\n"

    return text


def _srt_format(sub: dict) -> str:
    """Format a subtitle entry for SRT output."""
    return sub.get("Text", "")


def _find_subtext(frame_number: int, img_fps: float, dialogues_data: list[dict]) -> dict | None:
    """Return the active subtitle entry from a list of dialogues."""
    current_time = round(frame_number / img_fps, 2)

    for sub in dialogues_data:
        if sub["Start"] <= current_time <= sub["End"]:
            return sub

    return None


def get_subtitle(
    season: int | str, episode: int | str, frame_number: int, img_fps: float | None
) -> list[dict[str, str]] | None:
    """Return the subtitle language and text for the requested frame.

    Returns a list of dicts with "lang" and "text" for each subtitle file
    that has an active subtitle at the given frame time.
    """
    folder = SUBTITLES_DIR / f"{season}" / f"{episode}"
    if not folder.exists() or not folder.is_dir():
        logger.warning("Subtitle folder %s does not exist or is not a directory", folder)
        return None

    if img_fps is None or img_fps == "":
        return None

    if img_fps <= 0:
        logger.error("img_fps is set, but is not a valid value")
        return None

    files = [f for f in folder.iterdir() if f.is_file()]

    if not files:
        logger.warning("No subtitle files found in %s", folder)
        return None

    subtitle_results = []

    for file in files:
        match file.suffix:
            case ".ass":
                raw_text = _extract_raw_text(file)
                cleaned_text = _remove_tags(raw_text)
                lang = _get_lang(cleaned_text)
                dialogues_data = _parse_ass(cleaned_text)
                sub = _find_subtext(frame_number, img_fps, dialogues_data)

                if sub:
                    text = _ass_format(sub)
                    subtitle_results.append({"lang": lang, "text": text})

            case ".srt":
                raw_text = _extract_raw_text(file)
                cleaned_text = _remove_tags(raw_text)
                lang = _get_lang(cleaned_text)
                dialogues_data = _parse_srt(cleaned_text)
                sub = _find_subtext(frame_number, img_fps, dialogues_data)

                if sub:
                    text = _srt_format(sub)
                    subtitle_results.append({"lang": lang, "text": text})

            case _:
                logger.warning("Unsupported subtitle file format: %s", file.suffix)
                continue

    return subtitle_results
