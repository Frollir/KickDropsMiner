from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from http.cookiejar import Cookie, MozillaCookieJar
from pathlib import Path
from types import SimpleNamespace

from exceptions import LoginException
from inventory import DropsCampaign
from kick import load_kick_cookies, save_kick_cookies


def make_cookie(
    name: str,
    value: str,
    *,
    domain: str = ".kick.com",
    expires: int | None = None,
) -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=expires,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


class DummyChannels:
    pass


class DummyKick:
    def __init__(self):
        self.gui = SimpleNamespace(channels=DummyChannels())


def campaign_data(*, category=True, channels=None):
    now = datetime.now(timezone.utc)
    data = {
        "id": "01TESTCAMPAIGN",
        "name": "Test Campaign",
        "status": "active",
        "starts_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "ends_at": (now + timedelta(hours=6)).isoformat().replace("+00:00", "Z"),
        "connect_url": "https://kick.com/drops",
        "channels": channels or [],
        "rewards": [
            {
                "id": "reward-1",
                "name": "First Reward",
                "image_url": "drops/reward-image/first.png",
                "required_units": 30,
            },
            {
                "id": "reward-2",
                "name": "Second Reward",
                "image_url": "drops/reward-image/second.png",
                "required_units": 60,
            },
        ],
    }
    if category:
        data["category"] = {"id": 13, "name": "Rust", "slug": "rust"}
    return data


class CookieTests(unittest.TestCase):
    def test_round_trip_filters_non_kick_cookies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "cookies.txt")
            save_kick_cookies(
                [
                    make_cookie("session_token", "secret"),
                    make_cookie("kick_cookie", "value", domain="web.kick.com"),
                    make_cookie("other", "ignored", domain=".example.com"),
                ],
                path,
            )

            cookies = load_kick_cookies(path)

            self.assertEqual(
                {cookie.name for cookie in cookies},
                {"session_token", "kick_cookie"},
            )

    def test_missing_session_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "cookies.txt")
            save_kick_cookies([make_cookie("kick_cookie", "value")], path)

            with self.assertRaises(LoginException):
                load_kick_cookies(path)

    def test_expired_session_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "cookies.txt")
            jar = MozillaCookieJar(str(path))
            jar.set_cookie(make_cookie("session_token", "old", expires=1))
            jar.save(ignore_discard=True, ignore_expires=True)

            with self.assertRaises(LoginException):
                load_kick_cookies(path)


class CampaignTests(unittest.TestCase):
    def test_category_campaign_maps_progress(self):
        progress = {
            "rewards": [
                {"id": "reward-1", "progress": 1, "claimed": True},
                {"id": "reward-2", "progress": 0.5, "claimed": False},
            ]
        }

        campaign = DropsCampaign(DummyKick(), campaign_data(), progress)

        self.assertEqual(campaign.game.name, "Rust")
        self.assertEqual(campaign.claimed_drops, 1)
        self.assertEqual(campaign.get_drop("reward-2").current_minutes, 30)
        self.assertEqual(campaign.remaining_minutes, 30)

    def test_channel_campaign_gets_stable_synthetic_game(self):
        channels = [
            {
                "id": 123,
                "slug": "streamer",
                "user": {"username": "Streamer"},
            }
        ]
        first = DropsCampaign(
            DummyKick(),
            campaign_data(category=False, channels=channels),
        )
        second = DropsCampaign(
            DummyKick(),
            campaign_data(category=False, channels=channels),
        )

        self.assertIsNone(first.category_id)
        self.assertEqual(first.game.id, second.game.id)
        self.assertEqual(first.game.name, "Test Campaign")
        self.assertEqual(first.allowed_channels[0].login, "streamer")

    def test_completed_reward_is_claimable(self):
        progress = {
            "rewards": [
                {"id": "reward-1", "progress": 1, "claimed": False},
            ]
        }

        campaign = DropsCampaign(DummyKick(), campaign_data(), progress)

        self.assertTrue(campaign.get_drop("reward-1").can_claim)


if __name__ == "__main__":
    unittest.main()
