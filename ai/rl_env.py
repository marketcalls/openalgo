"""Custom Gymnasium Trading Environment for RL agents.

Actions: 0=HOLD, 1=BUY, 2=SELL
State:   last 20 candles of [open,high,low,close,volume] (normalised) + [position, cash_ratio]
Reward:  clipped log-return of portfolio value (numerically stable)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

LOOKBACK = 20
N_FEATURES = 5  # open, high, low, close, volume


def _normalise_window(window: np.ndarray) -> np.ndarray:
    """Normalise OHLCV window using per-column log-return approach.

    Each column is expressed as (value / first_value - 1), which is the
    percentage change relative to the start of the window.  Results are
    clipped to [-10, 10] to bound the observation space.
    """
    out = np.zeros_like(window, dtype=np.float32)
    for col in range(window.shape[1]):
        col_vals = window[:, col].astype(np.float64)
        first = col_vals[0] if col_vals[0] != 0.0 else 1.0
        out[:, col] = np.clip((col_vals / first - 1.0), -10.0, 10.0).astype(np.float32)
    return out


class TradingEnv(gym.Env):
    """Single-asset, discrete-action trading environment.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame with columns: open, high, low, close, volume.
        Must have at least LOOKBACK + 1 rows.
    initial_cash : float
        Starting capital in currency units.
    lot_size : int
        Minimum tradeable unit.  All BUY orders are rounded down to the
        nearest multiple of lot_size.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        df: pd.DataFrame,
        initial_cash: float = 100_000.0,
        lot_size: int = 1,
    ):
        super().__init__()
        self.df = df.reset_index(drop=True)
        self.initial_cash = float(initial_cash)
        self.lot_size = max(1, int(lot_size))

        n_obs = LOOKBACK * N_FEATURES + 2  # + position_flag + cash_ratio
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(n_obs,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0=HOLD, 1=BUY, 2=SELL

        # Internal state (initialised properly in reset())
        self._cursor: int = LOOKBACK
        self._cash: float = self.initial_cash
        self._shares: int = 0
        self._prev_value: float = self.initial_cash

    # ------------------------------------------------------------------
    # Gymnasium interface
    # ------------------------------------------------------------------

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._cursor = LOOKBACK
        self._cash = self.initial_cash
        self._shares = 0
        self._prev_value = self.initial_cash
        return self._obs(), {}

    def step(self, action: int):
        price = float(self.df.loc[self._cursor, "close"])

        if action == 1 and self._shares == 0:  # BUY
            shares_available = int(self._cash // price)
            # Enforce lot-size: round down to the nearest lot
            shares_available = (shares_available // self.lot_size) * self.lot_size
            if shares_available > 0:
                self._shares = shares_available
                self._cash -= self._shares * price

        elif action == 2 and self._shares > 0:  # SELL
            self._cash += self._shares * price
            self._shares = 0

        # Advance cursor
        self._cursor += 1
        portfolio = self._cash + self._shares * price
        reward = self._compute_reward(portfolio)
        self._prev_value = portfolio

        terminated = self._cursor >= len(self.df)
        info = {
            "portfolio_value": portfolio,
            "shares": self._shares,
            "cash": self._cash,
        }

        if terminated:
            return self._obs(clamp=True), reward, True, False, info
        return self._obs(), reward, False, False, info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_reward(self, portfolio: float) -> float:
        """Clipped log-return reward — numerically stable.

        Uses a clipped ratio so that log() never receives a value near
        zero or extremely large, preventing NaN / inf rewards.
        """
        if portfolio <= 0:
            return -10.0
        ratio = np.clip(portfolio / max(self._prev_value, 1.0), 0.01, 100.0)
        return float(np.log(ratio))

    def _obs(self, clamp: bool = False) -> np.ndarray:
        """Build the flat observation vector.

        Parameters
        ----------
        clamp : bool
            When True (at episode end) use the last valid index rather
            than reading past the end of the DataFrame.
        """
        idx = min(self._cursor, len(self.df) - 1) if clamp else self._cursor
        window = (
            self.df.iloc[idx - LOOKBACK: idx][
                ["open", "high", "low", "close", "volume"]
            ].values
        )
        norm_window = _normalise_window(window.astype(np.float32))

        price = float(self.df.loc[min(idx, len(self.df) - 1), "close"])
        total = self._cash + self._shares * price
        position = float(self._shares > 0)
        cash_ratio = float(self._cash / (total + 1e-9))

        return np.append(norm_window.flatten(), [position, cash_ratio]).astype(np.float32)
