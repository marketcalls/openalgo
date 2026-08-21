"""Frequency-neutral one-second sampling for constituent futures depth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from strategies.python.nifty_weekly_momentum.signal_engine import PriceFrame


@dataclass
class _QuoteState:
    timestamp: float
    bid: float
    ask: float
    bid_size: float
    ask_size: float

    @property
    def valid(self) -> bool:
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid


@dataclass
class _TradeAccumulator:
    notional: float = 0.0
    quantity: float = 0.0

    def add(self, price: float, quantity: float) -> None:
        self.notional += price * quantity
        self.quantity += quantity


class FuturesFrameSampler:
    """Build exactly one observation per configured contract per second."""

    def __init__(self, symbols: Iterable[str], max_quote_age_seconds: float = 2.0):
        self._symbols = tuple(symbols)
        self._symbol_set = set(self._symbols)
        self._max_quote_age = max_quote_age_seconds
        self._quotes: dict[str, _QuoteState] = {}
        self._trades: dict[int, dict[str, _TradeAccumulator]] = {}

    def ingest_quote(
        self,
        symbol: str,
        timestamp: float,
        bid: float,
        ask: float,
        bid_size: float,
        ask_size: float,
    ) -> None:
        if symbol not in self._symbol_set:
            return
        self._quotes[symbol] = _QuoteState(timestamp, bid, ask, bid_size, ask_size)

    def ingest_trade(self, symbol: str, timestamp: float, price: float, quantity: float) -> None:
        if symbol not in self._symbol_set or price <= 0 or quantity <= 0:
            return
        bucket = self._trades.setdefault(int(timestamp), {})
        bucket.setdefault(symbol, _TradeAccumulator()).add(price, quantity)

    def build_frame(self, second: int) -> dict[str, PriceFrame]:
        """Build the completed second ending at ``second + 1``."""
        frame_end = float(second + 1)
        trade_bucket = self._trades.pop(second, {})
        frames: dict[str, PriceFrame] = {}

        for symbol in self._symbols:
            quote = self._quotes.get(symbol)
            if quote is None or not quote.valid:
                frames[symbol] = PriceFrame(frame_end, 0.0, "stale")
                continue

            age = frame_end - quote.timestamp
            if age < 0 or age > self._max_quote_age:
                frames[symbol] = PriceFrame(frame_end, 0.0, "stale")
                continue

            trade = trade_bucket.get(symbol)
            if trade is not None and trade.quantity > 0:
                frames[symbol] = PriceFrame(
                    frame_end,
                    trade.notional / trade.quantity,
                    "vwap",
                )
                continue

            if quote.bid_size > 0 and quote.ask_size > 0:
                microprice = (
                    quote.ask * quote.bid_size + quote.bid * quote.ask_size
                ) / (quote.bid_size + quote.ask_size)
                frames[symbol] = PriceFrame(frame_end, microprice, "microprice")
            else:
                frames[symbol] = PriceFrame(frame_end, (quote.bid + quote.ask) / 2.0, "midpoint")

        self._discard_old_trades(second)
        return frames

    def reset(self) -> None:
        self._quotes.clear()
        self._trades.clear()

    def _discard_old_trades(self, completed_second: int) -> None:
        for second in tuple(self._trades):
            if second < completed_second:
                del self._trades[second]