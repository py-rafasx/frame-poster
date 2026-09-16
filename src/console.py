"""
Central Rich console module for styled terminal output.

Provides a shared Console instance and helper functions to keep
print-based output consistent, colorful, and easy to read.
"""

import pyfiglet
from rich.console import Console
from rich.markup import escape

# Shared console – use this everywhere instead of raw print().
console = Console()

SEPARATOR = "_______________________________________________________________________"


def _fmt_id(value: int | str) -> str:
    """Zero-pad numeric identifiers; strings stay as-is."""
    return f"{value:02d}" if isinstance(value, int) else str(value)


def _banner() -> None:
    """Render the shared Frame Poster ASCII art title."""
    title = pyfiglet.figlet_format("Frame Poster", font="slant")
    console.print(f"[bold cyan]{title}[/bold cyan]")


def print_sequential_header(
    season: int | str,
    episode: int | str,
    frame: int,
    max_frames: int,
) -> None:
    """Print a styled header before a sequential posting run begins.

    Output format:
        (Frame Poster ascii art)
        mode          : sequential
        resuming at   : S01E03 frame 0007/0015
        ______________________________________________
    """
    _banner()
    console.print(f"{'mode':<14}: [bold green]sequential[/bold green]")
    console.print(
        f"{'resuming at':<14}: "
        f"S{_fmt_id(season)}E{_fmt_id(episode)} frame {frame:04d}/{max_frames:04d}"
    )
    console.print(SEPARATOR)


def print_random_header(filters: dict | None = None) -> None:
    """Print a styled header before a random posting run begins.

    Output format:
        (Frame Poster ascii art)
        mode          : random
        active filters: none_filter (0.8), mirror (0.5)
        ______________________________________________

    Args:
        filters: The "filters" section from config.yml; enabled filters and
            their weights are listed in the header.
    """
    _banner()
    console.print(f"{'mode: '} [bold magenta]random[/bold magenta]")

    enabled = [
        f"{escape(str(name))} ({escape(str(settings.get('percent', 0)))})\n"
        for name, settings in (filters or {}).items()
        if isinstance(settings, dict) and settings.get("enabled", False)
    ]
    console.print(f"{'active filters'}\n{''.join(enabled) or escape('[none]')}")
    console.print(SEPARATOR)


def print_post_status(
    season: int | str,
    episode: int | str,
    total_episodes: int,
    frame: int,
    index_fph: int,
    fph: int,
    max_frames: int,
    has_subtitles: bool,
    crop_ok: bool,
    repost_enabled: bool,
    album_name: str | None = None,
) -> None:
    """Print the per-frame posting status block to the console.

    Output format:
        ______________________________________________
        season      : 1
        episode     : 1/12
        frame       : 1/15
        subtitles   : [ok]
        random_crop : [ok]
        repost      : [ok] - album_name
        ______________________________________________
    """
    sub_status = escape("[ok]") if has_subtitles else escape("[--]")
    crop_status = escape("[ok]") if crop_ok else escape("[--]")
    if repost_enabled and album_name:
        repost_status = f"{escape('[ok]')} - {escape(album_name)}"
    else:
        repost_status = escape("[--]")

    lines = [
        f"season        : {season}",
        f"episode       : {episode}/{total_episodes}",
        f"frame         : {index_fph}/{fph} of {frame}/{max_frames}",
        f"subtitles     : {sub_status}",
        f"random_crop   : {crop_status}",
        f"repost in     : {repost_status}",
        SEPARATOR,
    ]

    console.print("\n".join(lines))


def print_random_status(
    season: int | str,
    frames: list[tuple[int | str, int]],
    filter_name: str,
    has_subtitles: bool,
    crop_ok: bool,
) -> None:
    """Print the per-post status block for random posts.

    Unlike sequential posts there is no album repost line: random frames
    are never reposted to an album.

    Output format:
        ______________________________________________
        mode          : random
        filter        : mirror
        source        : S01/E03 frame 142
        subtitles     : [ok]
        random_crop   : [ok]
        ______________________________________________

    Args:
        season: Season identifier (number or string).
        frames: One (episode, frame_number) tuple per panel
            (single post or two_panels).
        filter_name: Name of the filter applied to the image.
        has_subtitles: Whether a subtitle comment was posted.
        crop_ok: Whether a random crop comment was posted.
    """

    def _fmt_id(value: int | str) -> str:
        """Zero-pad numeric identifiers; strings stay as-is."""
        return f"{value:02d}" if isinstance(value, int) else str(value)

    def _source(episode: int | str, number: int) -> str:
        return f"S{_fmt_id(season)}/E{_fmt_id(episode)} frame {number}"

    sub_status = escape("[ok]") if has_subtitles else escape("[--]")
    crop_status = escape("[ok]") if crop_ok else escape("[--]")

    lines = [
        "mode          : random",
        f"filter        : {escape(filter_name)}",
        f"source        : {' + '.join(_source(*f) for f in frames)}",
        f"subtitles     : {sub_status}",
        f"random_crop   : {crop_status}",
        SEPARATOR,
    ]

    console.print("\n".join(lines))
