from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap

from src.config_validator import validate_config
from src.logger import get_logger
from src.paths import project_path

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(
    mapping=2,
    sequence=4,
    offset=2,
)

logger = get_logger(__name__)

CONFIG_PATH = project_path("config.yml")


def load_configs() -> CommentedMap:
    """
    Load configuration from a YAML file preserving comments and formatting.

    Returns:
        CommentedMap: The configuration data loaded from the YAML file with comments preserved
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as file:
            return yaml.load(file)
    except (YAMLError, OSError) as e:
        logger.error("Error loading config file %s: %s", CONFIG_PATH, e)
        return CommentedMap()


def load_and_validate() -> CommentedMap:
    """
    Load configuration and validate it using custom validator.

    Returns:
        CommentedMap: The validated configuration with comments preserved

    Raises:
        ValidationError: If the configuration fails validation
    """
    config = load_configs()
    if not config:
        raise FileNotFoundError("Config file is empty or could not be loaded")

    validate_config(config)
    return config


def save_configs(config: CommentedMap) -> None:
    """
    Save configuration to a YAML file preserving comments and formatting.

    Args:
        config: The CommentedMap configuration data to save
    """
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            yaml.dump(config, file)
    except (YAMLError, OSError) as e:
        logger.error("Error saving config file %s: %s", CONFIG_PATH, e)
