import os

from dotenv import load_dotenv
from ruamel.yaml import CommentedMap

from src.cli import parse_args
from src.facebook import ApiVersion, FacebookGraphAPI
from src.load_configs import load_and_validate
from src.logger import get_logger, set_timezone_offset
from src.random_post import random_post
from src.sequential_post import sequential_post
from src.summary_step import Status, add_summary_row, end_summary, start_summary

# define logger for registre errors in code
logger = get_logger(__name__)

load_dotenv()


def main(argv: list[str] | None = None) -> None:
    """main function"""

    # ---------------------------------------Ambient config---------------------------------------
    # Parse arguments of the command line
    args = parse_args(argv)

    if args.fb_token:
        os.environ["FB_TOKEN"] = args.fb_token.strip()

    config: CommentedMap = load_and_validate()
    set_timezone_offset(config.get("timezone", 0))

    token = os.environ.get("FB_TOKEN", "").strip()
    if not token:
        logger.error("FB_TOKEN environment variable is missing or empty")
        return

    facebook_client = FacebookGraphAPI(
        access_token=token,
        api_version=config.get("facebook_api_version", ApiVersion.V25_0),
    )

    # ---------------------------------------------------------------------------------------------
    # Validate Facebook token and add to a github action summary
    start_summary()
    status, reason = facebook_client.validate_token()
    if not status:
        add_summary_row("FB_TOKEN", f"invalid or expired: {reason}", Status.ERROR)
        logger.error("Facebook token validation failed: %s", reason)
        return

    add_summary_row("FB_TOKEN", "found and validated successfully", Status.SUCCESS)
    end_summary()

    # ---------------------------------------------------------------------------------------------

    # define if the post will be random or sequential
    post_mode: bool = config.get("posting", {}).get("random_post", False)

    if not post_mode:
        sequential_post(facebook_client, config)  # follow the order in the config file "progress"

    else:
        random_post(facebook_client, config)  # post random frames


if __name__ == "__main__":
    main()
