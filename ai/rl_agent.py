"""FinRL-style RL trading agent — train PPO/A2C/DQN, infer BUY/SELL/HOLD signal.

Model artifacts saved to ml/rl_models/{symbol}_{algo}.zip
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from utils.logging import get_logger

logger = get_logger(__name__)

MODEL_DIR = Path(__file__).parent.parent / "ml" / "rl_models"

AlgoName = Literal["ppo", "a2c", "dqn"]


def _get_model_path(symbol: str, algo: str) -> Path:
    return MODEL_DIR / f"{symbol.upper()}_{algo.lower()}.zip"


def _fetch_candles(
    symbol: str,
    exchange: str,
    api_key: str,
    interval: str = "1d",
    limit: int = 500,
) -> pd.DataFrame | None:
    """Fetch OHLCV from OpenAlgo's data bridge (reuses existing fetch_ohlcv)."""
    try:
        from ai.data_bridge import fetch_ohlcv
        result = fetch_ohlcv(symbol=symbol, exchange=exchange, interval=interval, api_key=api_key)
        if not result.success or result.df.empty:
            logger.warning("_fetch_candles: fetch_ohlcv failed for %s — %s", symbol, result.error)
            return None
        df = result.df.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna().tail(limit).reset_index(drop=True)
        return df if len(df) >= 25 else None
    except Exception:
        logger.exception("_fetch_candles error for %s", symbol)
        return None


def train_rl_agent(
    df: pd.DataFrame,
    algo: AlgoName = "ppo",
    timesteps: int = 50_000,
    symbol: str = "MODEL",
) -> dict:
    """Train an SB3 agent on the provided OHLCV dataframe and save to disk."""
    from stable_baselines3 import A2C, DQN, PPO

    from ai.rl_env import TradingEnv

    ALGOS = {"ppo": PPO, "a2c": A2C, "dqn": DQN}
    cls = ALGOS.get(algo.lower(), PPO)

    try:
        env = TradingEnv(df)
        try:
            model = cls("MlpPolicy", env, verbose=0)
            model.learn(total_timesteps=int(timesteps))
        finally:
            env.close()

        path = _get_model_path(symbol, algo)
        path.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(path))
        logger.info("Trained %s for %s — saved to %s", algo.upper(), symbol, path)
        return {"status": "trained", "model_path": str(path), "algo": algo, "timesteps": timesteps}
    except Exception:
        logger.exception("train_rl_agent error for %s", symbol)
        return {"status": "error", "message": "Training failed", "algo": algo, "symbol": symbol}


def get_rl_signal(
    symbol: str,
    exchange: str,
    api_key: str,
    algo: AlgoName = "ppo",
    interval: str = "1d",
) -> dict:
    """Load saved model and return current BUY/SELL/HOLD signal with confidence."""
    from stable_baselines3 import A2C, DQN, PPO

    from ai.rl_env import TradingEnv

    ALGOS = {"ppo": PPO, "a2c": A2C, "dqn": DQN}
    cls = ALGOS.get(algo.lower(), PPO)

    path = _get_model_path(symbol, algo)
    if not path.exists():
        return {
            "status": "no_model",
            "signal": "HOLD",
            "confidence": 0.0,
            "message": (
                f"No trained model found for {symbol}. "
                "Train first via /api/v1/agent/rl-train."
            ),
            "symbol": symbol,
            "algo": algo,
        }

    df = _fetch_candles(symbol=symbol, exchange=exchange, api_key=api_key, interval=interval)
    if df is None or len(df) < 25:
        return {
            "status": "error",
            "signal": "HOLD",
            "confidence": 0.0,
            "message": "Insufficient historical data (need 25+ candles)",
        }

    try:
        model = cls.load(str(path))
        env = TradingEnv(df)
        try:
            obs, _ = env.reset()
            from ai.rl_env import LOOKBACK
            n_steps = len(df) - LOOKBACK - 1
            for _ in range(max(n_steps, 0)):
                action, _ = model.predict(obs, deterministic=True)
                obs, _, done, _, _ = env.step(int(action))
                if done:
                    break

            action, _ = model.predict(obs, deterministic=True)
            action_map = {0: "HOLD", 1: "BUY", 2: "SELL"}
            signal = action_map[int(action)]

            votes = [int(model.predict(obs, deterministic=False)[0]) for _ in range(20)]
            confidence = round(votes.count(int(action)) / 20, 2)

            return {
                "status": "success",
                "signal": signal,
                "confidence": confidence,
                "algo": algo,
                "symbol": symbol,
                "model_path": str(path),
                "action_int": int(action),
            }
        finally:
            env.close()
    except Exception:
        logger.exception("RL inference error for %s", symbol)
        return {"status": "error", "signal": "HOLD", "confidence": 0.0, "message": "Inference failed"}
