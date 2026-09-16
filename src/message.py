from src.logger import get_logger

logger = get_logger(__name__)


class SafeDict(dict):
    _newline_aliases = {"newline", "new_line", "linebreak", "br"}

    def __missing__(self, key):
        key_name = str(key).strip().lower()
        if key_name in self._newline_aliases:
            return "\n"
        return f"{{{key}}}"


def format_message(message: str | None, placeholders: dict) -> str:
    """
    Format a message safely, without raising an exception when a
    placeholder is missing.

    Special newline placeholders are also accepted: {newline},
    {new_line}, {linebreak} and {br}.
    """
    if message is None:
        logger.error("format_message received None as message template")
        return ""

    sanitized_message = message.replace("{br}", "{newline}")
    return sanitized_message.format_map(SafeDict(placeholders))
