"""
Random post mode: posts random frames from any configured episode.

Ported from py-rafasx/rand-frame and adapted to the frame-poster architecture.
Each execution posts ``posting.fph`` frames, optionally applying weighted
image filters (see the "filters" section in config.yml), avoiding repeated
frames through FrameHistory persistence between runs.

Random frames are never reposted to an album - album repost is a
sequential-mode feature only.
"""

from random import choice
from time import sleep

from ruamel.yaml import CommentedMap

from src.console import print_random_header, print_random_status
from src.facebook import FacebookGraphAPI
from src.filters import apply_filter, select_filter
from src.frame_history import FrameHistory
from src.frame_utils import frame_to_timestamp, get_frame
from src.github_tree import list_frames
from src.logger import get_logger
from src.message import format_message
from src.poster import create_post, make_post_public, post_comment, post_random_crop
from src.subtitles import get_subtitle
from src.workflow import get_workflow_interval_hours

logger = get_logger(__name__)

# Short delay after a failed iteration so a broken run does not spin
RETRY_DELAY_SECONDS = 10


def _iter_episodes(config: CommentedMap):
    """Yield (season, episode_data) pairs from all configured seasons."""
    for season_data in config.get("seasons", []):
        season = season_data.get("season")
        for episode_data in season_data.get("episodes", []):
            yield season, episode_data


def _pick_random_frame(
    config: CommentedMap,
    history: FrameHistory,
    pending: set | None = None,
):
    """
    Pick a random (season, episode_data, frame_number) avoiding frames
    already posted in previous executions.

    ``pending`` holds (episode, frame_number) pairs picked earlier in the
    current cycle that have not been confirmed yet, preventing the two
    panels of one post from being the same frame.

    When every frame of the configured episodes has already been used,
    the history is cleared and a new posting cycle begins.

    Returns None only when no candidate episodes exist in the config.
    """
    pending = pending or set()

    candidates = [
        (season, episode_data)
        for season, episode_data in _iter_episodes(config)
        if episode_data.get("max_frames", 0) > 0
    ]
    if not candidates:
        logger.error("No episodes with max_frames > 0 found in config")
        return None

    pool = []
    for season, episode_data in candidates:
        real_frames = list_frames(episode_data.get("github_repo", ""))
        if real_frames:
            for frame_number in real_frames:
                pool.append((season, episode_data, frame_number))
        else:
            for frame_number in range(1, episode_data["max_frames"] + 1):
                pool.append((season, episode_data, frame_number))

    available = [
        entry
        for entry in pool
        if not history.is_frame_used(entry[1].get("episode"), entry[2])
        and (entry[1].get("episode"), entry[2]) not in pending
    ]

    if not available:
        logger.info(
            "All %d frames have already been posted, starting a new cycle",
            len(pool),
        )
        history.clear_history()
        available = pool

    season, episode_data, frame_number = choice(available)

    return season, episode_data, frame_number


def _build_frame_data(filter_name: str, picked) -> dict | None:
    """Download a picked frame and collect its subtitle/timestamp metadata."""
    season, episode_data, frame_number = picked
    episode = episode_data.get("episode")

    frame_path = get_frame(season, episode, frame_number, episode_data.get("github_repo", ""))
    if not frame_path:
        logger.error(
            "Failed to download frame %d from episode %s (github_repo: %s)",
            frame_number,
            episode,
            episode_data.get("github_repo", ""),
        )
        return None

    img_fps = episode_data.get("img_fps")

    return {
        "season": season,
        "episode": episode,
        "frame_number": frame_number,
        "frame_path": frame_path,
        "output_path": None,
        "timestamp": frame_to_timestamp(frame_number, img_fps) or "",
        "subtitles": get_subtitle(season, episode, frame_number, img_fps) or [],
        "max_frames": episode_data.get("max_frames", 0),
        "img_fps": img_fps,
        "title": episode_data.get("title", ""),
        "filter_func": filter_name,
    }


def _tagged_subtitles(frame_data: dict) -> list[dict[str, str]]:
    """Tag each subtitle language with its episode (used for two-panel posts)."""
    return [
        {
            "lang": f"{sub.get('lang', 'Unknown')} (E{frame_data['episode']})",
            "text": sub.get("text", ""),
        }
        for sub in frame_data["subtitles"]
    ]


def _format_random_message(
    single_msg: str | None,
    two_panels_msg: str | None,
    static_placeholders: dict,
    framedata: list[dict],
) -> str | None:
    """Format the message for one frame or a two-panel pair.

    Single frames use TEMPLATE_RANDOM_FRAME_MSG; two_panels posts use
    TEMPLATE_RANDOM_TWO_PANELS_MSG (falling back to the single-frame
    template when it is not configured).
    """
    first = framedata[0]
    is_two_panels = len(framedata) == 2

    if is_two_panels:
        template_msg = two_panels_msg
        if not template_msg:
            logger.warning(
                "TEMPLATE_RANDOM_TWO_PANELS_MSG not set, falling back to TEMPLATE_RANDOM_FRAME_MSG"
            )
            template_msg = single_msg
    else:
        template_msg = single_msg

    placeholders = {
        **static_placeholders,
        # single-frame placeholders (first frame when using two panels)
        "season": first["season"],
        "episode": first["episode"],
        "episode_title": first["title"],
        "frame_number": first["frame_number"],
        "timestamp": first["timestamp"],
        "subtitles": first["subtitles"],
        "max_frames": first["max_frames"],
        "img_fps": first["img_fps"],
        "filter_func": first["filter_func"],
    }

    if is_two_panels:
        second = framedata[1]
        placeholders.update(
            {
                "episode1": first["episode"],
                "episode2": second["episode"],
                "frame1": first["frame_number"],
                "frame2": second["frame_number"],
                "timestamp1": first["timestamp"],
                "timestamp2": second["timestamp"],
            }
        )

    message = format_message(template_msg, placeholders)
    if not message or not message.strip():
        logger.error("Random frame message formatted empty")
        return None

    return message


def _post_random_frame(
    facebook_client: FacebookGraphAPI,
    single_msg: str | None,
    two_panels_msg: str | None,
    static_placeholders: dict,
    framedata: list[dict],
    *,
    sub_comment_enabled: bool,
    random_crop_config: dict,
) -> bool:
    """Upload and publish a random frame post (single or two panels)."""
    message = _format_random_message(single_msg, two_panels_msg, static_placeholders, framedata)
    if not message:
        return False

    first = framedata[0]
    is_two_panels = len(framedata) == 2

    result = create_post(
        facebook_client, first["output_path"], message, first["episode"], first["frame_number"]
    )
    if not result:
        return False

    post_id, _photo_id = result

    # random crop as comment (crop taken from the original frame image)
    crop_ok = post_random_crop(facebook_client, post_id, first["frame_path"], random_crop_config)

    # subtitles as comments
    subs_first = _tagged_subtitles(first) if is_two_panels else first["subtitles"]
    post_comment(facebook_client, post_id, subs_first, sub_comment_enabled)
    if is_two_panels:
        post_comment(facebook_client, post_id, _tagged_subtitles(framedata[1]), sub_comment_enabled)

    # publish the draft post
    make_post_public(facebook_client, post_id)

    has_subtitles = any(frame["subtitles"] for frame in framedata)
    print_random_status(
        season=first["season"],
        frames=[(frame["episode"], frame["frame_number"]) for frame in framedata],
        filter_name=first["filter_func"],
        has_subtitles=has_subtitles,
        crop_ok=crop_ok,
    )
    return True


def random_post(facebook_client: FacebookGraphAPI, config: CommentedMap) -> None:
    """Post random frames following the same cadence as sequential mode."""
    posting = config.get("posting", {})
    fph = posting.get("fph", 15)
    posting_interval = posting.get("post_interval", 2)
    sub_comment_enabled = posting.get("sub_comment", False)

    template_msg = config.get("TEMPLATE_RANDOM_FRAME_MSG")
    if not template_msg:
        logger.error("TEMPLATE_RANDOM_FRAME_MSG is missing from config.yml")
        return

    # dedicated template for two_panels posts (falls back to the single one)
    two_panels_msg = config.get("TEMPLATE_RANDOM_TWO_PANELS_MSG")

    random_crop_config = config.get("random_crop", {})
    history = FrameHistory()

    static_placeholders = {
        "fph": fph,
        "post_interval": posting_interval,
        "execution_interval": get_workflow_interval_hours(),
    }

    print_random_header(config.get("filters", {}))

    for _ in range(fph):
        pending_frames: set = set()
        try:
            filter_func = select_filter(config)

            if filter_func.__name__ == "two_panels":
                framedata: list[dict] = []
                for _ in range(2):
                    picked = _pick_random_frame(config, history, pending_frames)
                    if not picked:
                        break
                    pending_frames.add((picked[1].get("episode"), picked[2]))
                    data = _build_frame_data(filter_func.__name__, picked)
                    if not data:
                        break
                    framedata.append(data)

                if len(framedata) != 2:
                    logger.error("Failed to prepare both frames for two_panels")
                    sleep(RETRY_DELAY_SECONDS)
                    continue
            else:
                picked = _pick_random_frame(config, history, pending_frames)
                if not picked:
                    sleep(RETRY_DELAY_SECONDS)
                    continue

                pending_frames.add((picked[1].get("episode"), picked[2]))
                data = _build_frame_data(filter_func.__name__, picked)
                if not data:
                    sleep(RETRY_DELAY_SECONDS)
                    continue

                framedata = [data]

            output_path = apply_filter(filter_func, framedata)
            if not output_path:
                logger.error(
                    "Failed to generate filtered image with %s",
                    filter_func.__name__,
                )
                sleep(RETRY_DELAY_SECONDS)
                continue

            framedata[0]["output_path"] = output_path

            posted = _post_random_frame(
                facebook_client,
                template_msg,
                two_panels_msg,
                static_placeholders,
                framedata,
                sub_comment_enabled=sub_comment_enabled,
                random_crop_config=random_crop_config,
            )

        except Exception as e:
            logger.error("Unexpected error processing random frame: %s", e, exc_info=True)
            posted = False

        if posted:
            for data in framedata:
                history.add_frame(data["episode"], data["frame_number"])
            sleep(posting_interval * 60)
        else:
            sleep(RETRY_DELAY_SECONDS)
