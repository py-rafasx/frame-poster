"""
Custom validation for config.yml that works with ruamel.yaml CommentedMap.
Preserves the CommentedMap format while providing validation.
"""

from ruamel.yaml.comments import CommentedMap

from src.logger import get_logger

logger = get_logger(__name__)


class ConfigValidationError(ValueError):
    """Raised when config.yml contains one or more validation errors."""


def _report(errors: list[str], message: str) -> None:
    """Log a validation error and collect it."""
    errors.append(message)
    logger.error(message)


def validate_config(config: CommentedMap) -> None:
    """
    Validate the entire config structure.

    Collects all errors, logs them, and raises ConfigValidationError
    if any error was found (fail fast before posting starts).

    Args:
        config: The CommentedMap loaded from config.yml

    Raises:
        ConfigValidationError: If the configuration fails validation.
    """
    errors: list[str] = []

    # Validate top-level required fields
    required_fields = {
        "progress": dict,
        "seasons": list,
        "TEMPLATE_POST_MSG": str,
        "TEMPLATE_BIO_MSG": str,
        "TEMPLATE_RANDOM_FRAME_MSG": str,
        "TEMPLATE_RANDOM_TWO_PANELS_MSG": str,
        "posting": dict,
        "random_crop": dict,
    }

    for field, expected_type in required_fields.items():
        if field not in config:
            _report(errors, f"Missing required field: '{field}'")
        elif not isinstance(config[field], expected_type):
            _report(
                errors,
                f"Field '{field}' must be {expected_type.__name__}, "
                f"got {type(config[field]).__name__}",
            )

    # Validate progress section
    if "progress" in config:
        _validate_progress(config["progress"], errors)

    # Validate seasons section
    if "seasons" in config:
        _validate_seasons(config["seasons"], errors)

    # Validate posting section
    if "posting" in config:
        _validate_posting(config["posting"], errors)

    # Validate random_crop section
    if "random_crop" in config:
        _validate_random_crop(config["random_crop"], errors)

    # Validate optional filters section (used by random posts)
    if "filters" in config:
        _validate_filters(config["filters"], errors)

    # Validate optional fields with defaults
    if "facebook_api_version" in config and not isinstance(config["facebook_api_version"], str):
        _report(
            errors,
            "Field 'facebook_api_version' must be str, "
            f"got {type(config['facebook_api_version']).__name__}",
        )

    if "timezone" in config and not isinstance(config["timezone"], int):
        _report(errors, f"Field 'timezone' must be int, got {type(config['timezone']).__name__}")

    if errors:
        raise ConfigValidationError(
            f"config.yml validation failed with {len(errors)} error(s): {'; '.join(errors)}"
        )


def _validate_progress(progress: CommentedMap, errors: list[str]) -> None:
    """Validate progress section."""

    required = {
        "season": (str, int),
        "episode": (str, int),
        "frame": int,
    }

    for field, expected_types in required.items():
        allowed = expected_types if isinstance(expected_types, tuple) else (expected_types,)
        if field not in progress:
            _report(errors, f"Missing required field in progress: '{field}'")
        elif not isinstance(progress[field], allowed):
            type_name = " or ".join(t.__name__ for t in allowed)
            _report(
                errors,
                f"Field 'progress.{field}' must be {type_name}, "
                f"got {type(progress[field]).__name__}",
            )

    if "frame" in progress and isinstance(progress["frame"], int) and progress["frame"] < 0:
        _report(errors, "Field 'progress.frame' must be >= 0")


def _validate_seasons(seasons: list, errors: list[str]) -> None:
    """Validate seasons section."""

    if not seasons:
        _report(errors, "Field 'seasons' cannot be empty")

    for i, season in enumerate(seasons):
        if not isinstance(season, dict):
            _report(errors, f"Season {i} must be a dict, got {type(season).__name__}")
            continue

        # Validate season fields
        if "season" not in season:
            _report(errors, f"Season {i}: missing required field 'season'")
        elif not isinstance(season["season"], (str, int)):
            _report(
                errors,
                f"Season {i}: field 'season' must be str or int, "
                f"got {type(season['season']).__name__}",
            )

        # Validate episodes
        if "episodes" not in season:
            _report(errors, f"Season {i}: missing required field 'episodes'")
        elif not isinstance(season["episodes"], list):
            _report(
                errors,
                f"Season {i}: field 'episodes' must be list, "
                f"got {type(season['episodes']).__name__}",
            )
        else:
            _validate_episodes(season["episodes"], i, errors)


def _validate_episodes(episodes: list, season_index: int, errors: list[str]) -> None:
    """Validate episodes within a season."""

    if not episodes:
        _report(errors, f"Season {season_index}: episodes list cannot be empty")

    for i, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            _report(errors, f"episode {i}: must be a dict, got {type(episode).__name__}")
            continue

        # Required fields
        required = {
            "episode": (str, int),
            "max_frames": int,
            "github_repo": str,
        }

        for field, expected_types in required.items():
            allowed = expected_types if isinstance(expected_types, tuple) else (expected_types,)
            if field not in episode:
                _report(
                    errors,
                    f"season [{season_index}].episode index [{i}]: "
                    f"missing required field '{field}'",
                )
            elif not isinstance(episode[field], allowed):
                type_name = " or ".join(t.__name__ for t in allowed)
                _report(
                    errors,
                    f"season [{season_index}].episode index [{i}]: "
                    f"field '{field}' must be {type_name}, got {type(episode[field]).__name__}",
                )

        # Optional fields
        if (
            "title" in episode
            and episode["title"] is not None
            and not isinstance(episode["title"], str)
        ):
            _report(
                errors,
                f"episode {i}: field 'title' must be str or None, "
                f"got {type(episode['title']).__name__}",
            )

        album_id = episode.get("album_id")
        if album_id is not None and not isinstance(album_id, (str, int)):
            _report(
                errors,
                f"season [{season_index}].episode index [{i}]: "
                f"field 'album_id' must be str, int, or None, got {type(album_id).__name__}",
            )

        # Validate values
        if "img_fps" in episode:
            img_fps = episode["img_fps"]

            if img_fps is not None and img_fps != "":
                if not isinstance(img_fps, (int, float)):
                    _report(
                        errors,
                        f"season [{season_index}].episode index [{i}]: "
                        f"field 'img_fps' must be int or float, got {type(img_fps).__name__}",
                    )
                elif img_fps <= 0:
                    _report(
                        errors,
                        f"season [{season_index}].episode index [{i}]: field 'img_fps' must be > 0",
                    )

        if "max_frames" in episode:
            max_frames = episode["max_frames"]
            if isinstance(max_frames, int) and max_frames < 0:
                _report(
                    errors,
                    f"season [{season_index}].episode index [{i}]: field 'max_frames' must be >= 0",
                )


def _validate_posting(posting: CommentedMap, errors: list[str]) -> None:
    """Validate posting section."""

    required = {
        "fph": int,
        "post_interval": int,
        "sub_comment": bool,
        "album_repost": bool,
        "random_post": bool,
    }

    for field, expected_type in required.items():
        if field not in posting:
            _report(errors, f"Missing required field in posting: '{field}'")
        elif not isinstance(posting[field], expected_type):
            _report(
                errors,
                f"Field 'posting.{field}' must be {expected_type.__name__}, "
                f"got {type(posting[field]).__name__}",
            )

    # Validate values
    if "fph" in posting and isinstance(posting["fph"], int) and posting["fph"] < 1:
        _report(errors, "Field 'posting.fph' must be >= 1")

    if (
        "post_interval" in posting
        and isinstance(posting["post_interval"], int)
        and posting["post_interval"] < 1
    ):
        _report(errors, "Field 'posting.post_interval' must be >= 1")


def _validate_random_crop(random_crop: CommentedMap, errors: list[str]) -> None:
    """Validate random_crop section."""

    required = {
        "enabled": bool,
        "min_size": int,
        "max_size": int,
    }

    for field, expected_type in required.items():
        if field not in random_crop:
            _report(errors, f"Missing required field in random_crop: '{field}'")
        elif not isinstance(random_crop[field], expected_type):
            _report(
                errors,
                f"Field 'random_crop.{field}' must be {expected_type.__name__}, "
                f"got {type(random_crop[field]).__name__}",
            )

    # Validate values
    if "min_size" in random_crop and random_crop["min_size"] < 1:
        _report(errors, "Field 'random_crop.min_size' must be >= 1")

    if "max_size" in random_crop and random_crop["max_size"] < 1:
        _report(errors, "Field 'random_crop.max_size' must be >= 1")

    if (
        "min_size" in random_crop
        and "max_size" in random_crop
        and random_crop["min_size"] > random_crop["max_size"]
    ):
        _report(errors, "Field 'random_crop.min_size' must be <= random_crop.max_size")


def _validate_filters(filters: CommentedMap, errors: list[str]) -> None:
    """Validate optional filters section (used by random posts)."""

    if not isinstance(filters, dict):
        _report(errors, f"Field 'filters' must be dict, got {type(filters).__name__}")
        return

    if not filters:
        logger.warning("Field 'filters' is empty, random posts will use no filter")
        return

    for name, settings in filters.items():
        if not isinstance(settings, dict):
            _report(errors, f"filters.{name} must be a dict, got {type(settings).__name__}")
            continue

        if "enabled" not in settings:
            _report(errors, f"filters.{name}: missing required field 'enabled'")
        elif not isinstance(settings["enabled"], bool):
            _report(
                errors,
                f"filters.{name}.enabled must be bool, got {type(settings['enabled']).__name__}",
            )

        if "percent" not in settings:
            _report(errors, f"filters.{name}: missing required field 'percent'")
        elif not isinstance(settings["percent"], (int, float)):
            _report(
                errors,
                f"filters.{name}.percent must be int or float, "
                f"got {type(settings['percent']).__name__}",
            )
        elif settings["percent"] < 0:
            _report(errors, f"filters.{name}.percent must be >= 0")
