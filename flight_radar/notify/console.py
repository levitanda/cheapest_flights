"""Console sink — the default for dry runs and for an unconfigured install."""

from __future__ import annotations

from typing import Optional

from ..format import render_plain
from ..geo import Geo
from ..models import Deal


class ConsoleNotifier:
    name = "console"

    def __init__(self, geo: Optional[Geo] = None) -> None:
        self.geo = geo

    def send(self, deal: Deal, booking_url: str) -> bool:
        print("\n" + "─" * 60)
        print(render_plain(deal, booking_url, self.geo))
        return True
