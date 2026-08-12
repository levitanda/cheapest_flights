"""Notification sinks.

A sink never raises: a broken Telegram token must not abort a scan or lose the
price history that scan collected. Failures are logged and reported through
the return value instead.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

from ..config import Settings
from ..geo import Geo
from ..models import Deal

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    name: str

    def send(self, deal: Deal, booking_url: str) -> bool:
        """Deliver one deal. Returns True on success, never raises."""


def build_notifiers(settings: Settings, geo: Optional[Geo] = None) -> list[Notifier]:
    """Every notifier whose credentials are present, plus the console."""
    from .console import ConsoleNotifier
    from .pushover import PushoverNotifier
    from .telegram import TelegramNotifier

    notifiers: list[Notifier] = []
    if settings.telegram_token and settings.telegram_chat_id:
        notifiers.append(TelegramNotifier(settings, geo))
    if settings.pushover_token and settings.pushover_user:
        notifiers.append(PushoverNotifier(settings, geo))
    if not notifiers:
        logger.warning("no notifier configured — deals will only be printed")
        notifiers.append(ConsoleNotifier(geo))
    return notifiers
