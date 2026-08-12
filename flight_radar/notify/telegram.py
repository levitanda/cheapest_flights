"""Telegram Bot API sink."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from ..config import Settings
from ..format import render_telegram
from ..geo import Geo
from ..models import Deal

logger = logging.getLogger(__name__)


class TelegramNotifier:
    name = "telegram"

    def __init__(self, settings: Settings, geo: Optional[Geo] = None) -> None:
        self.settings = settings
        self.geo = geo

    def send(self, deal: Deal, booking_url: str) -> bool:
        url = f"https://api.telegram.org/bot{self.settings.telegram_token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": self.settings.telegram_chat_id,
                    "text": render_telegram(deal, booking_url, self.geo),
                    "parse_mode": "HTML",
                    # The preview would be a generic Aviasales card on every
                    # alert, pushing the actual details off the screen.
                    "disable_web_page_preview": True,
                },
                timeout=self.settings.http_timeout,
            )
            if resp.status_code != 200:
                logger.warning("telegram send failed: %s %s", resp.status_code, resp.text[:200])
                return False
            return True
        except requests.RequestException as exc:
            logger.warning("telegram send failed: %s", exc)
            return False
