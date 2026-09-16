from pathlib import Path

from src.facebook import FacebookGraphAPI
from src.frame_utils import random_crop
from src.logger import get_logger

logger = get_logger(__name__)


def create_post(
    facebook_client: FacebookGraphAPI,
    frame_path: Path,
    message: str,
    current_episode: int,
    frame_number: int,
) -> tuple[str, str] | None:
    """Upload photo and create unpublished post in sequence.

    Returns:
        (post_id, photo_id) if successful, None otherwise.
    """
    photo_id = facebook_client.upload_photo(frame_path, message)
    if not photo_id:
        logger.error(
            "Failed to upload photo: episode %s, frame %s",
            current_episode,
            frame_number,
        )
        return None

    post_id = facebook_client.create_unpublished_post(message, photo_id)
    if not post_id:
        logger.error("Failed to create post: episode %s, frame %s", current_episode, frame_number)
        return None

    return post_id, photo_id


def post_comment(
    facebook_client: FacebookGraphAPI,
    post_id: str,
    subtitles: list[dict[str, str]] | None,
    sub_comment_enabled: bool,
):
    if not sub_comment_enabled:
        return
    if not subtitles:
        return

    comments = []
    english_comment = None

    for sub_dict in subtitles:
        lang = sub_dict.get("lang")
        text = sub_dict.get("text")
        comment = f"[{lang}]\n{text}\n\n"

        if lang == "English":
            english_comment = comment
        else:
            comments.append(comment)

    if english_comment:
        comments.insert(0, english_comment)

    try:
        facebook_client.comments_post(post_id, "".join(comments))
    except Exception as e:
        logger.error("Failed to post comment: %s", e)


def post_random_crop(
    facebook_client: FacebookGraphAPI,
    post_id: str,
    frame_path: Path,
    random_crop_config: dict,
) -> bool:
    """Crop the frame randomly and post it as a comment."""
    if not random_crop_config.get("enabled", False):
        return False

    result = random_crop(frame_path, random_crop_config)
    if not result:
        return False

    cropped_path, crop_message = result
    try:
        facebook_client.comments_post(post_id, crop_message, frame_path=cropped_path)
        return True
    except Exception as e:
        logger.error("Failed to post random crop comment: %s", e)
        return False


def album_repost(
    facebook_client: FacebookGraphAPI,
    photo_id: str,
    message: str,
    frame_path: Path,
    album_id: str | None,
    reposting: bool,
):
    """Repost the frame directly to the album using the existing photo_id."""
    if not reposting:
        return

    facebook_client.album_repost(
        message=message,
        frame_path=frame_path,
        album_id=album_id,
        reposting=reposting,
    )


def make_post_public(facebook_client: FacebookGraphAPI, post_id: str):
    """Publish a previously created draft post."""
    facebook_client.publish_post(post_id)
