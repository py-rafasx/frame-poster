from time import sleep
from typing import cast

from ruamel.yaml import CommentedMap

from src.console import print_post_status, print_sequential_header
from src.facebook import FacebookGraphAPI
from src.frame_utils import frame_to_timestamp, get_frame
from src.load_configs import save_configs
from src.logger import get_logger, log_post_id
from src.message import format_message
from src.poster import album_repost, create_post, make_post_public, post_comment, post_random_crop
from src.subtitles import get_subtitle
from src.workflow import get_workflow_interval_hours

logger = get_logger(__name__)


def _save_progress(config: CommentedMap, season, episode, frame):
    """Save current progress to config and persist to disk."""
    config["progress"]["season"] = season
    config["progress"]["episode"] = episode
    config["progress"]["frame"] = frame

    save_configs(config)
    logger.info("Progress saved: S%sE%s frame %d", season, episode, frame)


def _advance_episode(config: CommentedMap, seasons_list: list, current_season, current_episode):
    """Advance progress to the next episode (or next season if last episode)."""
    season_data: CommentedMap = cast(
        CommentedMap, next((s for s in seasons_list if s.get("season") == current_season), {})
    )
    episodes = season_data.get("episodes", [])

    current_idx = next(
        (i for i, ep in enumerate(episodes) if ep.get("episode") == current_episode), None
    )

    if current_idx is not None and current_idx + 1 < len(episodes):
        next_episode = episodes[current_idx + 1].get("episode")
        config["progress"]["episode"] = next_episode
        config["progress"]["frame"] = 0
        save_configs(config)
        logger.info("Advanced to next episode: S%sE%s", current_season, next_episode)
    else:
        season_idx = next(
            (i for i, s in enumerate(seasons_list) if s.get("season") == current_season), None
        )
        if season_idx is not None and season_idx + 1 < len(seasons_list):
            next_season_data = seasons_list[season_idx + 1]
            next_season = next_season_data.get("season")
            first_episode = next_season_data.get("episodes", [{}])[0].get("episode", 1)
            config["progress"]["season"] = next_season
            config["progress"]["episode"] = first_episode
            config["progress"]["frame"] = 0
            save_configs(config)
            logger.info("Advanced to next season: S%sE%s", next_season, first_episode)
        else:
            logger.info(
                "All episodes posted. Progress: S%sE%s frame %d",
                current_season,
                current_episode,
                config["progress"]["frame"],
            )


def _count_episodes(seasons_list: list, current_season: int) -> int:
    """Count total episodes across all seasons up to and including current season."""
    total = 0
    for s in seasons_list:
        total += len(s.get("episodes", []))
        if s.get("season") == current_season:
            break
    return total


def sequential_post(facebook_client: FacebookGraphAPI, config: CommentedMap):
    # --- current progress ---
    progress = config.get("progress", {})
    current_season = progress.get("season", 1)
    current_episode = progress.get("episode", 1)

    # --- season and episode data ---
    seasons_list = config.get("seasons", [])
    season_data: CommentedMap = cast(
        CommentedMap, next((s for s in seasons_list if s.get("season") == current_season), {})
    )
    episode_data: CommentedMap = cast(
        CommentedMap,
        next(
            (ep for ep in season_data.get("episodes", []) if ep.get("episode") == current_episode),
            {},
        ),
    )

    if not episode_data:
        logger.error("Episode %s not found in season %s", current_episode, current_season)
        return

    # --- posting configuration ---
    posting = config.get("posting", {})
    fph = posting.get("fph", 15)
    sub_comment_enabled = posting.get("sub_comment", False)
    album_repost_enabled = posting.get("album_repost", False)
    posting_interval = posting.get("post_interval", 2)
    github_repo = episode_data.get("github_repo", "")
    album_id = episode_data.get("album_id")

    template_msg = config.get("TEMPLATE_POST_MSG")
    template_bio = config.get("TEMPLATE_BIO_MSG")

    # --- limits ---
    current_frame = max(1, progress.get("frame", 0))
    stop_frame = current_frame + fph
    max_frames = episode_data.get("max_frames", 0)
    img_fps = episode_data.get("img_fps")

    # --- random crop ---
    random_crop_config = config.get("random_crop", {})

    # --- episode totals for console display ---
    total_episodes = _count_episodes(seasons_list, current_season)

    # --- static placeholders ---
    static_placeholders = {
        "season": current_season,
        "episode": current_episode,
        "episode_title": episode_data.get("title", ""),
        "max_frames": max_frames,
        "img_fps": img_fps,
        "fph": fph,
        "post_interval": posting.get("post_interval", 2),
        "execution_interval": get_workflow_interval_hours(),
    }

    # --- post loop ---
    print_sequential_header(current_season, current_episode, current_frame, max_frames)

    for frame_number in range(current_frame, stop_frame):
        if frame_number > max_frames:
            _advance_episode(config, seasons_list, current_season, current_episode)
            break

        # download frame
        frame_path = get_frame(current_season, current_episode, frame_number, github_repo)
        if not frame_path:
            logger.error(
                "Failed to get frame %d for episode %d (github_repo: %s)",
                frame_number,
                current_episode,
                github_repo,
            )
            break

        # fetch subtitle for this frame
        subtitle_list = get_subtitle(current_season, current_episode, frame_number, img_fps)
        has_subtitles = bool(subtitle_list)

        # extend static placeholders with dynamic ones
        placeholders = {
            **static_placeholders,
            "frame_number": frame_number,
            "subtitles": subtitle_list,
            "timestamp": frame_to_timestamp(frame_number, img_fps) or "",
        }

        # format the post message
        post_message = format_message(template_msg, placeholders)
        if not post_message:
            logger.error(
                "Template post message is empty: episode %s, frame %s",
                current_episode,
                frame_number,
            )
            break

        # create the post (upload photo + draft)
        result = create_post(
            facebook_client, frame_path, post_message, current_episode, frame_number
        )
        if not result:
            break

        post_id, photo_id = result

        # post random crop as comment if enabled
        crop_ok = post_random_crop(facebook_client, post_id, frame_path, random_crop_config)
        # post subtitles as comment
        post_comment(facebook_client, post_id, subtitle_list, sub_comment_enabled)
        # publish the draft post
        make_post_public(facebook_client, post_id)

        # save the post link to the facebook log
        log_post_id(post_id, frame_number, current_episode, current_season)

        # repost to album if enabled
        album_name = None
        if album_repost_enabled and album_id:
            album_name = facebook_client.album_name(str(album_id))
            album_repost(
                facebook_client,
                photo_id,
                post_message,
                frame_path,
                album_id,
                album_repost_enabled,
            )

        # print status block to console
        print_post_status(
            season=current_season,
            episode=current_episode,
            total_episodes=total_episodes,
            frame=frame_number,
            index_fph=frame_number - current_frame + 1,
            fph=fph,
            max_frames=max_frames,
            has_subtitles=has_subtitles,
            crop_ok=crop_ok,
            repost_enabled=album_repost_enabled,
            album_name=album_name,
        )

        # save progress after each successful post
        _save_progress(config, current_season, current_episode, frame_number)

        sleep(posting_interval * 60)  # e.g. 2 min = 120 seconds

    # -------------------------------------------------------------------------
    # Update the page bio after the posting cycle
    # -------------------------------------------------------------------------
    bio_template = config.get("TEMPLATE_BIO_MSG")
    if bio_template:
        current_season  = progress["season"]
        current_episode = progress["episode"]
        current_frame   = progress["frame"]

        season_data = next(
            season_data
            for season_data in seasons_list
            if season_data["season"] == current_season
        )
        episode_data = next(
            episode_data
            for episode in season_data["episodes"]
            if episode_data["episode"] == current_episode
        )
        final_placeholders = {
            "season": current_season,
            "episode": current_episode,
            "episode_title": episode_data.get("title", ""),
            "frame_number": current_frame,
            "max_frames": episode_data.get("max_frames", 0),
            "img_fps": episode_data.get("img_fps"),
            "fph": fph,
            "post_interval": posting_interval,
            "execution_interval": get_workflow_interval_hours(),
        }

        bio_message = format_message(bio_template, final_placeholders)
        if bio_message:
            facebook_client.update_bio(bio_message)

