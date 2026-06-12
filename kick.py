from __future__ import annotations

import asyncio
import logging
import random
from collections import OrderedDict, abc, deque
from contextlib import asynccontextmanager, suppress
from copy import copy
from datetime import datetime, timedelta, timezone
from http.cookiejar import Cookie, MozillaCookieJar
from pathlib import Path
from time import time
from typing import Any, Final, NoReturn, TYPE_CHECKING

import aiohttp
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestException

from channel import Channel, Stream
from constants import (
    COOKIES_PATH,
    DUMP_PATH,
    KICK_CLIENT_TOKEN,
    MAX_INT,
    State,
    PriorityMode,
)
from exceptions import ExitRequest, LoginException, RequestException
from gui import GUIManager
from inventory import DropsCampaign
from translate import _
from utils import AwaitableValue, ExponentialBackoff, Game, task_wrapper

if TYPE_CHECKING:
    from constants import JsonType
    from inventory import TimedDrop
    from settings import Settings


logger = logging.getLogger("KickDrops")
api_logger = logging.getLogger("KickDrops.api")
ws_logger = logging.getLogger("KickDrops.websocket")

KICK_URL = "https://kick.com"
KICK_WEB_URL = "https://web.kick.com"
KICK_WS_URL = "https://websockets.kick.com/viewer/v1"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": KICK_URL,
    "Referer": f"{KICK_URL}/",
}


def load_kick_cookies(path: Path) -> list[Cookie]:
    jar = MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    now = time()
    cookies = [
        cookie
        for cookie in jar
        if cookie.domain.lstrip(".").lower().endswith("kick.com")
        and (cookie.expires is None or cookie.expires > now)
    ]
    if not cookies:
        raise LoginException("The selected file does not contain any Kick cookies.")
    if not any(cookie.name == "session_token" and cookie.value for cookie in cookies):
        raise LoginException("The selected file does not contain a valid session_token cookie.")
    return cookies


def save_kick_cookies(cookies: list[Cookie], path: Path = COOKIES_PATH) -> None:
    jar = MozillaCookieJar(str(path))
    for cookie in cookies:
        jar.set_cookie(copy(cookie))
    jar.save(ignore_discard=True, ignore_expires=True)


class _AuthState:
    def __init__(self, kick: Kick):
        self._kick = kick
        self._lock = asyncio.Lock()
        self._logged_in = asyncio.Event()
        self.cookies: list[Cookie] = []
        self.session_token = ""

    def clear(self) -> None:
        self.cookies.clear()
        self.session_token = ""
        self._logged_in.clear()

    def invalidate(self) -> None:
        self.clear()

    def cookie_dict(self) -> dict[str, str]:
        return {cookie.name: cookie.value for cookie in self.cookies}

    async def validate(self) -> None:
        async with self._lock:
            if self._logged_in.is_set():
                return
            login_form = self._kick.gui.login
            candidate = COOKIES_PATH if COOKIES_PATH.exists() else None
            while True:
                if candidate is None:
                    candidate = await login_form.ask_cookie_file()
                try:
                    cookies = load_kick_cookies(candidate)
                    self.cookies = cookies
                    self.session_token = next(
                        cookie.value for cookie in cookies if cookie.name == "session_token"
                    )
                    await self._kick.reset_session()
                    login_form.update(_("gui", "login", "logging_in"), None)
                    await self._kick.get_drop_progress(validate_only=True)
                except (OSError, ValueError, LoginException, RequestException) as exc:
                    logger.warning("Kick cookie validation failed: %s", exc)
                    self.clear()
                    await self._kick.reset_session()
                    self._kick.print(str(exc))
                    candidate = None
                    continue
                save_kick_cookies(cookies)
                login_form.update(_("gui", "login", "logged_in"), "Kick")
                self._logged_in.set()
                return


class Kick:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._state = State.IDLE
        self._state_change = asyncio.Event()
        self.wanted_games: list[Game] = []
        self.inventory: list[DropsCampaign] = []
        self._drops: dict[str, TimedDrop] = {}
        self._campaigns: dict[str, DropsCampaign] = {}
        self._mnt_triggers: deque[datetime] = deque()
        self._session: AsyncSession | None = None
        self._auth_state = _AuthState(self)
        self.gui = GUIManager(self)
        self.channels: OrderedDict[int, Channel] = OrderedDict()
        self.watching_channel: AwaitableValue[Channel] = AwaitableValue()
        self._watching_task: asyncio.Task[None] | None = None
        self._channel_poll_task: asyncio.Task[None] | None = None
        self._mnt_task: asyncio.Task[None] | None = None
        self._watching_restart = asyncio.Event()
        self._closed = False

    async def get_session(self) -> AsyncSession:
        if self._session is None:
            proxy = str(self.settings.proxy) if self.settings.proxy else None
            self._session = AsyncSession(
                impersonate="chrome",
                headers=DEFAULT_HEADERS,
                cookies=self._auth_state.cookie_dict(),
                proxy=proxy,
                timeout=10 * max(1, min(6, self.settings.connection_quality)),
            )
        return self._session

    async def reset_session(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def shutdown(self) -> None:
        self._closed = True
        self.stop_watching()
        for task_name in ("_watching_task", "_channel_poll_task", "_mnt_task"):
            task = getattr(self, task_name)
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                setattr(self, task_name, None)
        await self.reset_session()
        self.channels.clear()
        self.inventory.clear()
        self.gui.channels.clear()
        self.gui.inv.clear()
        self._drops.clear()
        self._campaigns.clear()
        self._auth_state.clear()

    def wait_until_login(self):
        return self._auth_state._logged_in.wait()

    def change_state(self, state: State) -> None:
        if self._state is not State.EXIT:
            self._state = state
        self._state_change.set()

    def state_change(self, state: State):
        return lambda: self.change_state(state)

    def close(self):
        self.change_state(State.EXIT)

    def prevent_close(self):
        self.gui.prevent_close()

    def print(self, message: str):
        self.gui.print(message)

    def save(self, *, force: bool = False) -> None:
        self.gui.save(force=force)
        self.settings.save(force=force)

    async def run(self):
        if self.settings.dump:
            DUMP_PATH.write_text("", encoding="utf8")
        while True:
            try:
                await self._run()
                return
            except LoginException:
                await self.shutdown()
                self._closed = False

    async def _run(self):
        self.gui.start()
        await self.get_auth()
        self._closed = False
        self._watching_task = asyncio.create_task(self._watch_loop())
        self._channel_poll_task = asyncio.create_task(self._channel_poll_loop())
        self.change_state(State.INVENTORY_FETCH)
        full_cleanup = False
        channels: Final[OrderedDict[int, Channel]] = self.channels
        while True:
            if self._state is State.IDLE:
                self.gui.tray.change_icon("idle")
                self.gui.status.update(_("gui", "status", "idle"))
                self.stop_watching()
                self._state_change.clear()
            elif self._state is State.INVENTORY_FETCH:
                self.gui.tray.change_icon("maint")
                await self.fetch_inventory()
                self.gui.set_games({campaign.game for campaign in self.inventory})
                self.save()
                self.change_state(State.GAMES_UPDATE)
            elif self._state is State.GAMES_UPDATE:
                for campaign in self.inventory:
                    for drop in campaign.drops:
                        if drop.can_claim:
                            await drop.claim()
                self._build_wanted_games()
                full_cleanup = True
                self.restart_watching()
                self.change_state(State.CHANNELS_CLEANUP)
            elif self._state is State.CHANNELS_CLEANUP:
                self.gui.status.update(_("gui", "status", "cleanup"))
                if full_cleanup or not self.wanted_games:
                    for channel in list(channels.values()):
                        channel.remove()
                    channels.clear()
                full_cleanup = False
                self.change_state(
                    State.CHANNELS_FETCH if self.wanted_games else State.IDLE
                )
            elif self._state is State.CHANNELS_FETCH:
                self.gui.status.update(_("gui", "status", "gathering"))
                await self._fetch_channels()
                self.change_state(State.CHANNEL_SWITCH)
            elif self._state is State.CHANNEL_SWITCH:
                self.gui.status.update(_("gui", "status", "switching"))
                new_watching = self._select_channel()
                current = self.watching_channel.get_with_default(None)
                if new_watching is not None:
                    self.watch(new_watching)
                    self._state_change.clear()
                elif current is not None and self.can_watch(current):
                    self._state_change.clear()
                else:
                    self.print(_("status", "no_channel"))
                    self.change_state(State.IDLE)
            elif self._state is State.EXIT:
                self.gui.tray.change_icon("pickaxe")
                self.gui.status.update(_("gui", "status", "exiting"))
                return
            await self._state_change.wait()

    def _build_wanted_games(self) -> None:
        self.wanted_games.clear()
        priority_only = self.settings.priority_mode is PriorityMode.PRIORITY_ONLY
        campaigns = list(self.inventory)
        if not priority_only:
            if self.settings.priority_mode is PriorityMode.ENDING_SOONEST:
                campaigns.sort(key=lambda campaign: campaign.ends_at)
            elif self.settings.priority_mode is PriorityMode.LOW_AVBL_FIRST:
                campaigns.sort(key=lambda campaign: campaign.availability)
        campaigns.sort(
            key=lambda campaign: (
                self.settings.priority.index(campaign.game.name)
                if campaign.game.name in self.settings.priority
                else MAX_INT
            )
        )
        next_hour = datetime.now(timezone.utc) + timedelta(hours=1)
        for campaign in campaigns:
            game = campaign.game
            if (
                game not in self.wanted_games
                and game.name not in self.settings.exclude
                and (not priority_only or game.name in self.settings.priority)
                and campaign.can_earn_within(next_hour)
            ):
                self.wanted_games.append(game)

    async def _fetch_channels(self) -> None:
        discovered: dict[int, Channel] = {}
        next_hour = datetime.now(timezone.utc) + timedelta(hours=1)
        category_games: dict[int, Game] = {}
        for campaign in self.inventory:
            if campaign.game not in self.wanted_games or not campaign.can_earn_within(next_hour):
                continue
            if campaign.allowed_channels:
                for channel in campaign.allowed_channels:
                    existing = discovered.get(channel.id)
                    if existing is None:
                        discovered[channel.id] = channel
                    else:
                        existing.acl_based = True
            elif campaign.category_id is not None:
                category_games[campaign.category_id] = campaign.game
        for game in category_games.values():
            for channel in await self.get_live_streams(game):
                discovered.setdefault(channel.id, channel)
        await self.bulk_check_online(
            (channel for channel in discovered.values() if channel.offline),
            notify=False,
        )
        ordered = sorted(discovered.values(), key=self._viewers_key, reverse=True)
        ordered.sort(key=lambda channel: channel.acl_based, reverse=True)
        ordered.sort(key=self.get_priority)
        self.channels.clear()
        self.gui.channels.clear()
        for channel in ordered[:199]:
            self.channels[channel.id] = channel
            channel.display(add=True)

    def get_priority(self, channel: Channel) -> int:
        matching = [
            self.wanted_games.index(campaign.game)
            for campaign in self.inventory
            if campaign.game in self.wanted_games and campaign.can_earn(channel)
        ]
        return min(matching, default=MAX_INT)

    @staticmethod
    def _viewers_key(channel: Channel) -> int:
        return channel.viewers if channel.viewers is not None else -1

    def can_watch(self, channel: Channel) -> bool:
        return channel.online and any(
            campaign.game in self.wanted_games and campaign.can_earn(channel)
            for campaign in self.inventory
        )

    def should_switch(self, channel: Channel) -> bool:
        if not self.can_watch(channel):
            return False
        current = self.watching_channel.get_with_default(None)
        if current is None or not self.can_watch(current):
            return True
        new_priority = self.get_priority(channel)
        old_priority = self.get_priority(current)
        return (
            new_priority < old_priority
            or new_priority == old_priority
            and channel.acl_based > current.acl_based
        )

    def _select_channel(self) -> Channel | None:
        selected = self.gui.channels.get_selection()
        if selected is not None and self.can_watch(selected):
            return selected
        for channel in sorted(self.channels.values(), key=self.get_priority):
            if self.should_switch(channel):
                return channel
        return None

    def watch(self, channel: Channel, *, update_status: bool = True):
        self.gui.tray.change_icon("active")
        self.gui.channels.set_watching(channel)
        self.watching_channel.set(channel)
        self.restart_watching()
        active_campaign = self.get_active_campaign(channel)
        if active_campaign is not None and active_campaign.first_drop is not None:
            active_campaign.first_drop.display(countdown=False, subone=True)
        if update_status:
            status = _("status", "watching").format(channel=channel.name)
            self.print(status)
            self.gui.status.update(status)

    def stop_watching(self):
        self.gui.clear_drop()
        self.watching_channel.clear()
        self.gui.channels.clear_watching()
        self.restart_watching()

    def restart_watching(self):
        self.gui.progress.stop_timer()
        self._watching_restart.set()

    async def _watch_sleep(self, seconds: float) -> bool:
        self._watching_restart.clear()
        try:
            await asyncio.wait_for(self._watching_restart.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    @task_wrapper(critical=True)
    async def _watch_loop(self) -> NoReturn:
        while True:
            channel = await self.watching_channel.get()
            if not channel.online:
                self.stop_watching()
                continue
            try:
                await self._watch_channel(channel)
            except LoginException as exc:
                self.print(str(exc))
                self._auth_state.invalidate()
                await self.reset_session()
                self.gui.login.update(_("gui", "login", "required"), None)
                self.stop_watching()
                self.change_state(State.INVENTORY_FETCH)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                ws_logger.exception("Kick viewer websocket failed: %s", exc)
                self.gui.websockets.update(0, status=_("gui", "websocket", "reconnecting"))
                await asyncio.sleep(5)

    async def _watch_channel(self, channel: Channel) -> None:
        ws_logger.debug("Refreshing channel before watch: %s (%s)", channel.name, channel.id)
        await channel.update_stream()
        if not channel.online or channel.livestream_id is None:
            ws_logger.debug("Channel is no longer watchable: %s", channel.name)
            self.change_state(State.CHANNEL_SWITCH)
            return
        ws_logger.debug("Requesting viewer token for channel %s", channel.id)
        token = await self.get_viewer_token()
        self.gui.websockets.update(0, status=_("gui", "websocket", "connecting"), topics=1)
        ws_logger.debug("Connecting viewer websocket for channel %s", channel.id)
        try:
            async with self.viewer_websocket(token) as websocket:
                ws_logger.debug("Viewer websocket connected for channel %s", channel.id)
                self.gui.websockets.update(
                    0, status=_("gui", "websocket", "connected"), topics=1
                )
                started = time()
                next_watch_event = started + 60
                send_handshake = True
                while self.watching_channel.get_with_default(None) == channel:
                    if send_handshake:
                        ws_logger.debug("Sending channel handshake for %s", channel.id)
                        await websocket.send_json(
                            {
                                "type": "channel_handshake",
                                "data": {"message": {"channelId": channel.id}},
                            }
                        )
                    else:
                        await websocket.send_json({"type": "ping"})
                    send_handshake = not send_handshake
                    with suppress(asyncio.TimeoutError):
                        message = await websocket.receive_json(timeout=0.1)
                        ws_logger.debug("Kick viewer websocket received: %s", message)
                    now = time()
                    if now >= next_watch_event:
                        ws_logger.debug(
                            "Sending watch event for channel %s, livestream %s",
                            channel.id,
                            channel.livestream_id,
                        )
                        await websocket.send_json(
                            {
                                "type": "user_event",
                                "data": {
                                    "message": {
                                        "name": "tracking.user.watch.livestream",
                                        "channel_id": channel.id,
                                        "livestream_id": int(channel.livestream_id),
                                    }
                                },
                            }
                        )
                        next_watch_event = now + 60
                        await self.refresh_progress()
                        active = self.get_active_campaign(channel)
                        if active is not None and active.first_drop is not None:
                            active.first_drop.display()
                    if await self._watch_sleep(random.uniform(13, 18)):
                        return
                    if time() - started >= 60:
                        started = time()
                        if not await channel.update_stream():
                            self.change_state(State.CHANNEL_SWITCH)
                            return
        finally:
            self.gui.websockets.update(0, status=_("gui", "websocket", "disconnected"), topics=0)

    @asynccontextmanager
    async def viewer_websocket(self, token: str):
        proxy = str(self.settings.proxy) if self.settings.proxy else None
        timeout = 10 * max(1, min(6, self.settings.connection_quality))
        async with aiohttp.ClientSession(
            headers=DEFAULT_HEADERS,
            cookies=self._auth_state.cookie_dict(),
        ) as session:
            async with session.ws_connect(
                f"wss://websockets.kick.com/viewer/v1/connect?token={token}",
                origin=KICK_URL,
                proxy=proxy,
                timeout=timeout,
            ) as websocket:
                yield websocket

    @task_wrapper
    async def _channel_poll_loop(self) -> NoReturn:
        while True:
            await asyncio.sleep(60)
            if not self.channels:
                continue
            await self.bulk_check_online(list(self.channels.values()))
            if any(self.should_switch(channel) for channel in self.channels.values()):
                self.change_state(State.CHANNEL_SWITCH)

    def on_channel_update(
        self,
        channel: Channel,
        stream_before: Stream | None,
        stream_after: Stream | None,
    ):
        current = self.watching_channel.get_with_default(None)
        if current == channel and not self.can_watch(channel):
            self.change_state(State.CHANNEL_SWITCH)
        elif stream_after is not None and self.should_switch(channel):
            self.watch(channel)
        channel.display()

    async def get_auth(self) -> _AuthState:
        await self._auth_state.validate()
        return self._auth_state

    def _auth_headers(self) -> dict[str, str]:
        return {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {self._auth_state.session_token}",
            "X-Client-Token": KICK_CLIENT_TOKEN,
        }

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        auth: bool = False,
        **kwargs: Any,
    ) -> JsonType:
        session = await self.get_session()
        backoff = ExponentialBackoff(maximum=60)
        for delay in backoff:
            if self.gui.close_requested:
                raise ExitRequest()
            headers = dict(kwargs.pop("headers", {}))
            headers = {**(self._auth_headers() if auth else DEFAULT_HEADERS), **headers}
            try:
                response = await session.request(method, url, headers=headers, **kwargs)
            except CurlRequestException:
                await asyncio.sleep(delay)
                continue
            api_logger.debug("%s %s -> %s", method, url, response.status_code)
            if auth and response.status_code in (401, 403):
                raise LoginException(
                    "Kick rejected the saved session. Import a fresh cookies.txt file."
                )
            if response.status_code >= 500:
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 400:
                raise RequestException(
                    f"Kick request failed ({response.status_code}): {url}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise RequestException(f"Kick returned invalid JSON: {url}") from exc
        raise RequestException(f"Kick request retry limit reached: {url}")

    async def request_bytes(self, url: str) -> tuple[int, bytes]:
        session = await self.get_session()
        response = await session.get(url, headers=DEFAULT_HEADERS)
        return response.status_code, response.content

    async def get_campaigns(self) -> list[JsonType]:
        data = await self.request_json("GET", f"{KICK_WEB_URL}/api/v1/drops/campaigns")
        return list(data.get("data") or [])

    async def get_drop_progress(self, *, validate_only: bool = False) -> JsonType:
        data = await self.request_json(
            "GET",
            f"{KICK_WEB_URL}/api/v1/drops/progress",
            auth=True,
        )
        if validate_only and not isinstance(data.get("data"), list):
            raise LoginException("Kick returned an unexpected drops progress response.")
        return data

    async def claim_reward(self, reward_id: str, campaign_id: str) -> bool:
        data = await self.request_json(
            "POST",
            f"{KICK_WEB_URL}/api/v1/drops/claim",
            auth=True,
            json={"reward_id": reward_id, "campaign_id": campaign_id},
        )
        return data.get("message") == "Success"

    async def get_viewer_token(self) -> str:
        data = await self.request_json(
            "GET",
            f"{KICK_WS_URL}/token",
            auth=True,
        )
        token = (data.get("data") or {}).get("token")
        if not token:
            raise RequestException("Kick did not return a viewer websocket token.")
        return str(token)

    async def get_channel(self, slug: str) -> JsonType:
        return await self.request_json("GET", f"{KICK_URL}/api/v2/channels/{slug}")

    async def get_live_streams(self, game: Game, *, limit: int = 20) -> set[Channel]:
        data = await self.request_json(
            "GET",
            f"{KICK_WEB_URL}/api/v1/livestreams",
            params={
                "limit": limit,
                "sort": "viewer_count_desc",
                "category_id": game.id,
            },
        )
        streams = (data.get("data") or {}).get("livestreams") or []
        return {Channel.from_directory(self, stream) for stream in streams}

    async def bulk_check_online(
        self,
        channels: abc.Iterable[Channel],
        *,
        notify: bool = True,
    ):
        channel_list = list(channels)
        if not channel_list:
            return
        results = await asyncio.gather(
            *(channel.get_stream() for channel in channel_list),
            return_exceptions=True,
        )
        for channel, result in zip(channel_list, results):
            if isinstance(result, Exception):
                logger.warning("Failed to refresh %s: %s", channel.name, result)
                continue
            old_stream = channel._stream
            channel._stream = result
            if notify:
                self.on_channel_update(channel, old_stream, result)

    async def fetch_inventory(self) -> None:
        await self.get_auth()
        self.gui.status.update(_("gui", "status", "fetching_inventory"))
        campaigns_data, progress_payload = await asyncio.gather(
            self.get_campaigns(),
            self.get_drop_progress(),
        )
        progress_campaigns = {
            str(campaign["id"]): campaign
            for campaign in (progress_payload.get("data") or [])
            if campaign.get("id") is not None
        }
        campaigns = [
            DropsCampaign(
                self,
                campaign_data,
                progress_campaigns.get(str(campaign_data["id"])),
            )
            for campaign_data in campaigns_data
            if campaign_data.get("id") is not None and campaign_data.get("rewards")
        ]
        campaigns.sort(key=lambda campaign: campaign.active, reverse=True)
        campaigns.sort(key=lambda campaign: campaign.upcoming and campaign.starts_at or campaign.ends_at)
        self.inventory.clear()
        self._campaigns.clear()
        self._drops.clear()
        self.gui.inv.clear()
        self._mnt_triggers.clear()
        now = datetime.now(timezone.utc)
        for campaign in campaigns:
            self.inventory.append(campaign)
            self._campaigns[campaign.id] = campaign
            self._drops.update({drop.id: drop for drop in campaign.drops})
            for trigger in campaign.time_triggers:
                if trigger > now:
                    self._mnt_triggers.append(trigger)
        self._mnt_triggers = deque(sorted(set(self._mnt_triggers)))
        for index, campaign in enumerate(campaigns, start=1):
            self.gui.status.update(
                _("gui", "status", "adding_campaigns").format(
                    counter=f"({index}/{len(campaigns)})"
                )
            )
            await self.gui.inv.add_campaign(campaign)
        if self._mnt_task is not None:
            self._mnt_task.cancel()
        self._mnt_task = asyncio.create_task(self._maintenance_task())

    async def refresh_progress(self) -> None:
        payload = await self.get_drop_progress()
        changed_to_claimable = False
        for campaign_data in payload.get("data") or []:
            campaign = self._campaigns.get(str(campaign_data.get("id")))
            if campaign is None:
                continue
            campaign.update_progress(campaign_data)
            for drop in campaign.drops:
                if drop.can_claim:
                    changed_to_claimable = await drop.claim() or changed_to_claimable
        if changed_to_claimable:
            self.change_state(State.INVENTORY_FETCH)

    def get_active_campaign(self, channel: Channel | None = None) -> DropsCampaign | None:
        candidates = [
            campaign
            for campaign in self.inventory
            if campaign.game in self.wanted_games and campaign.can_earn(channel)
        ]
        return min(candidates, key=lambda campaign: campaign.remaining_minutes, default=None)

    @task_wrapper(critical=True)
    async def _maintenance_task(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            next_reload = now + timedelta(hours=1)
            next_trigger = min(
                (trigger for trigger in self._mnt_triggers if trigger > now),
                default=next_reload,
            )
            await asyncio.sleep(max(1, (min(next_trigger, next_reload) - now).total_seconds()))
            self.change_state(State.INVENTORY_FETCH)
            return
