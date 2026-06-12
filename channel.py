from __future__ import annotations

import asyncio
from typing import Any, SupportsInt, TYPE_CHECKING

from constants import URLType
from exceptions import RequestException
from utils import Game

if TYPE_CHECKING:
    from constants import JsonType
    from gui import ChannelList
    from kick import Kick


class Stream:
    def __init__(
        self,
        channel: Channel,
        *,
        id: str | int,
        game: JsonType | None,
        viewers: int = 0,
        title: str = "",
    ):
        self.channel = channel
        self.broadcast_id = str(id)
        self.game = Game(game) if game else None
        self.viewers = int(viewers or 0)
        self.title = title
        self.drops_enabled = True

    @classmethod
    def from_directory(cls, channel: Channel, data: JsonType) -> Stream:
        return cls(
            channel,
            id=data["id"],
            game=data.get("category"),
            viewers=data.get("viewer_count", 0),
            title=data.get("title", ""),
        )

    @classmethod
    def from_channel(cls, channel: Channel, data: JsonType) -> Stream | None:
        livestream = data.get("livestream")
        if not livestream or not livestream.get("is_live"):
            return None
        categories = livestream.get("categories") or []
        return cls(
            channel,
            id=livestream["id"],
            game=categories[0] if categories else None,
            viewers=livestream.get("viewer_count", 0),
            title=livestream.get("session_title", ""),
        )


class Channel:
    __slots__ = (
        "_kick",
        "_gui_channels",
        "id",
        "_login",
        "_display_name",
        "_stream",
        "_pending_stream_up",
        "acl_based",
        "campaign_game",
    )

    def __init__(
        self,
        kick: Kick,
        *,
        id: SupportsInt,
        login: str,
        display_name: str | None = None,
        acl_based: bool = False,
        campaign_game: Game | None = None,
    ):
        self._kick = kick
        self._gui_channels: ChannelList = kick.gui.channels
        self.id = int(id)
        self._login = login
        self._display_name = display_name
        self._stream: Stream | None = None
        self._pending_stream_up: asyncio.Task[Any] | None = None
        self.acl_based = acl_based
        self.campaign_game = campaign_game

    @classmethod
    def from_acl(
        cls,
        kick: Kick,
        data: JsonType,
        *,
        campaign_game: Game | None = None,
    ) -> Channel:
        user = data.get("user") or {}
        return cls(
            kick,
            id=data["id"],
            login=data.get("slug") or user.get("username"),
            display_name=user.get("username"),
            acl_based=True,
            campaign_game=campaign_game,
        )

    @classmethod
    def from_directory(cls, kick: Kick, data: JsonType) -> Channel:
        channel_data = data["channel"]
        channel = cls(
            kick,
            id=channel_data["id"],
            login=channel_data.get("slug") or channel_data.get("username"),
            display_name=channel_data.get("username"),
        )
        channel._stream = Stream.from_directory(channel, data)
        return channel

    def __repr__(self) -> str:
        return f"Channel({self.name}, {self.id})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Channel):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return self.id

    @property
    def name(self) -> str:
        return self._display_name or self._login

    @property
    def url(self) -> URLType:
        return URLType(f"https://kick.com/{self._login}")

    @property
    def iid(self) -> str:
        return str(self.id)

    @property
    def online(self) -> bool:
        return self._stream is not None

    @property
    def offline(self) -> bool:
        return self._stream is None and self._pending_stream_up is None

    @property
    def pending_online(self) -> bool:
        return self._stream is None and self._pending_stream_up is not None

    @property
    def game(self) -> Game | None:
        return self._stream.game if self._stream else None

    @property
    def viewers(self) -> int | None:
        return self._stream.viewers if self._stream else None

    @viewers.setter
    def viewers(self, value: int):
        if self._stream:
            self._stream.viewers = value

    @property
    def drops_enabled(self) -> bool:
        return self.online

    @property
    def livestream_id(self) -> str | None:
        return self._stream.broadcast_id if self._stream else None

    def display(self, *, add: bool = False):
        self._gui_channels.display(self, add=add)

    def remove(self):
        if self._pending_stream_up:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
        self._gui_channels.remove(self)

    async def get_stream(self) -> Stream | None:
        try:
            data = await self._kick.get_channel(self._login)
        except RequestException:
            return None
        user = data.get("user") or {}
        self._display_name = user.get("username") or self._display_name
        return Stream.from_channel(self, data)

    async def update_stream(self) -> bool:
        old_stream = self._stream
        self._stream = await self.get_stream()
        self._kick.on_channel_update(self, old_stream, self._stream)
        return self._stream is not None

    def set_offline(self):
        old_stream = self._stream
        self._stream = None
        if old_stream is not None:
            self._kick.on_channel_update(self, old_stream, None)

    @property
    def login(self) -> str:
        return self._login
