from __future__ import annotations

import logging
import os
import sys
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, NewType

from version import __version__


IS_APPIMAGE = "APPIMAGE" in os.environ and os.path.exists(os.environ["APPIMAGE"])
IS_PACKAGED = hasattr(sys, "_MEIPASS") or IS_APPIMAGE

CALL = logging.INFO - 1
logging.addLevelName(CALL, "CALL")

if sys.platform == "win32":
    SYS_SITE_PACKAGES = "Lib/site-packages"
    SYS_SCRIPTS = "Scripts"
else:
    version_info = sys.version_info
    SYS_SITE_PACKAGES = f"lib/python{version_info.major}.{version_info.minor}/site-packages"
    SYS_SCRIPTS = "bin"


if IS_APPIMAGE:
    SELF_PATH = Path(os.environ["APPIMAGE"]).resolve()
else:
    SELF_PATH = Path(sys.argv[0]).resolve()
    if SELF_PATH.stem == "pyinstaller" or SELF_PATH.name == "gui.py":
        SELF_PATH = Path(__file__).with_name("main.py").resolve()

if IS_PACKAGED and sys.platform == "darwin":
    WORKING_DIR = Path.home() / "Library/Application Support/Kick Drops Miner"
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
else:
    WORKING_DIR = SELF_PATH.parent
VENV_PATH = Path(WORKING_DIR, "env")
SITE_PACKAGES_PATH = Path(VENV_PATH, SYS_SITE_PACKAGES)
SCRIPTS_PATH = Path(VENV_PATH, SYS_SCRIPTS)


def _resource_path(relative_path: Path | str) -> Path:
    if IS_APPIMAGE:
        base_path = Path(sys.argv[0]).resolve().parent
    elif IS_PACKAGED:
        base_path = Path(getattr(sys, "_MEIPASS"))
    else:
        base_path = WORKING_DIR
    return base_path.joinpath(relative_path)


LANG_PATH = _resource_path("lang")
LANG_ARCHIVE = _resource_path("lang.zip")
LOG_PATH = Path(WORKING_DIR, "log.txt")
LOGS_PATH = Path(WORKING_DIR, "logs")
VERBOSE_LOG_PATH = Path(LOGS_PATH, "kick-drops-miner.log")
DUMP_PATH = Path(WORKING_DIR, "dump.dat")
LOCK_PATH = Path(WORKING_DIR, "lock.file")
CACHE_PATH = Path(WORKING_DIR, "cache")
CACHE_DB = Path(CACHE_PATH, "mapping.json")
COOKIES_PATH = Path(WORKING_DIR, "cookies.txt")
SETTINGS_PATH = Path(WORKING_DIR, "settings.json")

JsonType = Dict[str, Any]
URLType = NewType("URLType", str)

MAX_INT = sys.maxsize
MAX_WEBSOCKETS = 1
WS_TOPICS_LIMIT = 1
DEFAULT_LANG = "English"
WINDOW_TITLE = f"Kick Drops Miner v{__version__}"
KICK_CLIENT_TOKEN = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"

LOGGING_LEVELS = {
    0: logging.ERROR,
    1: logging.WARNING,
    2: logging.INFO,
    3: CALL,
    4: logging.DEBUG,
}
FILE_FORMATTER = logging.Formatter(
    "{asctime}.{msecs:03.0f}:\t{levelname:>7}:\t{message}",
    style="{",
    datefmt="%Y-%m-%d %H:%M:%S",
)
OUTPUT_FORMATTER = logging.Formatter("{levelname}: {message}", style="{", datefmt="%H:%M:%S")


class State(Enum):
    IDLE = auto()
    INVENTORY_FETCH = auto()
    GAMES_UPDATE = auto()
    CHANNELS_FETCH = auto()
    CHANNELS_CLEANUP = auto()
    CHANNEL_SWITCH = auto()
    EXIT = auto()


class PriorityMode(Enum):
    PRIORITY_ONLY = 0
    ENDING_SOONEST = 1
    LOW_AVBL_FIRST = 2
