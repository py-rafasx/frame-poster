"""
This module provides functions to calculate the average run interval of GitHub Actions workflows.
"""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean

import yaml
from croniter import croniter

from src.logger import get_logger
from src.paths import project_path

logger = get_logger(__name__)


# Constants
WORKFLOW_PATH = str(project_path(".github", "workflows", "starter.yml"))
DEFAULT_RUNS = 20
SECONDS_PER_HOUR = 3600


@lru_cache(maxsize=1)
def _read_cron_expression(file_path: str = WORKFLOW_PATH) -> str | None:
    """
    Reads and returns the cron expression from a GitHub Actions workflow file.

    Args:
        file_path: Path to the workflow YAML file.

    Returns:
        The cron expression string, or None if not found.
    """
    try:
        with Path(file_path).open("r") as f:
            content: dict = yaml.safe_load(f)
            if not content:
                return None
            on_schedule = content.get(True)
            if not on_schedule:
                return None
            schedule_list = on_schedule.get("schedule")
            if not schedule_list:
                return None
            return schedule_list[0].get("cron")
    except (FileNotFoundError, KeyError, AttributeError) as e:
        logger.error("Error reading cron expression: %s", e)
        return None


@lru_cache(maxsize=1)
def _calc_average_run_interval(cron_expr: str, runs: int = DEFAULT_RUNS) -> float | None:
    """
    Calculates the average run interval in seconds for a given cron expression.

    Args:
        cron_expr: A cron expression string (e.g., "0 */3 * * *").
        runs: Number of runs to calculate the average interval for.

    Returns:
        The average run interval in seconds, or None if calculation fails.
    """
    try:
        cron_iter = croniter(cron_expr)
        intervals = []

        # Discard first run as it may be inconsistent
        prev_time = cron_iter.get_next(datetime)

        for _ in range(runs):
            next_time = cron_iter.get_next(datetime)
            interval = (next_time - prev_time).total_seconds()
            intervals.append(interval)
            prev_time = next_time

        return mean(intervals)
    except Exception as e:
        logger.error("Error calculating interval: %s", e)
        return None


@lru_cache(maxsize=1)
def get_workflow_interval_hours(file_path: str = WORKFLOW_PATH) -> str | None:
    """
    Returns the workflow's average run interval in hours.

    Args:
        file_path: Path to the workflow YAML file.

    Returns:
        The interval in hours as a string, or None if calculation fails.
    """
    cron_expr = _read_cron_expression(file_path)
    if not cron_expr:
        return None

    avg_seconds = _calc_average_run_interval(cron_expr)
    if avg_seconds is None:
        return None

    return str(int(avg_seconds / SECONDS_PER_HOUR))
