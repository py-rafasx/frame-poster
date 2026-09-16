"""
Summary step for GitHub Actions

This script is used to generate a summary of the workflow execution.
It reads environment variables and generates a markdown table with the status of each variable.

"""

import os
from collections.abc import Callable
from enum import Enum

from src.paths import project_path

# GitHub Actions GITHUB_STEP_SUMMARY environment variable or default to summary.md for local testing
SUMMARY_ENV = os.getenv("GITHUB_STEP_SUMMARY")
SUMMARY_LOCAL_FILE = project_path("summary.md")


class Status(Enum):
    """Status types for table rows."""

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


def write_summary(content: str) -> None:
    """Write a line to the summary output.

    When running inside GitHub Actions the content goes to the file pointed by
    ``GITHUB_STEP_SUMMARY``.  Locally it falls back to ``summary.md``.
    """
    target = SUMMARY_ENV or SUMMARY_LOCAL_FILE
    with open(target, "a", encoding="utf-8") as f:
        f.write(content + "\n")


def format_success(text: str) -> str:
    """Return a success badge formatted for GitHub Actions summary output."""
    return f"$\\fbox{{\\color{{#2ea44f}}\\textsf{{✅  {text}}}}}$"  # latex mathjax


def format_error(text: str) -> str:
    """Return an error badge formatted for GitHub Actions summary output."""
    return f"$\\fbox{{\\color{{#d73a49}}\\textsf{{❌  {text}}}}}$"  # latex mathjax


def format_warning(text: str) -> str:
    """Return a warning badge formatted for GitHub Actions summary output."""
    return f"⚠️ {text}"


STATUS_FORMATTERS: dict[Status, Callable[[str], str]] = {
    Status.SUCCESS: format_success,
    Status.ERROR: format_error,
    Status.WARNING: format_warning,
}


def add_summary_row(key: str, value: str, status: Status) -> None:
    """Add a single row to the summary from *anywhere*.

    Call this from poster.py, frame_utils.py, or anywhere in main.py
    without needing a ``with SummaryTable()`` block.
    """
    formatter = STATUS_FORMATTERS.get(status)
    if formatter:
        value = formatter(value)
    write_summary(f"| `{key}` | {value} |")


def start_summary() -> None:
    """Open the summary table — call once at the beginning.

    Use with ``end_summary()`` instead of the ``with SummaryTable()``
    context manager when rows need to be added from multiple places.

    Locally (no GITHUB_STEP_SUMMARY) the fallback file is truncated so
    repeated runs do not accumulate duplicate tables.
    """
    if not SUMMARY_ENV and SUMMARY_LOCAL_FILE.exists():
        SUMMARY_LOCAL_FILE.write_text("", encoding="utf-8")

    write_summary('<h1 align="center">Resume of execution</h1>')
    write_summary('<div align="center">')
    write_summary("\n| Variable | Status |")
    write_summary("|----------|---------|")


def end_summary() -> None:
    """Close the summary table — call once at the end."""
    write_summary("</div>")
