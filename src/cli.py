"""Command-line argument parsing for frame-poster."""

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run frame-poster with centralized config and token override."
    )

    parser.add_argument(
        "--fb-token",
        default=None,
        help="Facebook access token to use for this run. Overrides FB_TOKEN environment variable.",
    )
    return parser.parse_args(argv)
