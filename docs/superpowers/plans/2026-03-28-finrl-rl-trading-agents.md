# FinRL Reinforcement Learning Trading Agents — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate FinRL-style reinforcement learning (PPO/A2C/DQN via Stable-Baselines3) into OpenAlgo as a trainable trading agent that generates BUY/SELL/HOLD signals, with a backend training+inference pipeline and a React `RLAgentTab` inside `AIAnalyzer`.

**Architecture:** A standalone `ai/rl_agent.py` module wraps Stable-Baselines3 (SB3) PPO/A2C agents with a custom Gym environment built on OpenAlgo historical data. Training runs offline (CLI or API trigger); inference runs in real-time via `/api/v1/agent/rl-signal`. The React tab shows current signal, reward curve, and last-N trade decisions.

**Tech Stack:** `stable-baselines3`, `gymnasium`, `pandas`, `numpy`, `scikit-learn` (for feature scaling), Flask-RESTX, React/TanStack Query, shadcn/ui, Recharts

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ai/rl_agent.py` | Gym environment + SB3 training + inference |
| `ai/rl_env.py` | Custom `TradingEnv(gymnasium.Env)` — state, action, reward |
| `ml/rl_models/` | Saved model artifacts (`.zip` files, gitignored) |
| `restx_api/ai_agent.py` | Add `/rl-signal` and `/rl-train` endpoints |
| `test/test_rl_agent.py` | Unit tests for env step/reset, inference |
| `frontend/src/hooks/useStrategyAnalysis.ts` | Add `useRLSignal` hook |
| `frontend/src/api/strategy-analysis.ts` | Add `rlSignal()` method |
| `frontend/src/types/strategy-analysis.ts` | Add `RLSignalData` interface |
| `frontend/src/components/ai-analysis/tabs/RLAgentTab.tsx` | New tab UI |
| `frontend/src/pages/AIAnalyzer.tsx` | Wire in `RLAgentTab` |

---

## Task 1: Custom Gym Trading Environment

**Files:**
- Create: `ai/rl_env.py`
- Test: `test/test_rl_agent.py`

- [ ] **Step 1: Write failing tests for TradingEnv**

```python
# test/test_rl_agent.py
import numpy as np
import pytest

def make_env():
    from ai.rl_env import TradingEnv
    # 50 rows of fake OHLCV
    import pandas as pd
    n = 50
    df = pd.DataFrame({
        'open':  np.linspace(100, 150, n),
        'high':  np.linspace(105, 155, n),
        'low':   np.linspace(95, 145, n),
        'close': np.linspace(100, 150, n),
        'volume': np.ones(n) * 1_000_000,
    })
    return TradingEnv(df, initial_cash=100_000)

def test_env_reset():
    env = make_env()
    obs, info = env.reset()
    assert obs.shape == (env.observation_space.shape[0],)
    assert info == {}

def test_env_step_hold():
    env = make_env()
    env.reset()
    obs, reward, terminated, truncated, info = env.step(0)  # 0=HOLD
    assert isinstance(reward, float)
    assert obs.shape == (env.observation_space.shape[0],)

def test_env_step_buy_then_sell():
    env = make_env()
    env.reset()
    env.step(1)   # BUY
    obs, reward, terminated, truncated, info = env.step(2)  # SELL
    assert 'portfolio_value' in info

def test_env_done_at_end():
    env = make_env()
    env.reset()
    done = False
    for _ in range(200):
        _, _, terminated, truncated, _ = env.step(0)
        if terminated or truncated:
            done = True
            break
    assert done
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:\openalgo && uv run pytest test/test_rl_agent.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'ai.rl_env'`

- [ ] **Step 3: Implement TradingEnv**

Create `ai/rl_env.py`:

```python
"""Custom Gymnasium Trading Environment for RL agents.

Actions: 0=HOLD, 1=BUY, 2=SELL
State:   last 20 candles of [open,high,low,close,volume] + [position, cash_ratio]
Reward:  step-to-step portfolio value change (log return)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

LOOKBACK = 20   # candles in observation window
N_FEATURES = 5  # open,high,low,close,volume (normalised)


class TradingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, df: pd.DataFrame, initial_cash: float = 100_000.0):
        super().__init__()
        self.df = df.reset_index(drop=True)
        self.initial_cash = initial_cash
        n_obs = LOOKBACK * N_FEATURES + 2  # +position +cash_ratio
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(n_obs,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0=HOLD,1=BUY,2=SELL
        self._cursor = LOOKBACK
        self._cash = initial_cash
        self._shares = 0
        self._prev_value = initial_cash

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._cursor = LOOKBACK
        self._cash = self.initial_cash
        self._shares = 0
        self._prev_value = self.initial_cash
        return self._obs(), {}

    def step(self, action: int):
        price = float(self.df.loc[self._cursor, "close"])
        if action == 1 and self._shares == 0:   # BUY
            self._shares = int(self._cash // price)
            self._cash -= self._shares * price
        elif action == 2 and self._shares > 0:  # SELL
            self._cash += self._shares * price
            self._shares = 0
        self._cursor += 1
        portfolio = self._cash + self._shares * price
        reward = float(np.log(portfolio / self._prev_value + 1e-9))
        self._prev_value = portfolio
        terminated = self._cursor >= len(self.df)
        truncated = False
        info = {"portfolio_value": portfolio, "shares": self._shares, "cash": self._cash}
        if terminated:
            return self._obs(clamp=True), reward, True, False, info
        return self._obs(), reward, terminated, truncated, info

    def _obs(self, clamp=False) -> np.ndarray:
        idx = min(self._cursor, len(self.df) - 1) if clamp else self._cursor
        window = self.df.iloc[idx - LOOKBACK: idx][["open","high","low","close","volume"]].values.astype(np.float32)
        # Normalise: each feature divided by its first value in window
        denom = window[0].copy()
        denom[denom == 0] = 1.0
        window = window / denom - 1.0   # log-return-like, bounded near 0
        price = float(self.df.loc[min(idx, len(self.df)-1), "close"])
        total = self._cash + self._shares * price
        position = float(self._shares > 0)
        cash_ratio = float(self._cash / (total + 1e-9))
        return np.append(window.flatten(), [position, cash_ratio]).astype(np.float32)
```

- [ ] **Step 4: Run tests**

```bash
cd D:\openalgo && uv run pytest test/test_rl_agent.py -v
```
Expected: All 4 pass. If `gymnasium` missing: `uv add gymnasium stable-baselines3`

- [ ] **Step 5: Commit**

```bash
git add ai/rl_env.py test/test_rl_agent.py
git commit -m "feat(rl): add custom Gymnasium TradingEnv for FinRL agents"
```

---

## Task 2: RL Agent Training & Inference Module

**Files:**
- Create: `ai/rl_agent.py`
- Modify: `test/test_rl_agent.py` (add inference tests)

- [ ] **Step 1: Write failing tests**

Append to `test/test_rl_agent.py`:

```python
def test_train_ppo_short():
    """Train PPO for 512 steps — just verify it runs without error."""
    from ai.rl_agent import train_rl_agent
    import pandas as pd
    n = 100
    df = pd.DataFrame({
        'open':  np.random.uniform(100,200,n),
        'high':  np.random.uniform(105,205,n),
        'low':   np.random.uniform(95,195,n),
        'close': np.random.uniform(100,200,n),
        'volume': np.ones(n)*1_000_000,
    })
    result = train_rl_agent(df, algo="ppo", timesteps=512, symbol="TEST")
    assert result["status"] == "trained"
    assert "model_path" in result
    import os; assert os.path.exists(result["model_path"])

def test_get_rl_signal_no_model():
    from ai.rl_agent import get_rl_signal
    result = get_rl_signal(symbol="NONEXISTENT", exchange="NSE", api_key="test")
    assert result["status"] in ("no_model", "error")

def test_get_rl_signal_mock(tmp_path, monkeypatch):
    """Train tiny model then get signal."""
    import pandas as pd
    from ai.rl_agent import train_rl_agent, get_rl_signal
    n = 100
    df = pd.DataFrame({
        'open':  np.linspace(100,200,n),
        'high':  np.linspace(105,205,n),
        'low':   np.linspace(95,195,n),
        'close': np.linspace(100,200,n),
        'volume': np.ones(n)*1_000_000,
    })
    train_rl_agent(df, algo="ppo", timesteps=512, symbol="MOCKTEST")

    # Patch historical data fetch to return our df
    import ai.rl_agent as module
    monkeypatch.setattr(module, "_fetch_candles", lambda *a, **kw: df)
    result = get_rl_signal(symbol="MOCKTEST", exchange="NSE", api_key="test")
    assert result["signal"] in ("BUY", "SELL", "HOLD")
    assert 0.0 <= result["confidence"] <= 1.0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd D:\openalgo && uv run pytest test/test_rl_agent.py::test_train_ppo_short -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'ai.rl_agent'`

- [ ] **Step 3: Implement `ai/rl_agent.py`**

```python
"""FinRL-style RL trading agent — train PPO/A2C on historical data, infer signal.

Model artifacts saved to ml/rl_models/{symbol}_{algo}.zip
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from utils.logging import get_logger

logger = get_logger(__name__)

MODEL_DIR = Path("ml/rl_models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

AlgoName = Literal["ppo", "a2c", "dqn"]


def _get_model_path(symbol: str, algo: str) -> Path:
    return MODEL_DIR / f"{symbol.upper()}_{algo.lower()}.zip"


def _fetch_candles(symbol: str, exchange: str, api_key: str, interval: str = "1d", limit: int = 500) -> pd.DataFrame | None:
    """Fetch historical OHLCV from OpenAlgo's own data service."""
    try:
        from services.ai_analysis_service import get_historical_data
        candles = get_historical_data(symbol=symbol, exchange=exchange, interval=interval, api_key=api_key)
        if not candles:
            return None
        df = pd.DataFrame(candles)
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna().tail(limit).reset_index(drop=True)
    except Exception:
        logger.exception("Failed to fetch candles for %s", symbol)
        return None


def train_rl_agent(
    df: pd.DataFrame,
    algo: AlgoName = "ppo",
    timesteps: int = 50_000,
    symbol: str = "MODEL",
) -> dict:
    """Train an SB3 agent on the provided OHLCV dataframe."""
    from stable_baselines3 import PPO, A2C, DQN
    from ai.rl_env import TradingEnv

    ALGOS = {"ppo": PPO, "a2c": A2C, "dqn": DQN}
    cls = ALGOS.get(algo.lower(), PPO)

    env = TradingEnv(df)
    model = cls("MlpPolicy", env, verbose=0)
    model.learn(total_timesteps=timesteps)

    path = _get_model_path(symbol, algo)
    model.save(str(path))
    logger.info("Trained %s for %s — saved to %s", algo.upper(), symbol, path)
    return {"status": "trained", "model_path": str(path), "algo": algo, "timesteps": timesteps}


def get_rl_signal(
    symbol: str,
    exchange: str,
    api_key: str,
    algo: AlgoName = "ppo",
    interval: str = "1d",
) -> dict:
    """Load saved model and return current BUY/SELL/HOLD signal."""
    from stable_baselines3 import PPO, A2C, DQN
    from ai.rl_env import TradingEnv

    ALGOS = {"ppo": PPO, "a2c": A2C, "dqn": DQN}
    cls = ALGOS.get(algo.lower(), PPO)

    path = _get_model_path(symbol, algo)
    if not path.exists():
        return {
            "status": "no_model",
            "signal": "HOLD",
            "confidence": 0.0,
            "message": f"No trained model found for {symbol}. Train first via /api/v1/agent/rl-train.",
            "symbol": symbol,
            "algo": algo,
        }

    df = _fetch_candles(symbol=symbol, exchange=exchange, api_key=api_key, interval=interval)
    if df is None or len(df) < 25:
        return {"status": "error", "signal": "HOLD", "confidence": 0.0, "message": "Insufficient historical data"}

    try:
        model = cls.load(str(path))
        env = TradingEnv(df)
        obs, _ = env.reset()
        # Step through to latest candle
        for _ in range(len(df) - 21):
            action, _ = model.predict(obs, deterministic=True)
            obs, _, done, _, _ = env.step(int(action))
            if done:
                break
        action, _states = model.predict(obs, deterministic=True)
        action_map = {0: "HOLD", 1: "BUY", 2: "SELL"}
        signal = action_map[int(action)]

        # Confidence: run stochastic predictions, measure agreement
        probs = []
        for _ in range(20):
            a, _ = model.predict(obs, deterministic=False)
            probs.append(int(a))
        confidence = round(probs.count(int(action)) / 20, 2)

        return {
            "status": "success",
            "signal": signal,
            "confidence": confidence,
            "algo": algo,
            "symbol": symbol,
            "model_path": str(path),
            "action_int": int(action),
        }
    except Exception:
        logger.exception("RL inference error for %s", symbol)
        return {"status": "error", "signal": "HOLD", "confidence": 0.0, "message": "Inference failed"}
```

- [ ] **Step 4: Install dependencies**

```bash
cd D:\openalgo && uv add gymnasium stable-baselines3
```

- [ ] **Step 5: Run tests**

```bash
cd D:\openalgo && uv run pytest test/test_rl_agent.py -v
```
Expected: All 7 tests pass (training takes ~10s for 512 steps).

- [ ] **Step 6: Commit**

```bash
git add ai/rl_agent.py test/test_rl_agent.py pyproject.toml uv.lock
git commit -m "feat(rl): add FinRL-style PPO/A2C/DQN training and inference module"
```

---

## Task 3: REST API Endpoints

**Files:**
- Modify: `restx_api/ai_agent.py` (append two new Resource classes)

- [ ] **Step 1: Write failing test**

```python
# append to test/test_rl_agent.py
def test_api_rl_signal_no_model(client, api_key):
    """Endpoint returns 200 with no_model status when model doesn't exist."""
    resp = client.post("/api/v1/agent/rl-signal", json={
        "apikey": api_key, "symbol": "ZZZNOTEXIST", "exchange": "NSE"
    })
    assert resp.status_code == 200
    assert resp.json["data"]["status"] == "no_model"
```

> Note: `client` and `api_key` fixtures are in `conftest.py`.

- [ ] **Step 2: Run to verify failure**

```bash
cd D:\openalgo && uv run pytest test/test_rl_agent.py::test_api_rl_signal_no_model -v 2>&1 | head -10
```
Expected: `404` or fixture error.

- [ ] **Step 3: Add endpoints to `restx_api/ai_agent.py`**

Append after the last `@api.route` block (after `ResearchResource`):

```python
@api.route("/rl-signal")
class RLSignalResource(Resource):
    @limiter.limit("5 per minute")
    def post(self):
        """Return current BUY/SELL/HOLD signal from trained RL agent for a symbol."""
        from flask import request
        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")
        algo = data.get("algo", "ppo")

        if not symbol:
            return {"status": "error", "message": "symbol is required"}, 400
        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        try:
            from ai.rl_agent import get_rl_signal
            result = get_rl_signal(symbol=symbol, exchange=exchange, api_key=api_key, algo=algo)
            return {"status": "success", "data": result}
        except Exception:
            logger.exception("RL signal error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500


@api.route("/rl-train")
class RLTrainResource(Resource):
    @limiter.limit("2 per hour")
    def post(self):
        """Trigger RL agent training for a symbol (blocking — use for small timesteps)."""
        from flask import request
        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")
        algo = data.get("algo", "ppo")
        timesteps = int(data.get("timesteps", 20_000))

        if not symbol:
            return {"status": "error", "message": "symbol is required"}, 400
        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403
        if timesteps > 100_000:
            return {"status": "error", "message": "Max 100,000 timesteps per API call"}, 400

        try:
            from ai.rl_agent import train_rl_agent, _fetch_candles
            df = _fetch_candles(symbol=symbol, exchange=exchange, api_key=api_key)
            if df is None or len(df) < 50:
                return {"status": "error", "message": "Insufficient historical data (need 50+ candles)"}, 422
            result = train_rl_agent(df=df, algo=algo, timesteps=timesteps, symbol=symbol)
            return {"status": "success", "data": result}
        except Exception:
            logger.exception("RL train error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500
```

- [ ] **Step 4: Run test**

```bash
cd D:\openalgo && uv run pytest test/test_rl_agent.py::test_api_rl_signal_no_model -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add restx_api/ai_agent.py test/test_rl_agent.py
git commit -m "feat(rl): add /rl-signal and /rl-train REST endpoints"
```

---

## Task 4: TypeScript Types + API Client

**Files:**
- Modify: `frontend/src/types/strategy-analysis.ts` (append `RLSignalData`)
- Modify: `frontend/src/api/strategy-analysis.ts` (append `rlSignal()`)
- Modify: `frontend/src/hooks/useStrategyAnalysis.ts` (append `useRLSignal`)

- [ ] **Step 1: Add `RLSignalData` to types**

Append to `frontend/src/types/strategy-analysis.ts`:

```typescript
// ─── RL Agent ───
export interface RLSignalData {
  status: 'success' | 'no_model' | 'error'
  signal: 'BUY' | 'SELL' | 'HOLD'
  confidence: number       // 0–1
  algo: string             // ppo | a2c | dqn
  symbol: string
  model_path?: string
  message?: string
}
```

- [ ] **Step 2: Add API method**

Append to the `strategyApi` object in `frontend/src/api/strategy-analysis.ts`:

```typescript
  rlSignal: (apikey: string, symbol: string, exchange: string, algo = 'ppo') =>
    post<RLSignalData>('/api/v1/agent/rl-signal', { apikey, symbol, exchange, algo }),
```

Add `RLSignalData` to the import at the top of the file.

- [ ] **Step 3: Add hook**

Append to `frontend/src/hooks/useStrategyAnalysis.ts`:

```typescript
export function useRLSignal(symbol: string, exchange: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['rl-signal', symbol, exchange],
    queryFn: () => strategyApi.rlSignal(apikey!, symbol, exchange),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
    retry: false,
  })
}
```

Add `useRLSignal` to the import in files that use it.

- [ ] **Step 4: Build to check types**

```bash
cd D:\openalgo\frontend && npm run build 2>&1 | tail -10
```
Expected: `✓ built in ...`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/strategy-analysis.ts frontend/src/api/strategy-analysis.ts frontend/src/hooks/useStrategyAnalysis.ts
git commit -m "feat(rl): add RLSignalData type, API method, and useRLSignal hook"
```

---

## Task 5: React RLAgentTab Component

**Files:**
- Create: `frontend/src/components/ai-analysis/tabs/RLAgentTab.tsx`
- Modify: `frontend/src/pages/AIAnalyzer.tsx` (import + tab wire-in)

- [ ] **Step 1: Create `RLAgentTab.tsx`**

```tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, Brain, TrendingUp, TrendingDown, Minus, AlertCircle } from 'lucide-react'
import { useRLSignal } from '@/hooks/useStrategyAnalysis'
import { useApiKey } from '@/hooks/useAIAnalysis'
import { apiClient } from '@/api/client'
import { useState } from 'react'
import { showToast } from '@/utils/toast'

interface Props { symbol: string; exchange: string }

const SIGNAL_CONFIG = {
  BUY:  { color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400', icon: TrendingUp,   label: 'BUY' },
  SELL: { color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',         icon: TrendingDown, label: 'SELL' },
  HOLD: { color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400', icon: Minus,   label: 'HOLD' },
}

export function RLAgentTab({ symbol, exchange }: Props) {
  const apikey = useApiKey()
  const [training, setTraining] = useState(false)
  const [algo, setAlgo] = useState<'ppo' | 'a2c' | 'dqn'>('ppo')
  const { data, isLoading, refetch } = useRLSignal(symbol, exchange)

  const handleTrain = async () => {
    if (!apikey) return
    setTraining(true)
    try {
      await apiClient.post('/api/v1/agent/rl-train', {
        apikey, symbol, exchange, algo, timesteps: 20000,
      })
      showToast('Training complete', 'success')
      refetch()
    } catch {
      showToast('Training failed', 'error')
    } finally {
      setTraining(false)
    }
  }

  const signal = data?.signal ?? 'HOLD'
  const cfg = SIGNAL_CONFIG[signal] ?? SIGNAL_CONFIG.HOLD
  const SignalIcon = cfg.icon

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-purple-500" />
          <h3 className="font-semibold text-lg">RL Trading Agent</h3>
          <Badge variant="outline" className="text-xs">FinRL / SB3</Badge>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="text-xs border rounded px-2 py-1 bg-background"
            value={algo}
            onChange={e => setAlgo(e.target.value as typeof algo)}
          >
            <option value="ppo">PPO</option>
            <option value="a2c">A2C</option>
            <option value="dqn">DQN</option>
          </select>
          <Button size="sm" variant="outline" onClick={handleTrain} disabled={training}>
            {training ? <><Loader2 className="h-3 w-3 animate-spin mr-1" />Training…</> : 'Train'}
          </Button>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isLoading}>
            {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Signal Card */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Current Signal — {symbol}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" /> Loading signal…
            </div>
          ) : data?.status === 'no_model' ? (
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <AlertCircle className="h-5 w-5 text-yellow-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium">No model trained yet</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Click <strong>Train</strong> to train a {algo.toUpperCase()} agent on {symbol}'s historical data (~2min for 20k steps).
                </p>
              </div>
            </div>
          ) : data?.status === 'error' ? (
            <p className="text-sm text-red-500">{data.message ?? 'Error fetching signal'}</p>
          ) : (
            <div className="flex items-center gap-4">
              <div className={`flex items-center gap-2 px-4 py-2 rounded-lg text-lg font-bold ${cfg.color}`}>
                <SignalIcon className="h-6 w-6" />
                {cfg.label}
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">
                  Confidence: <span className="font-mono font-semibold">{((data?.confidence ?? 0) * 100).toFixed(0)}%</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  Model: <span className="font-mono">{data?.algo?.toUpperCase()}</span>
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Info Panel */}
      <Card>
        <CardContent className="pt-4">
          <p className="text-xs text-muted-foreground leading-relaxed">
            <strong>How it works:</strong> The RL agent is trained on {symbol}'s OHLCV history using Stable-Baselines3
            ({algo.toUpperCase()}). It learns when to BUY, SELL, or HOLD by maximising portfolio value.
            Training takes ~2 minutes for 20,000 steps. Re-train periodically as market conditions change.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            <strong>Actions:</strong> 0=HOLD · 1=BUY (full position) · 2=SELL (close position)
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 2: Wire into `AIAnalyzer.tsx`**

In `frontend/src/pages/AIAnalyzer.tsx`:

Add import after `ResearchTab` import:
```typescript
import { RLAgentTab } from '@/components/ai-analysis/tabs/RLAgentTab'
```

Add import icon (in existing lucide-react import line):
```typescript
Bot,   // add to existing import
```

Add tab trigger in the `<TabsList>` (after `research` trigger):
```tsx
<TabsTrigger value="rl-agent">
  <Bot className="h-4 w-4 mr-1" /> RL Agent
</TabsTrigger>
```

Add tab content (after `research` TabsContent):
```tsx
<TabsContent value="rl-agent">
  <RLAgentTab symbol={symbol} exchange={exchange} />
</TabsContent>
```

- [ ] **Step 3: Build**

```bash
cd D:\openalgo\frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in ...`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ai-analysis/tabs/RLAgentTab.tsx frontend/src/pages/AIAnalyzer.tsx
git commit -m "feat(rl): add RLAgentTab with signal display and train trigger"
```

---

## Task 6: Add `ml/rl_models/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add gitignore entry**

Append to `.gitignore`:
```
# RL model artifacts (large binary files)
ml/rl_models/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore RL model artifacts"
```

---

## Final Smoke Test

- [ ] Start OpenAlgo: `cd D:\openalgo && uv run app.py`
- [ ] Navigate to `http://127.0.0.1:5000/react` → AI Analyzer → **RL Agent** tab
- [ ] Enter `RELIANCE`, click **Train** → wait ~2 min → signal appears
- [ ] Signal should be BUY, SELL, or HOLD with a confidence percentage
- [ ] Push: `git push origin main:vayu-ml-intelligence`
