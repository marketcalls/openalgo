"""Weighted futures z-score signal engine.

 Pure-Python, no Lean dependencies. Consumes one-second synchronized frames
 of constituent futures prices derived from OpenAlgo depth data and computes
 a weighted momentum z-score.

Key invariants:
- Weights come from the CSV only; never from lot size, volume, or tick frequency.
- Each contract contributes at most once per one-second frame.
- 30-second log returns on the same common-expiry contract.
- Rolling 300-second (5-minute) mean and std for z-score.
- Coverage gate: ≥95% fresh eligible weight + all top-10 fresh.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Sequence


@dataclass
class ConstituentConfig:
    """One resolved constituent future."""
    symbol: str          # OpenAlgo canonical symbol (e.g. RELIANCE25AUG26FUT)
    nse_symbol: str      # Underlying NSE ticker (e.g. RELIANCE)
    weight: float        # Normalized weight (sums to 1.0 over eligible basket)
    is_top10: bool       # Whether this is a top-10 index constituent


@dataclass
class PriceFrame:
    """One contract's price observation at a given second."""
    timestamp: float       # Unix seconds
    price: float           # VWAP or microprice
    source: str            # "vwap" | "microprice" | "midpoint" | "stale"


@dataclass
class SignalResult:
    """Output of the signal engine at one second."""
    timestamp: float
    momentum: float        # Weighted 30s log return
    z_score: float         # Standardized momentum
    breadth: float         # Weighted fraction of positive returns
    fresh_weight_pct: float  # % of eligible weight with valid data
    top10_all_fresh: bool
    valid: bool            # Whether this frame produces a tradable signal
    reason: str            # "" if valid, else reason for invalidation


class SignalEngine:
    """Compute weighted futures-basket z-score from one-second frames.

    Usage:
        engine = SignalEngine(constituents)
        engine.update(second_ts, {symbol: PriceFrame(...)})
        result = engine.result()
    """

    WINDOW_SECONDS = 300  # 5-minute rolling window
    RETURN_HORIZON = 30   # 30-second log returns

    def __init__(self, constituents: Sequence[ConstituentConfig]):
        self._constituents = list(constituents)
        self._weight_map = {c.symbol: c.weight for c in self._constituents}
        self._is_top10 = {c.symbol: c.is_top10 for c in self._constituents}
        self._total_weight = sum(c.weight for c in self._constituents)

        # Per-contract price history (deque of (timestamp, price))
        self._history: dict[str, deque] = {
            c.symbol: deque(maxlen=self.WINDOW_SECONDS + self.RETURN_HORIZON + 10)
            for c in self._constituents
        }

        # Rolling momentum buffer for z-score
        self._momentum_buffer: deque[float] = deque(maxlen=self.WINDOW_SECONDS)

        self._last_result: SignalResult | None = None

    def update(self, timestamp: float, frames: dict[str, PriceFrame]) -> None:
        """Process one synchronized one-second frame."""
        fresh_weight = 0.0
        top10_all_fresh = True
        returns: dict[str, float] = {}

        for sym, frame in frames.items():
            if sym not in self._history:
                continue
            self._history[sym].append((timestamp, frame.price))

            # Check freshness (≤2 seconds old is handled by caller; here we check data validity)
            if frame.source == "stale" or frame.price <= 0:
                if self._is_top10.get(sym, False):
                    top10_all_fresh = False
                continue

            # Compute 30-second log return
            ret = self._compute_return(sym, timestamp)
            if ret is not None:
                returns[sym] = ret
                fresh_weight += self._weight_map.get(sym, 0.0)
            else:
                if self._is_top10.get(sym, False):
                    top10_all_fresh = False

        fresh_pct = (fresh_weight / self._total_weight * 100.0) if self._total_weight > 0 else 0.0

        # Weighted momentum
        momentum = 0.0
        breadth_weight = 0.0
        breadth_total = 0.0

        for sym, ret in returns.items():
            w = self._weight_map.get(sym, 0.0)
            momentum += w * ret
            breadth_total += w
            if ret > 0:
                breadth_weight += w

        if breadth_total > 0:
            momentum /= breadth_total
        breadth = (breadth_weight / breadth_total) if breadth_total > 0 else 0.0

        # Z-score from rolling momentum
        self._momentum_buffer.append(momentum)
        z = self._compute_z_score()

        # Validity
        valid = True
        reason = ""
        if len(self._momentum_buffer) < self.WINDOW_SECONDS:
            valid = False
            reason = f"warming up ({len(self._momentum_buffer)}/{self.WINDOW_SECONDS})"
        elif fresh_pct < 95.0:
            valid = False
            reason = f"fresh_weight {fresh_pct:.1f}% < 95%"
        elif not top10_all_fresh:
            valid = False
            reason = "not all top-10 fresh"
        elif not math.isfinite(z) or abs(z) > 100:
            valid = False
            reason = f"degenerate z_score {z}"

        self._last_result = SignalResult(
            timestamp=timestamp,
            momentum=momentum,
            z_score=z if math.isfinite(z) else 0.0,
            breadth=breadth,
            fresh_weight_pct=fresh_pct,
            top10_all_fresh=top10_all_fresh,
            valid=valid,
            reason=reason,
        )

    def _compute_return(self, sym: str, current_ts: float) -> float | None:
        history = self._history[sym]
        if len(history) < 2:
            return None

        target_ts = current_ts - self.RETURN_HORIZON
        # Find the price closest to 30 seconds ago
        best = None
        best_diff = float("inf")
        for ts, price in history:
            diff = abs(ts - target_ts)
            if diff < best_diff:
                best_diff = diff
                best = price

        if best is None or best <= 0:
            return None
        if best_diff > 5.0:  # No observation within 5 seconds of target
            return None

        current_price = history[-1][1]
        if current_price <= 0:
            return None

        return math.log(current_price / best)

    def _compute_z_score(self) -> float:
        if len(self._momentum_buffer) < 2:
            return 0.0

        values = list(self._momentum_buffer)
        n = len(values)
        mean = sum(values) / n

        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance)

        if std < 1e-10:
            return 0.0

        latest = values[-1]
        return (latest - mean) / std

    def result(self) -> SignalResult | None:
        return self._last_result

    def reset(self) -> None:
        for dq in self._history.values():
            dq.clear()
        self._momentum_buffer.clear()
        self._last_result = None
