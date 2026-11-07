from __future__ import annotations

from ..events import MarketEvent


class WSAdapter:
    name = "base"
    ping_interval: float | None = None    # app-level ping (seconds); None = protocol pings only
    max_msgs_per_sec: float = 5.0

    def __init__(self, symbols: list[str], timeframe: str = "1m", url: str | None = None):
        self.symbols, self.timeframe, self.url_override = symbols, timeframe, url

    def connections(self) -> list[tuple[str, list]]:
        """[(url, [subscription messages])] - some venues need more than one socket."""
        raise NotImplementedError

    def ping_message(self):
        return None

    def parse(self, raw: str | bytes) -> list[MarketEvent]:
        raise NotImplementedError

    @staticmethod
    def pair(sym: str, quote_len: int | None = None) -> str:
        return sym
