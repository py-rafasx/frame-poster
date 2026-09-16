"""
Logger module for application logging.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from src.paths import project_path

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

LOGS_DIR = project_path("logs")

LOG_FILE = LOGS_DIR / "app.log"
FACEBOOK_LOG = LOGS_DIR / "facebook.log"

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(module)s:%(funcName)s:%(lineno)d] %(message)s"

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ─────────────────────────────────────────────────────────────────────────────
# Timezone configuration
# ─────────────────────────────────────────────────────────────────────────────

# Default timezone: UTC-3
_log_timezone = timezone(timedelta(hours=-3))


def set_timezone_offset(offset_hours: int = 0) -> None:
    """
    Sets the global UTC offset used by the logging system.

    This function should be called once when the application starts,
    before creating the application loggers.

    Args:
        offset_hours:
            Offset from UTC in hours.

            Examples:
                -3 -> UTC-3
                 0 -> UTC
                 3 -> UTC+3
    """
    global _log_timezone

    _log_timezone = timezone(timedelta(hours=offset_hours))


# ─────────────────────────────────────────────────────────────────────────────
# Sensitive data sanitization
# ─────────────────────────────────────────────────────────────────────────────

SENSITIVE_PATTERNS = [
    (
        r"(?i)(access_token(?:%3D|=))([^&\s]+)",
        "access_token=***",
    ),
    (
        r"(?i)(malformed\s+access\s+token)\s+[^\s\"]+",
        r"\1 ***",
    ),
]


def sanitize_log_message(message: str) -> str:
    """
    Sanitizes sensitive information from log messages.

    Args:
        message:
            The original log message.

    Returns:
        The sanitized message with sensitive data masked.
    """
    sanitized = message

    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = re.sub(
            pattern,
            replacement,
            sanitized,
            flags=re.IGNORECASE,
        )

    return sanitized


# ─────────────────────────────────────────────────────────────────────────────
# Formatter
# ─────────────────────────────────────────────────────────────────────────────


class SanitizingFormatter(logging.Formatter):
    """
    Custom formatter that:

    - Sanitizes sensitive information from log messages.
    - Formats timestamps using the globally configured UTC offset.
    """

    def formatTime(  # noqa: N802 - method name required by logging.Formatter
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        """
        Formats the log record timestamp using the configured UTC offset.
        """
        dt = datetime.fromtimestamp(
            record.created,
            tz=_log_timezone,
        )

        if datefmt:
            return dt.strftime(datefmt)

        return dt.isoformat()

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        """
        Sanitizes the final formatted log message.
        """
        # Resolve the final message first.
        original_message = record.getMessage()

        # Sanitize the resolved message.
        record.msg = sanitize_log_message(original_message)

        # Prevent logging.Formatter from trying to format
        # the arguments a second time.
        record.args = None

        return super().format(record)


# ─────────────────────────────────────────────────────────────────────────────
# Logger configuration
# ─────────────────────────────────────────────────────────────────────────────


DEFAULT_LOG_LEVEL = logging.ERROR

_root_configured = False


def get_logger(
    name: str,
) -> logging.Logger:
    """
    Configures and returns a logger with sanitization.

    The root logging configuration (file + console handlers) is created only
    once, on the first call, so importing a module has no side effects until a
    logger is actually needed. The logger uses the globally configured timezone
    offset.

    Args:
        name:
            Logger name, usually __name__.

    Returns:
        Configured logger instance.
    """
    global _root_configured

    if not _root_configured:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        formatter = SanitizingFormatter(
            LOG_FORMAT,
            DATE_FORMAT,
        )

        # File handler
        file_handler = logging.FileHandler(
            LOG_FILE,
            encoding="utf-8",
        )

        file_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler()

        console_handler.setFormatter(formatter)

        # Configure logging
        logging.basicConfig(
            level=DEFAULT_LOG_LEVEL,
            handlers=[
                file_handler,
                console_handler,
            ],
        )
        _root_configured = True

    return logging.getLogger(name)


# ─────────────────────────────────────────────────────────────────────────────
# Default module logger
# ─────────────────────────────────────────────────────────────────────────────

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Facebook post log
# ─────────────────────────────────────────────────────────────────────────────


def _format_identifier(value: int | str) -> str:
    """Zero-pad numeric identifiers for aligned log lines; strings stay as-is."""
    return f"{value:02d}" if isinstance(value, int) else str(value)


def log_post_id(
    post_id: str | None,
    frame: int,
    episode: int | str,
    season: int | str,
) -> None:
    """
    Append the permalink of a posted frame to the Facebook log file.

    Each entry follows the pattern:
        [YYYY-MM-DD HH:MM:SS] S01E03 | frame 0007 | https://www.facebook.com/{post_id}

    Numeric seasons/episodes are zero-padded; string identifiers
    (e.g. "OVA-2") are logged as-is. The timestamp uses the globally
    configured UTC offset.

    Args:
        post_id: The ID returned by the Facebook API. None logs an error and writes nothing.
        frame: The frame number that was posted.
        episode: The episode identifier (number or string).
        season: The season identifier (number or string).
    """

    if not post_id:
        logger.error(
            "Cannot log post ID: post_id is None for frame %s of episode %s",
            frame,
            episode,
        )
        return

    timestamp = datetime.now(_log_timezone).strftime(DATE_FORMAT)

    entry = (
        f"[{timestamp}] "
        f"S{_format_identifier(season)}E{_format_identifier(episode)}"
        f" | frame {frame:04d}"
        f" | https://www.facebook.com/{post_id}\n"
    )

    try:
        FACEBOOK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FACEBOOK_LOG.open("a", encoding="utf-8") as f:
            f.write(entry)

    except OSError as e:
        logger.error("Failed to append to fb log (%s): %s", FACEBOOK_LOG, e)
