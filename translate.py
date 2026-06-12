from __future__ import annotations

import json
import zipfile
from collections import abc
from pathlib import Path
from typing import Any, TypedDict, cast, TYPE_CHECKING

from exceptions import MinerException
from utils import json_load, json_save, merge_json
from constants import IS_PACKAGED, LANG_PATH, LANG_ARCHIVE, DEFAULT_LANG

if TYPE_CHECKING:
    from typing_extensions import NotRequired


class StatusMessages(TypedDict):
    terminated: str
    watching: str
    goes_online: str
    goes_offline: str
    claimed_drop: str
    no_channel: str
    no_campaign: str


class ChromeMessages(TypedDict):
    startup: str
    login_to_complete: str
    no_token: str
    closed_window: str


class LoginMessages(TypedDict):
    chrome: ChromeMessages
    error_code: str
    unexpected_content: str
    email_code_required: str
    twofa_code_required: str
    incorrect_login_pass: str
    incorrect_email_code: str
    incorrect_twofa_code: str


class ErrorMessages(TypedDict):
    captcha: str
    no_connection: str
    site_down: str


class GUIStatus(TypedDict):
    name: str
    idle: str
    exiting: str
    terminated: str
    cleanup: str
    gathering: str
    switching: str
    fetching_inventory: str
    fetching_campaigns: str
    adding_campaigns: str


class GUITabs(TypedDict):
    main: str
    inventory: str
    settings: str
    help: str


class GUITray(TypedDict):
    notification_title: str
    minimize: str
    show: str
    quit: str


class GUILoginForm(TypedDict):
    name: str
    labels: str
    logging_in: str
    logged_in: str
    logged_out: str
    request: str
    required: str
    username: str
    password: str
    twofa_code: str
    button: str


class GUIWebsocket(TypedDict):
    name: str
    websocket: str
    initializing: str
    connected: str
    disconnected: str
    connecting: str
    disconnecting: str
    reconnecting: str


class GUIProgress(TypedDict):
    name: str
    drop: str
    game: str
    campaign: str
    remaining: str
    drop_progress: str
    campaign_progress: str


class GUIChannelHeadings(TypedDict):
    channel: str
    status: str
    game: str
    viewers: str


class GUIChannels(TypedDict):
    name: str
    switch: str
    online: str
    pending: str
    offline: str
    headings: GUIChannelHeadings


class GUIInvFilter(TypedDict):
    name: str
    show: str
    not_linked: str
    upcoming: str
    expired: str
    excluded: str
    finished: str
    refresh: str


class GUIInvStatus(TypedDict):
    linked: str
    not_linked: str
    active: str
    expired: str
    upcoming: str
    claimed: str
    ready_to_claim: str


class GUIInventory(TypedDict):
    filter: GUIInvFilter
    status: GUIInvStatus
    starts: str
    ends: str
    allowed_channels: str
    all_channels: str
    and_more: str
    percent_progress: str
    minutes_progress: str


class GUISettingsGeneral(TypedDict):
    name: str
    autostart: str
    tray: str
    tray_notifications: str
    dark_mode: str
    verbose_logging: str
    verbose_enabled: str
    verbose_disabled: str
    priority_mode: str
    proxy: str


class GUISettingsAdvanced(TypedDict):
    name: str
    warning: str
    warning_text: str
    enable_badges_emotes: str
    available_drops_check: str


class GUIPriorityModes(TypedDict):
    priority_only: str
    ending_soonest: str
    low_availability: str


class GUISettings(TypedDict):
    general: GUISettingsGeneral
    advanced: GUISettingsAdvanced
    priority_modes: GUIPriorityModes
    game_name: str
    priority: str
    exclude: str
    reload: str
    reload_text: str


class GUIHelpLinks(TypedDict):
    name: str
    inventory: str
    campaigns: str


class GUIHelp(TypedDict):
    links: GUIHelpLinks
    how_it_works: str
    how_it_works_text: str
    getting_started: str
    getting_started_text: str


class GUIMessages(TypedDict):
    output: str
    status: GUIStatus
    tabs: GUITabs
    tray: GUITray
    login: GUILoginForm
    websocket: GUIWebsocket
    progress: GUIProgress
    channels: GUIChannels
    inventory: GUIInventory
    settings: GUISettings
    help: GUIHelp


class Translation(TypedDict):
    language_name: NotRequired[str]
    english_name: str
    status: StatusMessages
    login: LoginMessages
    error: ErrorMessages
    gui: GUIMessages


default_translation: Translation = {
    "english_name": "English",
    "status": {
        "terminated": "\nApplication Terminated.\nClose the window to exit the application.",
        "watching": "Watching: {channel}",
        "goes_online": "{channel} goes ONLINE, switching...",
        "goes_offline": "{channel} goes OFFLINE, switching...",
        "claimed_drop": "Claimed drop: {drop}",
        "no_channel": "No available channels to watch. Waiting for an ONLINE channel...",
        "no_campaign": "No active campaigns to mine drops for. Waiting for an active campaign...",
    },
    "login": {
        "unexpected_content": (
            "Unexpected content type returned, usually due to being redirected. "
            "Do you need to login for internet access?"
        ),
        "chrome": {
            "startup": "Opening Chrome...",
            "login_to_complete": (
                "Complete the login procedure manually by pressing the Login button again."
            ),
            "no_token": "No authorization token could be found.",
            "closed_window": (
                "The Chrome window was closed before the login procedure could be completed."
            ),
        },
        "error_code": "Login error code: {error_code}",
        "incorrect_login_pass": "Incorrect username or password.",
        "incorrect_email_code": "Incorrect email code.",
        "incorrect_twofa_code": "Incorrect 2FA code.",
        "email_code_required": "Email code required. Check your email.",
        "twofa_code_required": "2FA token required.",
    },
    "error": {
        "captcha": "Kick rejected the login session. Import a fresh cookies.txt file.",
        "site_down": "Kick is down, retrying in {seconds} seconds...",
        "no_connection": "Cannot connect to Kick, retrying in {seconds} seconds... ({url})",
    },
    "gui": {
        "output": "Output",
        "status": {
            "name": "Status",
            "idle": "Idle",
            "exiting": "Exiting...",
            "terminated": "Terminated",
            "cleanup": "Cleaning up channels...",
            "gathering": "Gathering channels...",
            "switching": "Switching the channel...",
            "fetching_inventory": "Fetching inventory...",
            "fetching_campaigns": "Fetching campaigns...",
            "adding_campaigns": "Adding campaigns to inventory... {counter}",
        },
        "tabs": {
            "main": "Main",
            "inventory": "Inventory",
            "settings": "Settings",
            "help": "Help",
        },
        "tray": {
            "notification_title": "Mined Drop",
            "minimize": "Minimize to Tray",
            "show": "Show",
            "quit": "Quit",
        },
        "login": {
            "name": "Kick Account",
            "labels": "Status:\nPlatform:",
            "logged_in": "Logged in",
            "logged_out": "Logged out",
            "logging_in": "Logging in...",
            "required": "Login required",
            "request": "Export Kick cookies in Netscape cookies.txt format, then import the file.",
            "username": "Username",
            "password": "Password",
            "twofa_code": "2FA code (optional)",
            "button": "Import cookies.txt",
        },
        "websocket": {
            "name": "Websocket Status",
            "websocket": "Websocket #{id}:",
            "initializing": "Initializing...",
            "connected": "Connected",
            "disconnected": "Disconnected",
            "connecting": "Connecting...",
            "disconnecting": "Disconnecting...",
            "reconnecting": "Reconnecting...",
        },
        "progress": {
            "name": "Campaign Progress",
            "drop": "Drop:",
            "game": "Game:",
            "campaign": "Campaign:",
            "remaining": "{time} remaining",
            "drop_progress": "Progress:",
            "campaign_progress": "Progress:",
        },
        "channels": {
            "name": "Channels",
            "switch": "Switch",
            "online": "ONLINE  ✔",
            "pending": "OFFLINE ⏳",
            "offline": "OFFLINE ❌",
            "headings": {
                "channel": "Channel",
                "status": "Status",
                "game": "Game",
                "viewers": "Viewers",
            },
        },
        "inventory": {
            "filter": {
                "name": "Filter",
                "show": "Show:",
                "not_linked": "Not linked",
                "upcoming": "Upcoming",
                "expired": "Expired",
                "excluded": "Excluded",
                "finished": "Finished",
                "refresh": "Refresh",
            },
            "status": {
                "linked": "Linked ✔",
                "not_linked": "Not Linked ❌",
                "active": "Active ✔",
                "upcoming": "Upcoming ⏳",
                "expired": "Expired ❌",
                "claimed": "Claimed ✔",
                "ready_to_claim": "Ready to claim ⏳",
            },
            "starts": "Starts: {time}",
            "ends": "Ends: {time}",
            "allowed_channels": "Allowed Channels:",
            "all_channels": "All",
            "and_more": "and {amount} more...",
            "percent_progress": "{percent} of {minutes} minutes",
            "minutes_progress": "{minutes} minutes",
        },
        "settings": {
            "general": {
                "name": "General",
                "autostart": "Autostart: ",
                "tray": "Autostart into tray: ",
                "tray_notifications": "Tray notifications: ",
                "dark_mode": "Dark mode: ",
                "verbose_logging": "Verbose diagnostic logging: ",
                "verbose_enabled": "Verbose logging enabled: {path}",
                "verbose_disabled": "Verbose logging disabled.",
                "priority_mode": "Priority mode: ",
                "proxy": "Proxy (requires restart):",
            },
            "advanced": {
                "name": "Advanced",
                "warning": "Private Kick API",
                "warning_text": (
                    "Kick does not publish a Drops API.\n"
                    "Endpoint changes may require an application update."
                ),
                "enable_badges_emotes": "Enable partial support for badges and emotes: ",
                "available_drops_check": "Enable extra available drops check: ",
            },
            "priority_modes": {
                "priority_only": "Priority list only",
                "ending_soonest": "Ending soonest",
                "low_availability": "Low availability first",
            },
            "game_name": "Game name",
            "priority": "Priority",
            "exclude": "Exclude",
            "reload": "Reload",
            "reload_text": "Most changes require a reload to take an immediate effect: ",
        },
        "help": {
            "links": {
                "name": "Useful Links",
                "inventory": "See Kick drops",
                "campaigns": "See all Kick campaigns",
            },
            "how_it_works": "How It Works",
            "how_it_works_text": (
                "The application connects to Kick's viewer websocket and reports the active "
                "livestream without downloading video or audio. It periodically refreshes "
                "campaign progress, changes channels when needed, and claims completed rewards."
            ),
            "getting_started": "Getting Started",
            "getting_started_text": (
                "1. Log in to Kick in your browser and export kick.com cookies "
                "in Netscape cookies.txt format.\n"
                "2. Import the cookies.txt file in the application.\n"
                "3. If you're interested in mining everything possible, "
                "change the Priority Mode to anything other than \"Priority list only\" "
                "and press on \"Reload\".\n"
                "4. If you want to mine specific games first, use the \"Priority\" list "
                "to set up an ordered list of games of your choice. "
                "Games from the top of the list will be attempted to be mined first, "
                "before the ones lower down the list.\n"
                "5. Keep the \"Priority mode\" selected as \"Priority list only\", "
                "to avoid mining games that are not on the priority list. "
                "Or not - it's up to you.\n"
                "6. Use the \"Exclude\" list to tell the application "
                "which games should never be mined.\n"
                "7. Changing the contents of either of the lists, or changing "
                "the \"Priority mode\", requires you to press on \"Reload\" "
                "for the changes to take an effect."
            ),
        },
    },
}


class Translator:
    def __init__(self) -> None:
        self._langs: list[str] = []
        self._language_files: dict[str, Path | str] = {}
        # start with (and always copy) the default translation
        self._translation: Translation = default_translation.copy()
        # if we're in dev, update the template English.json file
        if not IS_PACKAGED:
            default_langpath = LANG_PATH.joinpath(f"{DEFAULT_LANG}.json")
            json_save(default_langpath, default_translation)
        self._translation["language_name"] = DEFAULT_LANG
        # load available translation names
        if LANG_PATH.is_dir():
            for filepath in LANG_PATH.glob("*.json"):
                self._language_files[filepath.stem] = filepath
        elif LANG_ARCHIVE.is_file():
            with zipfile.ZipFile(LANG_ARCHIVE) as archive:
                for filename in archive.namelist():
                    if filename.endswith(".json"):
                        self._language_files[Path(filename).stem] = filename
        self._langs.extend(self._language_files)
        self._langs.sort()
        if DEFAULT_LANG in self._langs:
            self._langs.remove(DEFAULT_LANG)
        self._langs.insert(0, DEFAULT_LANG)

    @property
    def languages(self) -> abc.Iterable[str]:
        return iter(self._langs)

    @property
    def current(self) -> str:
        return self._translation["language_name"]

    def set_language(self, language: str):
        if language not in self._langs:
            raise ValueError("Unrecognized language")
        elif self._translation["language_name"] == language:
            # same language as loaded selected
            return
        elif language == DEFAULT_LANG:
            # default language selected - use the memory value
            self._translation = default_translation.copy()
        else:
            source = self._language_files[language]
            if isinstance(source, Path):
                self._translation = json_load(source, default_translation)
            else:
                with zipfile.ZipFile(LANG_ARCHIVE) as archive:
                    loaded = json.loads(archive.read(source))
                merge_json(loaded, default_translation)
                self._translation = cast(Translation, loaded)
            if "language_name" in self._translation:
                raise ValueError("Translations cannot define 'language_name'")
        self._translation["language_name"] = language

    def __call__(self, *path: str) -> str:
        if not path:
            raise ValueError("Language path expected")
        v: Any = self._translation
        try:
            for key in path:
                v = v[key]
        except KeyError:
            # this can only really happen for the default translation
            raise MinerException(
                f"{self.current} translation is missing the '{' -> '.join(path)}' translation key"
            )
        return v


_ = Translator()
