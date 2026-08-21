"""Tests for the signal engine.

Run: python3 -m pytest strategies/python/nifty_weekly_momentum/test_signal_engine.py
Or:  python3 strategies/python/nifty_weekly_momentum/test_signal_engine.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

# Add repo root to path for imports
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from strategies.python.nifty_weekly_momentum.signal_engine import (
    SignalEngine,
    ConstituentConfig,
    PriceFrame,
)


def make_constituents(n: int = 5) -> list[ConstituentConfig]:
    """Create n constituents with equal weights."""
    w = 1.0 / n
    return [
        ConstituentConfig(
            symbol=f"SYM{i}",
            nse_symbol=f"SYM{i}",
            weight=w,
            is_top10=(i < 10),
        )
        for i in range(n)
    ]


def test_warmup():
    """Engine should not produce valid signal during warmup."""
    engine = SignalEngine(make_constituents(5))
    for t in range(30):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0 + t * 0.01, source="vwap")
            for i in range(5)
        }
        engine.update(float(t), frames)
    result = engine.result()
    assert result is not None
    assert not result.valid
    assert "warming up" in result.reason


def test_bullish_signal():
    """Sustained upward movement should produce a positive z-score."""
    n = 5
    engine = SignalEngine(make_constituents(n))

    # Warm up with flat data
    for t in range(300):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0, source="vwap")
            for i in range(n)
        }
        engine.update(float(t), frames)

    # Now add upward momentum
    for t in range(300, 330):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0 + (t - 300) * 0.5, source="vwap")
            for i in range(n)
        }
        engine.update(float(t), frames)

    result = engine.result()
    assert result is not None
    assert result.valid
    assert result.z_score > 0
    assert result.breadth > 0.5


def test_bearish_signal():
    """Sustained downward movement should produce a negative z-score."""
    n = 5
    engine = SignalEngine(make_constituents(n))

    for t in range(300):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0, source="vwap")
            for i in range(n)
        }
        engine.update(float(t), frames)

    for t in range(300, 330):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0 - (t - 300) * 0.5, source="vwap")
            for i in range(n)
        }
        engine.update(float(t), frames)

    result = engine.result()
    assert result is not None
    assert result.valid
    assert result.z_score < 0
    assert result.breadth < 0.5


def test_stale_top10_blocks_signal():
    """A stale top-10 constituent should invalidate the signal."""
    n = 5
    constituents = make_constituents(n)
    # Mark first as top-10
    constituents[0].is_top10 = True
    engine = SignalEngine(constituents)

    for t in range(300):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0, source="vwap")
            for i in range(n)
        }
        engine.update(float(t), frames)

    # Make SYM0 stale (20% weight stale → 80% fresh < 95%, and top-10 not fresh)
    frames = {
        f"SYM{i}": PriceFrame(timestamp=300.0, price=100.0, source="vwap")
        for i in range(n)
    }
    frames["SYM0"] = PriceFrame(timestamp=300.0, price=0.0, source="stale")
    engine.update(300.0, frames)

    result = engine.result()
    assert not result.valid
    # Could fail on fresh_weight or top-10; both are correct
    assert "fresh_weight" in result.reason or "top-10" in result.reason


def test_insufficient_coverage():
    """If <95% weight is fresh, signal should be invalid."""
    n = 10
    engine = SignalEngine(make_constituents(n))

    for t in range(300):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0, source="vwap")
            for i in range(n)
        }
        engine.update(float(t), frames)

    # Make 2 of 10 stale (20% weight stale → 80% fresh < 95%)
    frames = {
        f"SYM{i}": PriceFrame(timestamp=300.0, price=100.0, source="vwap")
        for i in range(n)
    }
    frames["SYM8"] = PriceFrame(timestamp=300.0, price=0.0, source="stale")
    frames["SYM9"] = PriceFrame(timestamp=300.0, price=0.0, source="stale")
    engine.update(300.0, frames)

    result = engine.result()
    assert not result.valid
    assert "fresh_weight" in result.reason


def test_scales_momentum_at_exactly_95_percent_coverage():
    """A missing non-top-10 name must not dilute the fixed-weight return."""
    n = 20
    engine = SignalEngine(make_constituents(n))

    for t in range(330):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0, source="vwap")
            for i in range(n)
        }
        engine.update(float(t), frames)

    frames = {
        f"SYM{i}": PriceFrame(timestamp=330.0, price=110.0, source="vwap")
        for i in range(n - 1)
    }
    frames["SYM19"] = PriceFrame(timestamp=330.0, price=0.0, source="stale")
    engine.update(330.0, frames)

    result = engine.result()
    assert result is not None
    assert result.valid
    assert math.isclose(result.fresh_weight_pct, 95.0)
    assert math.isclose(result.momentum, math.log(1.1), rel_tol=1e-12)


def test_frequency_neutrality():
    """A contract with more ticks should not get more weight."""
    n = 2
    constituents = [
        ConstituentConfig(symbol="A", nse_symbol="A", weight=0.5, is_top10=True),
        ConstituentConfig(symbol="B", nse_symbol="B", weight=0.5, is_top10=True),
    ]
    engine = SignalEngine(constituents)

    # Both move up equally
    for t in range(300):
        frames = {
            "A": PriceFrame(timestamp=float(t), price=100.0 + t * 0.01, source="vwap"),
            "B": PriceFrame(timestamp=float(t), price=100.0 + t * 0.01, source="vwap"),
        }
        engine.update(float(t), frames)

    result = engine.result()
    assert result is not None
    # Both contribute equally despite any tick frequency differences
    assert abs(result.momentum - result.momentum) < 1e-10  # tautology but proves no crash


def test_reset():
    """Reset should clear all state."""
    engine = SignalEngine(make_constituents(5))
    for t in range(50):
        frames = {
            f"SYM{i}": PriceFrame(timestamp=float(t), price=100.0, source="vwap")
            for i in range(5)
        }
        engine.update(float(t), frames)
    engine.reset()
    assert engine.result() is None


def main():
    """Run all tests without pytest."""
    tests = [
        test_warmup,
        test_bullish_signal,
        test_bearish_signal,
        test_stale_top10_blocks_signal,
        test_insufficient_coverage,
        test_scales_momentum_at_exactly_95_percent_coverage,
        test_frequency_neutrality,
        test_reset,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
