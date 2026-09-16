from pathlib import Path
from random import randint

import httpx
from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential

from src.logger import get_logger
from src.paths import project_path

logger = get_logger(__name__)


FRAMES_DIR = project_path("frames")
TEMP_DIR = project_path("temp")


def _timestamp_to_frame(timestamp: str, fps: int | float = 3.5) -> int | None:
    """
    Converts a timestamp (H:MM:SS.CC) from .ass subtitle format to a frame number.
    Example: "0:01:02.50" → 1 minute, 2.5 seconds → calculated frame.

    Args:
        timestamp (str): Example: "0:01:02.50"
        fps (int, float): Frames per second. Example: 2

    Returns:
        int: Rounded frame number. Or None if error occurs.
    """
    try:
        hours, minutes, seconds = timestamp.split(":")
        seconds, centiseconds = seconds.split(".")
        total_seconds = (
            int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centiseconds) / 100
        )
        return round(total_seconds * fps)
    except (ValueError, AttributeError) as error:
        logger.error("Invalid timestamp %r (expected H:MM:SS.CC): %s", timestamp, error)
        return None


def timestamp_to_seconds(time_str: str, fmt: str = "ass") -> float | None:
    """
    Converts a timestamp (H:MM:SS.CC) to total seconds (float).
    Example: "0:01:02.50" → 1 minute, 2.5 seconds → 62.5 seconds.

    Args:
        time_str (str): Example: "0:01:02.50"

    Returns:
        float: Total seconds. Or None if error occurs.
    """
    if fmt == "ass":
        try:
            h, m, s = time_str.split(":")
            s, cc = s.split(".")
            cc = cc.ljust(2, "0")  # ensure two digits
            total_seconds = int(h) * 3600 + int(m) * 60 + int(s) + int(cc) / 100
            return total_seconds
        except (ValueError, AttributeError) as error:
            logger.error("Invalid ASS timestamp %r: %s", time_str, error)
            return None

    elif fmt == "srt":
        try:
            hours, minutes, rest = time_str.split(":")
            seconds, cc = rest.split(",")
            total_seconds = int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(cc) / 1000.0
            return total_seconds
        except (ValueError, AttributeError) as error:
            logger.error("Invalid SRT timestamp %r: %s", time_str, error)
            return None

    else:
        # Not an exception, just a programming error, so skip exc_info.
        logger.error("Unsupported subtitle format %r (expected 'ass' or 'srt')", fmt)
        return None


def frame_to_timestamp(current_frame: int, img_fps: int | float) -> str | None:
    """Converts frame number to timestamp in .ass format (H:MM:SS.CC).

    Args:
        current_frame (int): Current frame number.
        img_fps (int | float): Frames per second of the video.

    Returns:
        str | None: Timestamp in the format 'H:MM:SS.CC', or None if error occurs.
    """

    if not isinstance(img_fps, (int, float)) or img_fps <= 0:
        logger.error(
            "Invalid img_fps %r for frame_to_timestamp: must be positive int or float",
            img_fps,
        )
        return None

    try:
        total_seconds = current_frame / img_fps

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        centiseconds = int(round((seconds % 1) * 100))
        seconds = int(seconds)

        # Rounding that can generate carry-over (ex: 59.999s -> 1:00.00)
        if centiseconds == 100:
            centiseconds = 0
            seconds += 1
            if seconds == 60:
                seconds = 0
                minutes += 1
                if minutes == 60:
                    minutes = 0
                    hours += 1
        return f"{int(hours)}:{int(minutes):02}:{int(seconds):02}.{centiseconds:02}"

    except (TypeError, ZeroDivisionError) as error:
        logger.error(
            "Failed to convert frame %r at fps=%r to timestamp: %s",
            current_frame,
            img_fps,
            error,
        )
        return None


def random_crop(frame_path: Path, random_crop: dict) -> tuple[Path, str] | None:
    """
    Returns a random crop of the frame.

    Args:
        frame_path: Path to the frame image.
        min_size: Minimum size of the random crop.
        max_size: Maximum size of the random crop.

    Returns:
        tuple[Path, str]: Tuple containing the path to the cropped image and the crop coordinates.
    """

    if not frame_path.is_file():
        logger.error("random_crop: file not found at %s", frame_path)
        return None

    try:
        # Primary keys are ``min_size``/``max_size`` (the square crop size in
        # pixels). The legacy ``random_crop_min_size``/``random_crop_max_size``
        # names are still read as a fallback so older configs keep working.
        min_size = int(random_crop.get("min_size", random_crop.get("random_crop_min_size", 200)))
        max_size = int(random_crop.get("max_size", random_crop.get("random_crop_max_size", 600)))

        if min_size <= 0 or max_size <= 0:
            logger.error(
                "random_crop: crop sizes must be positive, got min=%s max=%s",
                min_size,
                max_size,
            )
            return None

        if min_size > max_size:
            logger.error(
                "random_crop: min_size (%s) cannot be greater than max_size (%s)",
                min_size,
                max_size,
            )
            return None

        crop_width = crop_height = randint(min_size, max_size)

        with Image.open(frame_path) as img:
            image_width, image_height = img.size

            if image_width < crop_width or image_height < crop_height:
                logger.error(
                    "Image %s (%dx%d) is smaller than requested crop (%dx%d)",
                    frame_path.name,
                    image_width,
                    image_height,
                    crop_width,
                    crop_height,
                )
                return None

            # Generate random crop coordinates. eg: 0px... 1920px
            cordinate_x = randint(0, image_width - crop_width)
            cordinate_y = randint(0, image_height - crop_height)

            # Crop image
            cropped_img = img.crop(
                (
                    cordinate_x,
                    cordinate_y,
                    cordinate_x + crop_width,
                    cordinate_y + crop_height,
                )
            )

            # Save the cropped image inside the shared temp folder.
            temp_dir = TEMP_DIR
            temp_dir.mkdir(parents=True, exist_ok=True)
            cropped_path = temp_dir / f"{frame_path.stem}_crop{frame_path.suffix}"
            cropped_img.save(cropped_path)
            message = (
                f"Random Crop. width[{crop_width}] height[{crop_height}] ~ "
                f"cordinate_x: {cordinate_x}, cordinate_y: {cordinate_y}"
            )

            return cropped_path, message

    except (OSError, ValueError, Image.DecompressionBombError) as e:
        logger.error(
            "Failed to crop %s: %s: %s",
            frame_path.name,
            type(e).__name__,
            e,
            exc_info=True,
        )
        return None


def _fall_back(url: str) -> str:
    """Generate a fallback URL using images.weserv.nl proxy.

    Args:
        url: The original URL to proxy.

    Returns:
        str: The proxied URL.
    """
    return f"https://images.weserv.nl/?url={url}"


def _build_url(github_repo: str, frame_number: int) -> str:
    """Build the GitHub raw content URL for a frame.

    Args:
        github_repo: GitHub repository in format "username/repo/branch/"
            + folders and subfolders if needed. Trailing slashes are stripped
            to avoid doubled path separators.
        frame_number: Frame number to fetch.

    Returns:
        str: The complete URL to the frame image.
    """
    base = github_repo.strip("/")
    return f"https://raw.githubusercontent.com/{base}/{frame_number:04d}.jpg"


def _output_path(season_number: int, episode_number: int, frame_number: int) -> Path:
    """Generate the local output path for a frame.

    Args:
        season_number: Season number.
        episode_number: Episode number.
        frame_number: Frame number.

    Returns:
        Path: The local path where the frame will be saved.
    """
    output_path = (
        FRAMES_DIR / f"S-{season_number}" / f"E-{episode_number}" / f"{frame_number:04d}.jpg"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def _log_download_failure(retry_state) -> None:
    """Log the final failure of a frame download after all retries."""
    outcome = retry_state.outcome
    logger.error(
        "Failed to download frame after %d attempts: %s",
        retry_state.attempt_number,
        outcome.exception() if outcome is not None else "unknown error",
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    before_sleep=lambda retry_state: (
        logger.warning("Download attempt %d failed, retrying...", retry_state.attempt_number)
        if retry_state.attempt_number < 3
        else None
    ),
    retry_error_callback=_log_download_failure,
)
def _download_frame(url: str, output_path: Path) -> None:
    """Download a frame from URL and save it to the output path.

    Uses retry logic with exponential backoff. Falls back to images.weserv.nl
    proxy if rate limited (429 status code).

    Args:
        url: The URL to download the frame from.
        output_path: The local path to save the downloaded frame.

    Raises:
        httpx.HTTPStatusError: If the download fails after retries.
    """
    try:
        response = httpx.get(url, follow_redirects=True, timeout=30)
        if response.status_code == 429:
            response = httpx.get(_fall_back(url), follow_redirects=True, timeout=30)

        response.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(response.content)

    except httpx.HTTPStatusError:
        raise


def get_frame(
    season_number: int, episode_number: int, frame_number: int, github_repo: str
) -> Path | None:
    """Download a frame from GitHub and save it locally.

    Returns Path if successful, None if failed.
    """
    if frame_number < 0:
        logger.error("Invalid frame_number: %d (must be >= 0)", frame_number)
        return None

    if not github_repo:
        logger.error("Empty github_repo provided")
        return None

    url = _build_url(github_repo, frame_number)
    output_path = _output_path(season_number, episode_number, frame_number)

    if output_path.exists():
        logger.info("Frame already exists: %s", output_path)
        return output_path

    try:
        logger.info("Downloading frame %d from %s", frame_number, url)
        _download_frame(url, output_path)

        if not output_path.exists():
            logger.error("Download failed: file not created at %s", output_path)
            return None

        return output_path

    except Exception as e:
        logger.error("Failed to get frame %d: %s", frame_number, e)
        return None
