from __future__ import annotations

import math
import logging
from collections import abc
from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING

from constants import URLType
from exceptions import LoginException, RequestException
from translate import _
from utils import Game, timestamp

if TYPE_CHECKING:
    from channel import Channel
    from constants import JsonType
    from kick import Kick


logger = logging.getLogger("KickDrops")


def _image_url(value: str | None) -> URLType:
    if not value:
        return URLType("https://ext.kick.com/drops/organization/kickdrops.png")
    if value.startswith(("http://", "https://")):
        return URLType(value)
    return URLType(f"https://ext.kick.com/{value.lstrip('/')}")


def _campaign_game(data: JsonType) -> Game:
    category = data.get("category")
    if category:
        return Game(category)
    # Channel-specific campaigns do not always contain category metadata. Give each
    # campaign a stable synthetic game so it can still be prioritized independently.
    synthetic_id = -int.from_bytes(sha256(data["id"].encode()).digest()[:4], "big")
    return Game({"id": synthetic_id, "name": data["name"], "slug": data["id"].lower()})


class Benefit:
    __slots__ = ("id", "name", "image_url")

    def __init__(self, data: JsonType):
        self.id = str(data["id"])
        self.name = str(data.get("name") or "Kick Drop")
        self.image_url = _image_url(data.get("image_url"))


class TimedDrop:
    def __init__(
        self,
        campaign: DropsCampaign,
        data: JsonType,
        progress_data: JsonType | None = None,
    ):
        self._kick = campaign._kick
        self.campaign = campaign
        self.id = str(data["id"])
        self.name = str(data.get("name") or "Kick Drop")
        self.benefits = [Benefit(data)]
        self.starts_at = campaign.starts_at
        self.ends_at = campaign.ends_at
        self.required_minutes = max(0, int(data.get("required_units") or 0))
        self.real_current_minutes = 0
        self.extra_current_minutes = 0
        self.is_claimed = False
        self._apply_progress(progress_data or {})

    def __repr__(self) -> str:
        return (
            f"Drop({self.name}, {self.current_minutes}/{self.required_minutes}, "
            f"claimed={self.is_claimed})"
        )

    @property
    def current_minutes(self) -> int:
        return min(self.required_minutes, self.real_current_minutes + self.extra_current_minutes)

    @property
    def remaining_minutes(self) -> int:
        return max(0, self.required_minutes - self.current_minutes)

    @property
    def total_required_minutes(self) -> int:
        return self.required_minutes

    @property
    def total_remaining_minutes(self) -> int:
        return self.remaining_minutes

    @property
    def progress(self) -> float:
        if self.required_minutes <= 0:
            return 1.0 if self.is_claimed else 0.0
        return min(1.0, self.current_minutes / self.required_minutes)

    @property
    def availability(self) -> float:
        now = datetime.now(timezone.utc)
        if self.remaining_minutes > 0 and now < self.ends_at:
            return ((self.ends_at - now).total_seconds() / 60) / self.remaining_minutes
        return math.inf

    @property
    def can_claim(self) -> bool:
        return not self.is_claimed and self.progress >= 1.0

    def rewards_text(self, delim: str = ", ") -> str:
        return delim.join(benefit.name for benefit in self.benefits)

    def can_earn(self, channel: Channel | None = None) -> bool:
        return (
            not self.is_claimed
            and self.required_minutes > 0
            and self.progress < 1.0
            and self.campaign.can_earn(channel)
        )

    def _apply_progress(self, data: JsonType) -> bool:
        old_state = (self.real_current_minutes, self.is_claimed)
        self.is_claimed = bool(data.get("claimed", self.is_claimed))
        raw_progress = data.get("progress")
        if raw_progress is not None:
            try:
                progress = float(raw_progress)
            except (TypeError, ValueError):
                progress = 0.0
            if progress <= 1.0:
                self.real_current_minutes = round(self.required_minutes * max(0.0, progress))
            else:
                self.real_current_minutes = min(self.required_minutes, round(progress))
        if self.is_claimed:
            self.real_current_minutes = self.required_minutes
        self.extra_current_minutes = 0
        return old_state != (self.real_current_minutes, self.is_claimed)

    def update_progress(self, data: JsonType) -> None:
        if self._apply_progress(data):
            self._kick.gui.inv.update_drop(self)
            if self.campaign.first_drop is self:
                self.display()

    def bump_minutes(self) -> None:
        if self.can_earn(self._kick.watching_channel.get_with_default(None)):
            self.extra_current_minutes = min(
                self.required_minutes - self.real_current_minutes,
                self.extra_current_minutes + 1,
            )
            self._kick.gui.inv.update_drop(self)
            self.display()

    async def claim(self) -> bool:
        if self.is_claimed:
            return True
        if not self.can_claim:
            return False
        try:
            result = await self._kick.claim_reward(self.id, self.campaign.id)
        except LoginException:
            raise
        except RequestException as exc:
            logger.warning("Failed to claim Kick reward %s: %s", self.id, exc)
            return False
        if not result:
            return False
        self.is_claimed = True
        self.real_current_minutes = self.required_minutes
        self.extra_current_minutes = 0
        self._kick.gui.inv.update_drop(self)
        claim_text = (
            f"{self.campaign.game.name}\n"
            f"{self.rewards_text()} "
            f"({self.campaign.claimed_drops}/{self.campaign.total_drops})"
        )
        self._kick.print(_("status", "claimed_drop").format(drop=claim_text.replace("\n", " ")))
        self._kick.gui.tray.notify(claim_text, _("gui", "tray", "notification_title"))
        return True

    def display(self, *, countdown: bool = True, subone: bool = False):
        self._kick.gui.display_drop(self, countdown=countdown, subone=subone)


class DropsCampaign:
    def __init__(
        self,
        kick: Kick,
        data: JsonType,
        progress_data: JsonType | None = None,
    ):
        from channel import Channel

        self._kick = kick
        self.id = str(data["id"])
        self.name = str(data.get("name") or "Kick Campaign")
        self.game = _campaign_game(data)
        self.category_id = (
            int(data["category"]["id"]) if data.get("category") is not None else None
        )
        self.linked = True
        self.link_url = str(data.get("connect_url") or data.get("url") or "https://kick.com/drops")
        self.starts_at = timestamp(data["starts_at"])
        self.ends_at = timestamp(data["ends_at"])
        self._valid = str(data.get("status", "")).lower() != "expired"
        self.allowed_channels = [
            Channel.from_acl(kick, channel_data, campaign_game=self.game)
            for channel_data in (data.get("channels") or [])
        ]

        progress_rewards = {
            str(reward["id"]): reward
            for reward in ((progress_data or {}).get("rewards") or [])
            if reward.get("id") is not None
        }
        self.timed_drops = {
            str(reward["id"]): TimedDrop(
                self,
                reward,
                progress_rewards.get(str(reward["id"])),
            )
            for reward in (data.get("rewards") or [])
            if reward.get("id") is not None
        }
        first_reward = next(iter(self.timed_drops.values()), None)
        category_image = (data.get("category") or {}).get("image_url")
        self.image_url = (
            first_reward.benefits[0].image_url
            if first_reward is not None
            else _image_url(category_image)
        )

    def __repr__(self) -> str:
        return f"Campaign({self.game}, {self.name}, {self.claimed_drops}/{self.total_drops})"

    @property
    def drops(self) -> abc.Iterable[TimedDrop]:
        return self.timed_drops.values()

    @property
    def time_triggers(self) -> set[datetime]:
        return {self.starts_at, self.ends_at}

    @property
    def active(self) -> bool:
        return self._valid and self.starts_at <= datetime.now(timezone.utc) < self.ends_at

    @property
    def upcoming(self) -> bool:
        return self._valid and datetime.now(timezone.utc) < self.starts_at

    @property
    def expired(self) -> bool:
        return not self._valid or self.ends_at <= datetime.now(timezone.utc)

    @property
    def total_drops(self) -> int:
        return len(self.timed_drops)

    @property
    def eligible(self) -> bool:
        return True

    @property
    def finished(self) -> bool:
        return bool(self.timed_drops) and all(drop.is_claimed for drop in self.drops)

    @property
    def claimed_drops(self) -> int:
        return sum(drop.is_claimed for drop in self.drops)

    @property
    def remaining_drops(self) -> int:
        return sum(not drop.is_claimed for drop in self.drops)

    @property
    def required_minutes(self) -> int:
        return max((drop.required_minutes for drop in self.drops), default=0)

    @property
    def remaining_minutes(self) -> int:
        return max((drop.remaining_minutes for drop in self.drops), default=0)

    @property
    def progress(self) -> float:
        if not self.timed_drops:
            return 0.0
        return sum(drop.progress for drop in self.drops) / self.total_drops

    @property
    def availability(self) -> float:
        return min((drop.availability for drop in self.drops), default=math.inf)

    @property
    def first_drop(self) -> TimedDrop | None:
        available = [drop for drop in self.drops if drop.can_earn()]
        return min(available, key=lambda drop: drop.required_minutes, default=None)

    def get_drop(self, drop_id: str) -> TimedDrop | None:
        return self.timed_drops.get(drop_id)

    def can_earn(self, channel: Channel | None = None) -> bool:
        if (
            not self.active
            or self.finished
            or not any(drop.progress < 1.0 and not drop.is_claimed for drop in self.drops)
        ):
            return False
        if channel is None:
            return True
        if self.allowed_channels and channel not in self.allowed_channels:
            return False
        if self.category_id is not None:
            return channel.game is not None and channel.game.id == self.category_id
        return True

    def can_earn_within(self, stamp: datetime) -> bool:
        return (
            self._valid
            and self.ends_at > datetime.now(timezone.utc)
            and self.starts_at < stamp
            and any(drop.progress < 1.0 and not drop.is_claimed for drop in self.drops)
            and bool(self.timed_drops)
        )

    def bump_minutes(self, channel: Channel) -> None:
        if not self.can_earn(channel):
            return
        for drop in self.drops:
            drop.bump_minutes()

    def update_progress(self, data: JsonType) -> None:
        rewards = {
            str(reward["id"]): reward
            for reward in (data.get("rewards") or [])
            if reward.get("id") is not None
        }
        for drop_id, drop in self.timed_drops.items():
            if drop_id in rewards:
                drop.update_progress(rewards[drop_id])
