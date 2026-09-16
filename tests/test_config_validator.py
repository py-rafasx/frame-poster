from ruamel.yaml.comments import CommentedMap

from src.config_validator import ConfigValidationError, validate_config


def _valid_config() -> CommentedMap:
    return CommentedMap(
        {
            "progress": CommentedMap({"season": 1, "episode": 1, "frame": 0}),
            "seasons": [
                CommentedMap(
                    {
                        "season": 1,
                        "episodes": [
                            CommentedMap(
                                {
                                    "episode": 1,
                                    "max_frames": 100,
                                    "github_repo": "owner/repo/main/",
                                    "img_fps": 3.5,
                                }
                            )
                        ],
                    }
                )
            ],
            "TEMPLATE_POST_MSG": "Season {season}",
            "TEMPLATE_BIO_MSG": "Posting {fph} frames every {execution_interval} hours",
            "TEMPLATE_RANDOM_FRAME_MSG": "[Random] Frame",
            "TEMPLATE_RANDOM_TWO_PANELS_MSG": "[Random] Frames",
            "posting": CommentedMap(
                {
                    "fph": 15,
                    "post_interval": 2,
                    "sub_comment": True,
                    "album_repost": True,
                    "random_post": False,
                }
            ),
            "random_crop": CommentedMap({"enabled": True, "min_size": 200, "max_size": 600}),
        }
    )


def test_valid_config_passes():
    validate_config(_valid_config())


def test_missing_required_field_raises():
    config = _valid_config()
    del config["TEMPLATE_POST_MSG"]

    try:
        validate_config(config)
    except ConfigValidationError as error:
        assert "TEMPLATE_POST_MSG" in str(error)
    else:
        raise AssertionError("Expected ConfigValidationError")


def test_wrong_type_raises():
    config = _valid_config()
    config["TEMPLATE_POST_MSG"] = 123

    try:
        validate_config(config)
    except ConfigValidationError:
        pass
    else:
        raise AssertionError("Expected ConfigValidationError")


def test_negative_frame_raises():
    config = _valid_config()
    config["progress"]["frame"] = -5

    try:
        validate_config(config)
    except ConfigValidationError:
        pass
    else:
        raise AssertionError("Expected ConfigValidationError")
