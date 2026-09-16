from enum import Enum
from pathlib import Path
from threading import Lock

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.logger import get_logger

logger = get_logger(__name__)


class ApiVersion(str, Enum):
    """Supported Graph API versions. Update when Facebook launches
    or deprecates versions (https://developers.facebook.com/docs/graph-api/changelog)."""

    V20_0 = "v20.0"
    V21_0 = "v21.0"
    V22_0 = "v22.0"
    V23_0 = "v23.0"
    V24_0 = "v24.0"
    V25_0 = "v25.0"


def _is_retryable_exception(exception: BaseException) -> bool:
    """Return True when a Graph API failure should be retried.

    Network errors are retried, but HTTP 401/403 (invalid/expired token or
    missing permissions) are not, to avoid wasting retries on errors that
    will not resolve on their own.
    """
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code not in (401, 403)
    return isinstance(exception, httpx.HTTPError)


def _api_retry(error_callback):
    """Build a fresh retry decorator for Graph API calls.

    Exceptions propagate to tenacity so the retries actually happen; when all
    attempts fail, ``error_callback`` logs the failure and returns the method's
    documented failure value (None or False) instead of raising.
    """
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_retryable_exception),
        before_sleep=lambda retry_state: logger.warning(
            "%s failed (attempt %d), retrying...",
            getattr(retry_state.fn, "__name__", "graph-api-call"),
            retry_state.attempt_number,
        ),
        retry_error_callback=error_callback,
    )


def _fail_none(retry_state) -> None:
    """Log final failure and return None."""
    logger.error(
        "%s failed after %d attempts: %s",
        getattr(retry_state.fn, "__name__", "graph-api-call"),
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    )
    return None


def _fail_false(retry_state) -> bool:
    """Log final failure and return False."""
    logger.error(
        "%s failed after %d attempts: %s",
        getattr(retry_state.fn, "__name__", "graph-api-call"),
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    )
    return False


def _fail_token(retry_state) -> tuple[bool, str]:
    """Log final failure and return validate_token's failure tuple."""
    reason = str(retry_state.outcome.exception())
    logger.error(
        "Facebook token validation failed after %d attempts: %s",
        retry_state.attempt_number,
        reason,
    )
    return False, reason


BIO_MAX_LENGTH = 101


class FacebookGraphAPI:
    def __init__(
        self,
        access_token: str,
        api_version: ApiVersion | str = ApiVersion.V25_0,
    ):
        self.access_token = self._normalize_token(access_token)
        # Accept plain strings from config.yml (e.g. facebook_api_version: "v25.0")
        if isinstance(api_version, str):
            api_version = ApiVersion(api_version)
        self.api_version = api_version
        self.client = httpx.Client(
            base_url=f"https://graph.facebook.com/{self.api_version.value}",
            timeout=httpx.Timeout(30, connect=10),
        )
        self._album_name_cache: dict[str, str | None] = {}
        self._album_name_cache_lock = Lock()

        if not self.access_token:
            logger.error("Facebook access token is not defined")

    def __enter__(self) -> "FacebookGraphAPI":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self.client.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    @staticmethod
    def _normalize_token(token: str | None) -> str | None:
        if not token:
            return None

        # remove the FB_TOKEN prefix if present
        token = token.strip().removeprefix("FB_TOKEN=")
        return token or None

    @_api_retry(_fail_token)
    def validate_token(self) -> tuple[bool, str]:
        """Validate the Facebook token.

        Returns:
            (True, "") when the token is valid.
            (False, reason) when the token is missing or the call fails.
        """
        if not self.access_token:
            return False, "Facebook access token is not defined"

        response = self.client.get("/me", headers=self._headers)
        response.raise_for_status()
        return True, response.text

    @_api_retry(_fail_none)
    def upload_photo(
        self,
        frame_path: Path,
        message: str = "",
        album_id: str | None = None,
        published: bool = False,
    ) -> str | None:
        """Upload a photo to Facebook.

        Args:
            frame_path: Path to the image.
            message: Optional message for the photo.
            album_id: Optional album ID.
            published: If True, publishes the photo directly.

        Returns:
            Photo ID or None on error.
        """
        endpoint = f"/{album_id}/photos" if album_id else "/me/photos"
        params = {"published": str(published).lower()}
        if message:
            params["message"] = message

        try:
            with frame_path.open("rb") as image:
                response = self.client.post(
                    endpoint,
                    params=params,
                    files={"source": image},
                    headers=self._headers,
                )
                response.raise_for_status()

        except OSError as e:
            logger.error("error opening file %s: %s", frame_path, e)
            return None

        try:
            return response.json().get("id")
        except ValueError:
            logger.error("invalid response from API: %s", response.text)
            return None

    @_api_retry(_fail_none)
    def create_unpublished_post(self, message: str, photo_id: str) -> str | None:
        """Create a draft (unpublished) post referencing an already uploaded photo."""
        payload = {
            "message": message,
            "attached_media": [{"media_fbid": photo_id}],
            "published": "false",
        }
        response = self.client.post("/me/feed", json=payload, headers=self._headers)
        response.raise_for_status()

        try:
            return response.json().get("id")
        except ValueError:
            logger.error("invalid response from API: %s", response.text)
            return None

    @_api_retry(_fail_false)
    def publish_post(self, post_id: str) -> bool:
        """Publish a post previously created as a draft."""
        response = self.client.post(
            f"/{post_id}", params={"is_published": "true"}, headers=self._headers
        )
        response.raise_for_status()
        return True

    @_api_retry(_fail_false)
    def comments_post(
        self, post_id: str, message: str, frame_path: Path | None = None
    ) -> str | bool | None:
        """Comment on a post.

        Args:
            post_id: ID of the post to comment on.
            message: Comment text.
            frame_path: Optional path to an image attached to the comment.

        Returns:
            The comment ID on success, False otherwise.
        """
        try:
            if frame_path:
                with frame_path.open("rb") as f:
                    response = self.client.post(
                        f"/{post_id}/comments",
                        data={"message": message},
                        files={"source": f},
                        headers=self._headers,
                    )
            else:
                response = self.client.post(
                    f"/{post_id}/comments",
                    params={"message": message},
                    headers=self._headers,
                )

        except OSError as e:
            logger.error("Failed to open image %s: %s", frame_path, e)
            return False

        response.raise_for_status()

        try:
            return response.json().get("id")
        except ValueError:
            logger.error("invalid response from API: %s", response.text)
            return False

    @_api_retry(_fail_false)
    def update_bio(self, message: str) -> bool:
        """Update the Facebook bio/description.

        Args:
            message: New bio message.

        Returns:
            True if updated successfully, False otherwise.
        """
        if not message:
            logger.info("Bio message is empty, skipping update.")
            return True

        if len(message) > BIO_MAX_LENGTH:
            logger.warning(
                "Bio message is too long, truncating to %d characters.", BIO_MAX_LENGTH
            )
            message = message[:BIO_MAX_LENGTH]

        response = self.client.post("/me", params={"about": message}, headers=self._headers)
        response.raise_for_status()
        return True

    def album_name(self, album_id: str) -> str | None:
        """Return the name of an album with thread-safe cache.

        Args:
            album_id: Album ID.

        Returns:
            Album name or None on error.
        """
        with self._album_name_cache_lock:
            if album_id in self._album_name_cache:
                return self._album_name_cache[album_id]

        name = self._fetch_album_name(album_id)

        with self._album_name_cache_lock:
            self._album_name_cache[album_id] = name
        return name

    @_api_retry(_fail_none)
    def _fetch_album_name(self, album_id: str) -> str | None:
        """Fetch the album name from the API."""
        response = self.client.get(f"/{album_id}", params={"fields": "name"}, headers=self._headers)
        response.raise_for_status()
        return response.json().get("name")

    def album_repost(
        self,
        message: str = "",
        frame_path: Path | None = None,
        album_id: str | None = None,
        reposting: bool = False,
    ) -> str | None:
        """Repost a frame directly to an album (published).

        Args:
            message: Optional message.
            frame_path: Path to the image.
            album_id: Album ID.
            reposting: If True, enables repost.

        Returns:
            Photo ID or None on error.
        """
        if not reposting or not album_id or not frame_path:
            return None

        if not str(album_id).isdigit():
            logger.error(
                "Album repost enabled but album_id %r is not a valid integer",
                album_id,
            )
            return None

        photo_id = self.upload_photo(frame_path, message=message, album_id=album_id, published=True)
        if not photo_id:
            logger.error("Failed to repost frame to album %s", album_id)
            return None

        return photo_id
