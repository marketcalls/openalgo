"""Tests for the custom Gymnasium TradingEnv.

Covers: reset/obs shape, BUY/HOLD/SELL actions, episode termination,
        zero-cash guard, lot-size enforcement, reward stability, and
        BUY-then-SELL portfolio balance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n: int = 50, price: float = 100.0, volume: float = 1_000_000.0) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame for testing."""
    return pd.DataFrame({
        "open":   np.ones(n) * price,
        "high":   np.ones(n) * (price * 1.05),
        "low":    np.ones(n) * (price * 0.95),
        "close":  np.ones(n) * price,
        "volume": np.ones(n) * volume,
    })


def make_env():
    """Create a default TradingEnv with a 50-bar flat-price DataFrame."""
    from ai.rl_env import TradingEnv
    return TradingEnv(_make_df(), initial_cash=100_000.0)


# ---------------------------------------------------------------------------
# Original 4 tests from the base plan
# ---------------------------------------------------------------------------

def test_env_reset_obs_shape():
    """reset() must return an observation with the expected flat shape."""
    env = make_env()
    obs, info = env.reset()
    # 20 candles × 5 features + 2 scalars (position, cash_ratio)
    assert obs.shape == (20 * 5 + 2,), f"Unexpected shape: {obs.shape}"
    assert obs.dtype == np.float32


def test_env_step_hold():
    """HOLD action (0) must not change shares or trigger termination early."""
    env = make_env()
    env.reset()
    obs, reward, terminated, truncated, info = env.step(0)
    assert env._shares == 0
    assert not terminated
    assert np.isfinite(reward)


def test_env_step_buy():
    """BUY action (1) when no position must allocate shares and reduce cash."""
    env = make_env()
    env.reset()
    initial_cash = env._cash
    env.step(1)  # BUY
    assert env._shares > 0
    assert env._cash < initial_cash


def test_env_episode_terminates():
    """Running through all bars must set terminated=True on the final step."""
    env = make_env()
    env.reset()
    terminated = False
    for _ in range(1000):
        _, _, terminated, _, _ = env.step(0)
        if terminated:
            break
    assert terminated, "Episode never terminated"


# ---------------------------------------------------------------------------
# 4 additional fix-tests
# ---------------------------------------------------------------------------

def test_env_zero_cash_buy_ignored():
    """BUY with insufficient cash (less than 1 share cost) must be ignored."""
    env = make_env()
    env.reset()
    env._cash = 1.0  # far below the 100-per-share price
    obs, reward, _, _, info = env.step(1)  # BUY should be silently ignored
    assert env._shares == 0, "Shares should remain 0 when cash is insufficient"


def test_env_lot_size_enforced():
    """Shares purchased must always be a non-zero multiple of lot_size."""
    from ai.rl_env import TradingEnv

    n = 50
    df = pd.DataFrame({
        "open":   np.ones(n) * 100,
        "high":   np.ones(n) * 105,
        "low":    np.ones(n) * 95,
        "close":  np.ones(n) * 100,
        "volume": np.ones(n) * 1_000_000,
    })
    env = TradingEnv(df, initial_cash=100_000, lot_size=10)
    env.reset()
    env.step(1)  # BUY
    assert env._shares % 10 == 0, (
        f"Shares {env._shares} is not a multiple of lot_size=10"
    )


def test_env_reward_stable_on_flat_prices():
    """Reward must be finite (no NaN / inf) on constant-price data."""
    from ai.rl_env import TradingEnv

    n = 50
    df = pd.DataFrame({
        "open":   np.ones(n) * 100,
        "high":   np.ones(n) * 100,
        "low":    np.ones(n) * 100,
        "close":  np.ones(n) * 100,
        "volume": np.ones(n) * 1_000_000,
    })
    env = TradingEnv(df)
    env.reset()
    for _ in range(10):
        _, reward, done, _, _ = env.step(0)
        assert np.isfinite(reward), f"Reward not finite: {reward}"
        if done:
            break


def test_env_step_buy_sell_balance():
    """After BUY then SELL on flat prices, cash must be >= 95% of initial."""
    env = make_env()
    env.reset()
    initial_cash = env._cash
    env.step(1)   # BUY
    env.step(2)   # SELL
    # On flat (constant) prices there is no slippage — cash == initial_cash
    assert env._cash >= initial_cash * 0.95, (
        f"Cash {env._cash:.2f} fell below 95% of initial {initial_cash:.2f}"
    )


def test_train_ppo_short():
    """Train PPO for 512 steps — just verify it runs without error."""
    from ai.rl_agent import train_rl_agent
    n = 100
    df = pd.DataFrame({
        'open':  np.random.uniform(100, 200, n),
        'high':  np.random.uniform(105, 205, n),
        'low':   np.random.uniform(95, 195, n),
        'close': np.random.uniform(100, 200, n),
        'volume': np.ones(n) * 1_000_000,
    })
    result = train_rl_agent(df, algo="ppo", timesteps=512, symbol="TEST")
    assert result["status"] == "trained"
    assert "model_path" in result
    import os
    assert os.path.exists(result["model_path"])


def test_get_rl_signal_no_model():
    from ai.rl_agent import get_rl_signal
    result = get_rl_signal(symbol="NONEXISTENT_ZZZ", exchange="NSE", api_key="test")
    assert result["status"] in ("no_model", "error")


def test_get_rl_signal_mock(tmp_path, monkeypatch):
    """Train tiny model then get signal via monkeypatched fetch."""
    from ai.rl_agent import train_rl_agent, get_rl_signal
    n = 100
    df = pd.DataFrame({
        'open':  np.linspace(100, 200, n),
        'high':  np.linspace(105, 205, n),
        'low':   np.linspace(95, 195, n),
        'close': np.linspace(100, 200, n),
        'volume': np.ones(n) * 1_000_000,
    })
    train_rl_agent(df, algo="ppo", timesteps=512, symbol="MOCKTEST")

    import ai.rl_agent as module
    monkeypatch.setattr(module, "_fetch_candles", lambda *a, **kw: df)
    result = get_rl_signal(symbol="MOCKTEST", exchange="NSE", api_key="test")
    assert result["signal"] in ("BUY", "SELL", "HOLD")
    assert 0.0 <= result["confidence"] <= 1.0
