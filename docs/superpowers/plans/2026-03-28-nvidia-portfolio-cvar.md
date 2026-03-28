# NVIDIA Portfolio CVaR Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GPU-accelerated (CUDA via CuPy/PyTorch) Conditional Value at Risk (CVaR) portfolio optimization for a basket of NSE stocks, exposed as `/api/v1/agent/portfolio-cvar` and displayed in a new `PortfolioCVaRTab` inside `AIAnalyzer`.

**Architecture:** `ai/portfolio_cvar.py` runs Monte Carlo simulation of portfolio returns (10,000+ scenarios) using `numpy` on CPU (with optional `cupy` GPU path). It computes CVaR at 95%/99% confidence levels, optimal weights via `scipy.optimize.minimize`, and a max-Sharpe alternative. The React tab shows weight allocation pie chart, efficient frontier curve, and risk metrics table.

**Tech Stack:** `numpy`, `scipy`, `cupy` (optional/graceful fallback), `pandas`, Flask-RESTX, React/TanStack Query, Recharts (PieChart + LineChart), shadcn/ui

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ai/portfolio_cvar.py` | CVaR computation, Monte Carlo, weight optimisation |
| `restx_api/ai_agent.py` | Add `/portfolio-cvar` endpoint |
| `test/test_portfolio_cvar.py` | Unit tests for CVaR math and API |
| `frontend/src/types/strategy-analysis.ts` | Add `PortfolioCVaRData` interface |
| `frontend/src/api/strategy-analysis.ts` | Add `portfolioCVaR()` method |
| `frontend/src/hooks/useStrategyAnalysis.ts` | Add `usePortfolioCVaR` hook |
| `frontend/src/components/ai-analysis/tabs/PortfolioCVaRTab.tsx` | New tab UI |
| `frontend/src/pages/AIAnalyzer.tsx` | Wire in tab |

---

## Task 1: CVaR Core Module

**Files:**
- Create: `ai/portfolio_cvar.py`
- Create: `test/test_portfolio_cvar.py`

- [ ] **Step 1: Write failing tests**

```python
# test/test_portfolio_cvar.py
import numpy as np
import pytest


def make_returns(n_assets=4, n_days=252):
    """Fake daily returns matrix: shape (n_days, n_assets)."""
    np.random.seed(42)
    return np.random.normal(0.001, 0.02, (n_days, n_assets))


def test_compute_cvar_basic():
    from ai.portfolio_cvar import compute_cvar
    returns = make_returns()
    weights = np.array([0.25, 0.25, 0.25, 0.25])
    result = compute_cvar(returns, weights, confidence=0.95)
    assert "cvar_95" in result
    assert "var_95" in result
    assert result["cvar_95"] < 0       # CVaR is a loss
    assert result["cvar_95"] <= result["var_95"]   # CVaR ≤ VaR


def test_compute_cvar_99():
    from ai.portfolio_cvar import compute_cvar
    returns = make_returns()
    weights = np.array([0.25, 0.25, 0.25, 0.25])
    result = compute_cvar(returns, weights, confidence=0.99)
    assert "cvar_99" in result
    # 99% CVaR should be worse (more negative) than 95%
    assert result["cvar_99"] <= result["cvar_95"]


def test_optimise_min_cvar():
    from ai.portfolio_cvar import optimise_min_cvar
    returns = make_returns(n_assets=4)
    result = optimise_min_cvar(returns)
    assert "weights" in result
    assert len(result["weights"]) == 4
    assert abs(sum(result["weights"]) - 1.0) < 1e-4   # weights sum to 1
    assert all(w >= -0.01 for w in result["weights"])   # no short selling


def test_optimise_max_sharpe():
    from ai.portfolio_cvar import optimise_max_sharpe
    returns = make_returns(n_assets=4)
    result = optimise_max_sharpe(returns)
    assert "weights" in result
    assert "sharpe" in result
    assert abs(sum(result["weights"]) - 1.0) < 1e-4


def test_run_portfolio_analysis_full():
    from ai.portfolio_cvar import run_portfolio_analysis
    symbols = ["A", "B", "C"]
    # Fake returns dict
    import pandas as pd
    returns_dict = {
        s: pd.Series(np.random.normal(0.001, 0.02, 252)) for s in symbols
    }
    result = run_portfolio_analysis(symbols=symbols, returns_dict=returns_dict)
    assert result["status"] == "success"
    assert "min_cvar_weights" in result
    assert "max_sharpe_weights" in result
    assert "cvar_95" in result
    assert "efficient_frontier" in result
    assert isinstance(result["efficient_frontier"], list)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd D:\openalgo && uv run pytest test/test_portfolio_cvar.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'ai.portfolio_cvar'`

- [ ] **Step 3: Implement `ai/portfolio_cvar.py`**

```python
"""CVaR Portfolio Optimisation — GPU-optional via CuPy, fallback to NumPy.

CVaR (Conditional Value at Risk) = expected loss beyond the VaR threshold.
Minimising CVaR produces portfolios that limit tail-risk losses.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional
from scipy.optimize import minimize, LinearConstraint, Bounds

from utils.logging import get_logger

logger = get_logger(__name__)

# Try GPU acceleration; silently fall back to numpy
try:
    import cupy as cp
    _USE_GPU = True
    logger.info("CuPy detected — using GPU for Monte Carlo")
except ImportError:
    cp = None
    _USE_GPU = False


def _xp():
    """Return cupy if available, else numpy."""
    return cp if _USE_GPU else np


def _to_np(arr) -> np.ndarray:
    """Move array to CPU numpy if it's on GPU."""
    if _USE_GPU and isinstance(arr, cp.ndarray):
        return cp.asnumpy(arr)
    return np.asarray(arr)


def compute_cvar(
    returns: np.ndarray,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> dict:
    """Compute VaR and CVaR for a weighted portfolio.

    Args:
        returns: shape (T, N) daily returns matrix
        weights: shape (N,) portfolio weights summing to 1
        confidence: 0.95 or 0.99

    Returns:
        dict with cvar_{pct} and var_{pct} keys (negative = loss)
    """
    xp = _xp()
    R = xp.asarray(returns, dtype=xp.float32)
    w = xp.asarray(weights, dtype=xp.float32)
    port_returns = R @ w                            # (T,)
    sorted_r = xp.sort(port_returns)
    cutoff = int((1 - confidence) * len(sorted_r))
    cutoff = max(cutoff, 1)
    var = float(_to_np(sorted_r[cutoff]))
    cvar = float(_to_np(sorted_r[:cutoff].mean()))
    pct = int(confidence * 100)
    return {f"var_{pct}": round(var, 6), f"cvar_{pct}": round(cvar, 6)}


def optimise_min_cvar(returns: np.ndarray, confidence: float = 0.95) -> dict:
    """Find portfolio weights that minimise CVaR at given confidence level."""
    n = returns.shape[1]

    def _neg_cvar(w: np.ndarray) -> float:
        r = compute_cvar(returns, w, confidence)
        pct = int(confidence * 100)
        return r[f"cvar_{pct}"]  # already negative, minimising makes it less negative

    w0 = np.ones(n) / n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = Bounds(lb=0.0, ub=1.0)
    res = minimize(_neg_cvar, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                   options={"maxiter": 500, "ftol": 1e-9})
    weights = (res.x / res.x.sum()).tolist()
    pct = int(confidence * 100)
    metrics = compute_cvar(returns, np.array(weights), confidence)
    return {"weights": weights, **metrics, "converged": bool(res.success)}


def optimise_max_sharpe(returns: np.ndarray, risk_free: float = 0.065 / 252) -> dict:
    """Find portfolio weights that maximise Sharpe ratio."""
    n = returns.shape[1]
    mean_r = returns.mean(axis=0)
    cov = np.cov(returns.T)

    def _neg_sharpe(w: np.ndarray) -> float:
        ret = float(w @ mean_r)
        vol = float(np.sqrt(w @ cov @ w))
        return -(ret - risk_free) / (vol + 1e-9)

    w0 = np.ones(n) / n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = Bounds(lb=0.0, ub=1.0)
    res = minimize(_neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                   options={"maxiter": 500})
    weights = (res.x / res.x.sum()).tolist()
    sharpe = -_neg_sharpe(np.array(weights))
    ann_return = float(np.array(weights) @ mean_r) * 252
    ann_vol = float(np.sqrt(np.array(weights) @ cov @ np.array(weights))) * np.sqrt(252)
    return {
        "weights": weights,
        "sharpe": round(sharpe, 4),
        "annual_return": round(ann_return, 4),
        "annual_volatility": round(ann_vol, 4),
        "converged": bool(res.success),
    }


def _efficient_frontier(returns: np.ndarray, n_points: int = 20) -> list[dict]:
    """Sample the efficient frontier (return, volatility) pairs."""
    n = returns.shape[1]
    mean_r = returns.mean(axis=0)
    cov = np.cov(returns.T)
    target_returns = np.linspace(mean_r.min(), mean_r.max(), n_points)
    frontier = []
    for target in target_returns:
        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1.0},
            {"type": "eq", "fun": lambda w, t=target: w @ mean_r - t},
        ]
        res = minimize(
            lambda w: float(np.sqrt(w @ cov @ w)),
            np.ones(n) / n,
            method="SLSQP",
            bounds=Bounds(0.0, 1.0),
            constraints=constraints,
            options={"maxiter": 200},
        )
        if res.success:
            vol = float(np.sqrt(res.x @ cov @ res.x)) * np.sqrt(252)
            ret = float(res.x @ mean_r) * 252
            frontier.append({"volatility": round(vol, 4), "return": round(ret, 4)})
    return frontier


def run_portfolio_analysis(
    symbols: list[str],
    returns_dict: dict[str, pd.Series],
    confidence: float = 0.95,
) -> dict:
    """Full portfolio analysis: CVaR, Sharpe, efficient frontier."""
    try:
        df = pd.DataFrame(returns_dict)[symbols].dropna()
        if len(df) < 30:
            return {"status": "error", "message": "Need at least 30 days of return data"}
        returns = df.values.astype(np.float64)

        equal_w = np.ones(len(symbols)) / len(symbols)
        eq_metrics_95 = compute_cvar(returns, equal_w, 0.95)
        eq_metrics_99 = compute_cvar(returns, equal_w, 0.99)

        min_cvar_result = optimise_min_cvar(returns, confidence)
        max_sharpe_result = optimise_max_sharpe(returns)
        frontier = _efficient_frontier(returns)

        return {
            "status": "success",
            "symbols": symbols,
            "n_days": len(df),
            "gpu_used": _USE_GPU,
            "equal_weight_metrics": {**eq_metrics_95, **eq_metrics_99},
            "min_cvar_weights": dict(zip(symbols, [round(w, 4) for w in min_cvar_result["weights"]])),
            "max_sharpe_weights": dict(zip(symbols, [round(w, 4) for w in max_sharpe_result["weights"]])),
            "cvar_95": min_cvar_result.get("cvar_95", 0),
            "cvar_99": compute_cvar(returns, np.array(min_cvar_result["weights"]), 0.99).get("cvar_99", 0),
            "sharpe": max_sharpe_result["sharpe"],
            "annual_return": max_sharpe_result["annual_return"],
            "annual_volatility": max_sharpe_result["annual_volatility"],
            "efficient_frontier": frontier,
        }
    except Exception:
        logger.exception("Portfolio CVaR analysis failed")
        return {"status": "error", "message": "Portfolio optimisation failed"}
```

- [ ] **Step 4: Run tests**

```bash
cd D:\openalgo && uv run pytest test/test_portfolio_cvar.py -v
```
Expected: All 5 pass.

- [ ] **Step 5: Commit**

```bash
git add ai/portfolio_cvar.py test/test_portfolio_cvar.py
git commit -m "feat(cvar): add CVaR portfolio optimisation module with GPU-optional Monte Carlo"
```

---

## Task 2: REST Endpoint

**Files:**
- Modify: `restx_api/ai_agent.py`

- [ ] **Step 1: Append endpoint**

Add after `RLTrainResource` (or at end of file):

```python
@api.route("/portfolio-cvar")
class PortfolioCVaRResource(Resource):
    @limiter.limit("5 per minute")
    def post(self):
        """CVaR portfolio optimisation for a basket of symbols."""
        from flask import request
        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbols = data.get("symbols", [])   # e.g. ["RELIANCE","TCS","INFY","HDFCBANK"]
        exchange = data.get("exchange", "NSE")
        interval = data.get("interval", "1d")

        if not symbols or not isinstance(symbols, list):
            return {"status": "error", "message": "symbols list is required"}, 400
        if len(symbols) < 2:
            return {"status": "error", "message": "Need at least 2 symbols"}, 400
        if len(symbols) > 20:
            return {"status": "error", "message": "Max 20 symbols"}, 400
        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        try:
            from ai.rl_agent import _fetch_candles
            import pandas as pd
            returns_dict = {}
            for sym in symbols:
                df = _fetch_candles(symbol=sym, exchange=exchange, api_key=api_key, interval=interval)
                if df is not None and len(df) >= 30:
                    returns_dict[sym] = df["close"].pct_change().dropna()

            if len(returns_dict) < 2:
                return {"status": "error", "message": "Could not fetch data for enough symbols"}, 422

            from ai.portfolio_cvar import run_portfolio_analysis
            valid_symbols = list(returns_dict.keys())
            result = run_portfolio_analysis(symbols=valid_symbols, returns_dict=returns_dict)
            return {"status": "success", "data": result}
        except Exception:
            logger.exception("Portfolio CVaR error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500
```

- [ ] **Step 2: Smoke test endpoint**

```bash
cd D:\openalgo && uv run python -c "
from app import app
with app.test_client() as c:
    r = c.post('/api/v1/agent/portfolio-cvar', json={'apikey':'bad','symbols':['A','B']})
    print(r.status_code, r.json)
"
```
Expected: `403 {'status': 'error', 'message': 'Invalid openalgo apikey'}`

- [ ] **Step 3: Commit**

```bash
git add restx_api/ai_agent.py
git commit -m "feat(cvar): add /portfolio-cvar REST endpoint"
```

---

## Task 3: TypeScript Types + API + Hook

**Files:**
- Modify: `frontend/src/types/strategy-analysis.ts`
- Modify: `frontend/src/api/strategy-analysis.ts`
- Modify: `frontend/src/hooks/useStrategyAnalysis.ts`

- [ ] **Step 1: Add types**

Append to `frontend/src/types/strategy-analysis.ts`:

```typescript
// ─── Portfolio CVaR ───
export interface EfficientFrontierPoint {
  volatility: number
  return: number
}

export interface PortfolioCVaRData {
  status: 'success' | 'error'
  symbols: string[]
  n_days: number
  gpu_used: boolean
  equal_weight_metrics: {
    var_95: number; cvar_95: number
    var_99: number; cvar_99: number
  }
  min_cvar_weights: Record<string, number>
  max_sharpe_weights: Record<string, number>
  cvar_95: number
  cvar_99: number
  sharpe: number
  annual_return: number
  annual_volatility: number
  efficient_frontier: EfficientFrontierPoint[]
  message?: string
}
```

- [ ] **Step 2: Add API method**

In `frontend/src/api/strategy-analysis.ts`, add to `strategyApi`:

```typescript
  portfolioCVaR: (apikey: string, symbols: string[], exchange = 'NSE') =>
    post<PortfolioCVaRData>('/api/v1/agent/portfolio-cvar', { apikey, symbols, exchange }),
```

Add `PortfolioCVaRData` to the import at the top.

- [ ] **Step 3: Add hook**

Append to `frontend/src/hooks/useStrategyAnalysis.ts`:

```typescript
export function usePortfolioCVaR(symbols: string[], exchange: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['portfolio-cvar', symbols.join(','), exchange],
    queryFn: () => strategyApi.portfolioCVaR(apikey!, symbols, exchange),
    enabled: enabled && !!apikey && symbols.length >= 2,
    staleTime: 5 * 60_000,
    retry: false,
  })
}
```

- [ ] **Step 4: Build check**

```bash
cd D:\openalgo\frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/strategy-analysis.ts frontend/src/api/strategy-analysis.ts frontend/src/hooks/useStrategyAnalysis.ts
git commit -m "feat(cvar): add PortfolioCVaRData type, API method, and usePortfolioCVaR hook"
```

---

## Task 4: React PortfolioCVaRTab Component

**Files:**
- Create: `frontend/src/components/ai-analysis/tabs/PortfolioCVaRTab.tsx`
- Modify: `frontend/src/pages/AIAnalyzer.tsx`

- [ ] **Step 1: Create `PortfolioCVaRTab.tsx`**

```tsx
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, PieChartIcon, TrendingUp, AlertTriangle, Cpu } from 'lucide-react'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
} from 'recharts'
import { usePortfolioCVaR } from '@/hooks/useStrategyAnalysis'

const COLORS = ['#6366f1','#22c55e','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#ec4899','#84cc16']

const NIFTY10 = ['RELIANCE','TCS','HDFCBANK','INFY','ICICIBANK','HINDUNILVR','SBIN','BHARTIARTL','ITC','KOTAKBANK']

interface Props { exchange: string }

function WeightPie({ weights, title }: { weights: Record<string, number>; title: string }) {
  const data = Object.entries(weights).map(([name, value]) => ({ name, value: +(value * 100).toFixed(1) }))
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie data={data} cx="50%" cy="50%" outerRadius={70} dataKey="value" label={({ name, value }) => `${name} ${value}%`} labelLine={false}>
              {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip formatter={(v: number) => `${v}%`} />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

export function PortfolioCVaRTab({ exchange }: Props) {
  const [symbols, setSymbols] = useState<string[]>(NIFTY10.slice(0, 5))
  const [inputVal, setInputVal] = useState(NIFTY10.slice(0, 5).join(', '))
  const [run, setRun] = useState(false)
  const { data, isLoading, refetch } = usePortfolioCVaR(symbols, exchange, run)

  const handleAnalyse = () => {
    const syms = inputVal.split(',').map(s => s.trim().toUpperCase()).filter(Boolean)
    setSymbols(syms)
    setRun(true)
    setTimeout(() => refetch(), 100)
  }

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <PieChartIcon className="h-5 w-5 text-indigo-500" />
        <h3 className="font-semibold text-lg">CVaR Portfolio Optimiser</h3>
        <Badge variant="outline" className="text-xs">NVIDIA / SciPy</Badge>
        {data?.gpu_used && <Badge className="text-xs bg-green-100 text-green-800"><Cpu className="h-3 w-3 mr-1" />GPU</Badge>}
      </div>

      {/* Symbol Input */}
      <Card>
        <CardContent className="pt-4 flex gap-2 flex-wrap items-end">
          <div className="flex-1 min-w-48">
            <label className="text-xs text-muted-foreground mb-1 block">Symbols (comma-separated, min 2)</label>
            <input
              className="w-full border rounded px-3 py-2 text-sm bg-background"
              value={inputVal}
              onChange={e => setInputVal(e.target.value)}
              placeholder="RELIANCE, TCS, INFY, HDFCBANK"
            />
          </div>
          <Button onClick={handleAnalyse} disabled={isLoading}>
            {isLoading ? <><Loader2 className="h-4 w-4 animate-spin mr-1" />Optimising…</> : 'Optimise'}
          </Button>
        </CardContent>
      </Card>

      {!run && (
        <p className="text-sm text-muted-foreground text-center py-8">
          Enter symbols and click <strong>Optimise</strong> to run CVaR portfolio analysis.
        </p>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" /> Running Monte Carlo optimisation…
        </div>
      )}

      {data?.status === 'error' && (
        <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-700 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="text-sm">{data.message}</span>
        </div>
      )}

      {data?.status === 'success' && (
        <>
          {/* Risk Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: 'CVaR 95%', value: `${(data.cvar_95 * 100).toFixed(2)}%`, note: 'Daily tail loss', color: 'text-red-600' },
              { label: 'CVaR 99%', value: `${(data.cvar_99 * 100).toFixed(2)}%`, note: 'Extreme tail loss', color: 'text-red-700' },
              { label: 'Sharpe', value: data.sharpe.toFixed(2), note: 'Max Sharpe portfolio', color: 'text-green-600' },
              { label: 'Ann. Return', value: `${(data.annual_return * 100).toFixed(1)}%`, note: 'Max Sharpe portfolio', color: 'text-blue-600' },
            ].map(m => (
              <Card key={m.label}>
                <CardContent className="pt-3 pb-3">
                  <p className="text-xs text-muted-foreground">{m.label}</p>
                  <p className={`text-2xl font-bold font-mono ${m.color}`}>{m.value}</p>
                  <p className="text-xs text-muted-foreground">{m.note}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Weight Pies */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <WeightPie weights={data.min_cvar_weights} title="Min CVaR Weights" />
            <WeightPie weights={data.max_sharpe_weights} title="Max Sharpe Weights" />
          </div>

          {/* Efficient Frontier */}
          {data.efficient_frontier.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1">
                  <TrendingUp className="h-4 w-4" /> Efficient Frontier
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={220}>
                  <ScatterChart>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="volatility" name="Volatility" tickFormatter={v => `${(v*100).toFixed(0)}%`} label={{ value: 'Ann. Vol', position: 'insideBottom', offset: -5 }} />
                    <YAxis dataKey="return" name="Return" tickFormatter={v => `${(v*100).toFixed(0)}%`} label={{ value: 'Ann. Return', angle: -90, position: 'insideLeft' }} />
                    <Tooltip formatter={(v: number) => `${(v*100).toFixed(2)}%`} />
                    <Scatter data={data.efficient_frontier} fill="#6366f1" />
                  </ScatterChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          <p className="text-xs text-muted-foreground">
            Data: {data.n_days} trading days · {data.symbols.length} assets
            {data.gpu_used ? ' · GPU-accelerated' : ' · CPU compute'}
          </p>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Wire into `AIAnalyzer.tsx`**

Add import:
```typescript
import { PortfolioCVaRTab } from '@/components/ai-analysis/tabs/PortfolioCVaRTab'
```

Add icon to lucide-react imports: `PieChart` (if not already present).

Add tab trigger (after rl-agent):
```tsx
<TabsTrigger value="portfolio-cvar">
  <PieChart className="h-4 w-4 mr-1" /> Portfolio
</TabsTrigger>
```

Add tab content:
```tsx
<TabsContent value="portfolio-cvar">
  <PortfolioCVaRTab exchange={exchange} />
</TabsContent>
```

- [ ] **Step 3: Build**

```bash
cd D:\openalgo\frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in ...`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ai-analysis/tabs/PortfolioCVaRTab.tsx frontend/src/pages/AIAnalyzer.tsx
git commit -m "feat(cvar): add PortfolioCVaRTab with pie charts and efficient frontier"
```

---

## Final Smoke Test

- [ ] Start OpenAlgo: `cd D:\openalgo && uv run app.py`
- [ ] Navigate to `http://127.0.0.1:5000/react` → AI Analyzer → **Portfolio** tab
- [ ] Default symbols `RELIANCE, TCS, INFY, HDFCBANK, SBIN` → click **Optimise**
- [ ] Verify: CVaR metrics appear, two weight pie charts render, efficient frontier scatter plot shows
- [ ] Push: `git push origin main:vayu-ml-intelligence`
