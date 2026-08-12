"""Pushover sink."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from ..config import Settings
from ..format import render_plain, render_title
from ..geo import Geo
from ..models import TIER_ERROR_FARE, Deal

logger = logging.getLogger(__name__)


class PushoverNotifier:
    name = "pushover"

    def __init__(self, settings: Settings, geo: Optional[Geo] = None) -> None:
        self.settings = settings
        self.geo = geo

    def send(self, deal: Deal, booking_url: str) -> bool:
        try:
            resp = requests.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": self.settings.pushover_token,
                    "user": self.settings.pushover_user,
                    "title": render_title(deal, self.geo)[:250],
                    "message": render_plain(deal, booking_url, self.geo)[:1024],
                    "url": booking_url,
                    "url_title": "Открыть на Aviasales",
                    # Error fares expire within hours, so they are worth
                    # breaking through a quiet-hours setting for.
                    "priority": 1 if deal.tier == TIER_ERROR_FARE else 0,
                },
                timeout=self.settings.http_timeout,
            )
            if resp.status_code != 200:
                logger.warning("pushover send failed: %s %s", resp.status_code, resp.text[:200])
                return False
            return True
        except requests.RequestException as exc:
            logger.warning("pushover send failed: %s", exc)
            return False
