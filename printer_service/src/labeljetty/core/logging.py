import logging
import sys
import os
import hashlib
from typing import Optional, Dict, Tuple
import inspect
from pathlib import Path
from labeljetty.config import Config, get_config

config = get_config()


APP_LOGGER_DEFAULT_NAME = config.APP_NAME


# suppress "AttributeError: module 'bcrypt' has no attribute '__about__'"-warning
# https://github.com/pyca/bcrypt/issues/684
logging.getLogger("passlib").setLevel(logging.ERROR)


# ANSI Color codes
class Colors:
    """ANSI color codes for terminal output"""

    RESET = "\033[0m"

    # Log level colors
    DEBUG = "\033[36m"  # Cyan
    INFO = "\033[32m"  # Green
    WARNING = "\033[33m"  # Yellow
    ERROR = "\033[31m"  # Red
    CRITICAL = "\033[35m"  # Magenta

    # Module name colors - distinctive, neutral palette
    MODULE_COLORS = [
        "\033[34m",  # Blue
        "\033[33m",  # Yellow
        "\033[32m",  # Green
        "\033[36m",  # Cyan
        "\033[35m",  # Magenta
        "\033[94m",  # Bright Blue
        "\033[93m",  # Bright Yellow
        "\033[92m",  # Bright Green
        "\033[96m",  # Bright Cyan
        "\033[95m",  # Bright Magenta
        "\033[91m",  # Bright Red (subtle, for modules)
    ]


def get_loglevel():
    return os.getenv("LOG_LEVEL", config.LOG_LEVEL)


def get_module_color(module_name: str) -> str:
    """
    Generate a deterministic, unique color for each module name.
    Same module name will always get the same color.
    """
    if config.LOG_DISABLE_COLORS:
        return ""

    hash_digest = hashlib.md5(module_name.encode()).hexdigest()
    hash_int = int(hash_digest, 16)
    color_index = hash_int % len(Colors.MODULE_COLORS)
    return Colors.MODULE_COLORS[color_index]


def get_loglevel_color(level: int) -> str:
    """Get the color for a specific log level"""
    if config.LOG_DISABLE_COLORS:
        return ""

    if level >= logging.CRITICAL:
        return Colors.CRITICAL
    elif level >= logging.ERROR:
        return Colors.ERROR
    elif level >= logging.WARNING:
        return Colors.WARNING
    elif level >= logging.INFO:
        return Colors.INFO
    else:  # DEBUG and below
        return Colors.DEBUG


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to log output"""

    GRAY = "\033[90m"  # Bright black (dark gray)

    def format(self, record):
        # Get colors
        levelcolor = get_loglevel_color(record.levelno)

        # Color the level name
        record.levelname = f"{levelcolor}{record.levelname}{Colors.RESET if not config.LOG_DISABLE_COLORS else ''}"

        # Format the record
        result = super().format(record)

        # Color the timestamp gray if colors are enabled
        if not config.LOG_DISABLE_COLORS:
            parts = result.split(" - ", 1)
            if parts:
                timestamp = parts[0]
                rest = " - " + parts[1] if len(parts) > 1 else ""
                result = f"{self.GRAY}{timestamp}{Colors.RESET}{rest}"

        return result


active_loggers_store = None


def get_logger(
    name: Optional[str] = APP_LOGGER_DEFAULT_NAME, modulename: Optional[str] = ""
) -> logging.Logger:
    global active_loggers_store
    if active_loggers_store is None:
        active_loggers_store = {}
    if not modulename:
        modulename = Path(inspect.stack()[1].filename).name
    store_name = f"{name}{modulename}"
    module = ""
    module_color_code = ""

    if modulename:
        module_color_code = get_module_color(modulename)
        module = f" - [{module_color_code}{modulename}{Colors.RESET}]"

    logger_ = None

    if store_name not in active_loggers_store:
        logger_ = logging.getLogger(store_name)
        logger_.setLevel(get_loglevel())

        # Clear existing handlers to avoid duplicate logs
        logger_.handlers.clear()

        handler = logging.StreamHandler(sys.stdout)

        format_string = f"%(asctime)s - {name}{module} - %(levelname)s - %(message)s"
        formatter = ColoredFormatter(format_string)
        handler.setFormatter(formatter)

        logger_.addHandler(handler)
        active_loggers_store[store_name] = logger_
    else:
        logger_ = active_loggers_store[store_name]

    return logger_


def get_uvicorn_loglevel() -> str:
    # uvicorn has a different log level naming system than python, we need to translate the log level setting
    UVICORN_LOG_LEVEL_map: Dict[Tuple[int | str, ...], str] = {
        (logging.NOTSET, "NOTSET", "notset", "0"): "trace",
        (logging.CRITICAL, "50", "CRITICAL", "critical", "FATAL", "fatal"): "critical",
        (logging.ERROR, "40", "ERROR", "error"): "error",
        (logging.WARNING, "30", "WARNING", "warning", "WARN", "warn"): "warning",
        (logging.INFO, "20", "INFO", "info"): "info",
        (logging.DEBUG, "10", "DEBUG", "debug"): "debug",
    }

    # if the uvicorn log level is not defined, it will be the same as the python log level
    UVICORN_LOG_LEVEL: str = (
        config.UVICORN_LOG_LEVEL
        if config.UVICORN_LOG_LEVEL is not None
        else config.LOG_LEVEL
    )
    uvicorn_log_level_mapped: str | None = None
    for key, val in UVICORN_LOG_LEVEL_map.items():
        if UVICORN_LOG_LEVEL in key:
            uvicorn_log_level_mapped = val
            break
    if uvicorn_log_level_mapped is None:
        uvicorn_log_level_mapped = "info"
    return uvicorn_log_level_mapped
