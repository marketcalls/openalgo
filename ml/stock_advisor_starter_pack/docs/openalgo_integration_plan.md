# OpenAlgo Integration Plan — Real-Time Trade Guidance

**Status:** PLANNED — not yet built
**Last updated:** 2026-03-22
**Goal:** Connect the RELIANCE swing ML bundle to OpenAlgo for bar-close → inference → recommendation → paper/live order placement.

---

## OpenAlgo Platform
- GitHub: https://github.com/marketcalls/openalgo.git
- REST API: `http://localhost:5000/api/v1`
- WebSocket: ZeroMQ pub/sub port 8765
- Supports 30+ Indian brokers; Analyzer (sandbox) mode for paper trading

---

## Gap Analysis: Current vs Required

| Layer | Current | Required |
|---|---|---|
| Data ingestion | CSV from `D:\TV_proj\` | OpenAlgo `/api/v1/history` |
| Bar assembly | Offline (whole CSV) | BarCloseDetector on ZeroMQ port 8765 |
| Inference trigger | Manual script | Auto on every bar close |
| Signal delivery | Print to console | `Recommendation` dataclass + log |
| Order execution | None | `POST /api/v1/placeorder` |
| Paper trade feedback | None | Fills CSV + running win rate |
| Model promotion | Manual | Drift monitor + win rate threshold |
| Multi-symbol | RELIANCE only | Parameterized configs per symbol/TF |

---

## New Modules to Build

All under `local_project/src/`

### `src/data/openalgo_adapter.py` — `OpenAlgoDataAdapter`
Replace CSV loader. Fetch OHLCV from REST API, return DataFrame matching existing format.

```python
class OpenAlgoDataAdapter:
    def __init__(self, api_key: str, base_url: str = "http://localhost:5000"): ...
    def fetch_ohlcv(self, symbol, exchange, timeframe, start, end) -> pd.DataFrame: ...
    def fetch_latest_bars(self, symbol, exchange, timeframe, n_bars=200) -> pd.DataFrame: ...
```

### `src/execution/bar_close_detector.py` — `BarCloseDetector`
Subscribe to ZeroMQ port 8765, detect bar close events, fire callbacks.

```python
class BarCloseDetector:
    def __init__(self, ws_port=8765, symbol="RELIANCE", timeframe="15m"): ...
    def register_callback(self, fn: Callable[[dict], None]): ...
    def start(self): ...  # blocking
    def stop(self): ...
```
> ⚠️ Read OpenAlgo `websocket.py` source to verify ZeroMQ message format before building.

### `src/execution/order_router.py` — `OpenAlgoOrderRouter`
Accept `Recommendation` → POST `/api/v1/placeorder` → log fills.

```python
@dataclass
class Recommendation:
    symbol: str
    direction: int        # +1 long, -1 short, 0 flat
    confidence: float
    entry_price: float
    take_profit: float
    stop_loss: float
    timeframe: str
    timestamp: pd.Timestamp

class OpenAlgoOrderRouter:
    def __init__(self, api_key, base_url, paper_trade=True, qty=1): ...
    def route(self, rec: Recommendation) -> dict: ...
```

### `src/execution/paper_trade_bridge.py` — `OpenAlgoPaperTradeBridge`
Collect sandbox fills → CSV → running win rate vs model predictions.

```python
@dataclass
class PaperTradeRecord:
    timestamp, symbol, direction, entry_price, exit_price, pnl, model_confidence, actual_win

class OpenAlgoPaperTradeBridge:
    def __init__(self, output_path: str): ...
    def record_fill(self, rec: Recommendation, fill_price: float): ...
    def record_exit(self, symbol: str, exit_price: float): ...
    def running_win_rate(self) -> float: ...
```

### `src/execution/inference_scheduler.py` — `InferenceScheduler`
Orchestrate full cycle: bar close → data → indicators → inference → order.

```python
class InferenceScheduler:
    def __init__(self, bundle_path, data_adapter, bar_detector, order_router, paper_bridge, config): ...
    def on_bar_close(self, bar: dict):
        # 1. Fetch latest N bars
        # 2. Run strategy indicators
        # 3. Compute regime features
        # 4. Regime model predict
        # 5. Setup ranker score
        # 6. Build Recommendation
        # 7. Log + route if confidence >= threshold
        # 8. Record paper trade
        ...
    def start(self):
        self.bar_detector.register_callback(self.on_bar_close)
        self.bar_detector.start()
```

---

## Existing File Changes

### `configs/reliance_swing_live.yaml` (new config for live use)
```yaml
# Extend reliance_swing_optimized_v2.yaml with:
openalgo_api_key: "your_api_key_here"
openalgo_base_url: "http://localhost:5000"
use_live_data: false       # flip to true when ready
paper_trade: true          # flip to false after 30 paper signals
order_qty: 1
min_confidence: 0.60
exchange: "NSE"
```

### `src/core/constants.py` (add constants)
```python
OPENALGO_BASE_URL = "http://localhost:5000"
OPENALGO_WS_PORT = 8765
OPENALGO_API_VERSION = "v1"
```

### `src/inference/generate_reliance_swing_recommendation.py` (add data_source param)
```python
def generate_recommendation(config, data_source="csv", n_bars=500) -> Recommendation:
    if data_source == "openalgo":
        adapter = OpenAlgoDataAdapter(config["openalgo_api_key"], config["openalgo_base_url"])
        primary_df = adapter.fetch_latest_bars(...)
    else:
        primary_df = pd.read_csv(...)
    # rest unchanged
```

---

## Phased Build Plan

| Phase | What | Gate |
|---|---|---|
| **1 — Data Bridge** | Build `OpenAlgoDataAdapter`, verify same OHLCV shape, run offline inference with live data | `fetch_latest_bars()` matches CSV columns |
| **2 — Bar-Close Trigger** | `BarCloseDetector` + `InferenceScheduler` (print only) | Recommendation prints on every 15m bar close |
| **3 — Paper Trading** | `OpenAlgoOrderRouter` (sandbox) + `OpenAlgoPaperTradeBridge` | ≥30 paper trades logged; running WR ≥ 80% of in-sample WR |
| **4 — Live Trading** | Flip `paper_trade: false`, add position guard | Manual review of 5 live trades before scaling |
| **5 — Multi-Symbol** | Parameterize per symbol/TF, run optimizer per symbol | Each symbol passes 30-signal paper gate independently |

---

## Critical Prerequisites Before Going Live

1. **Holdout validation** — split data 70/30, re-run combo search on train only, measure on holdout
2. **30 paper trades** — minimum before real money
3. **Regime model honesty** — current model is near-random (0.357 vs 0.333 baseline); do NOT use for position sizing yet
4. **Verify ZeroMQ message format** — read OpenAlgo `websocket.py` before building `BarCloseDetector`
5. **Verify broker symbol codes** — RELIANCE symbol format varies by broker in OpenAlgo

---

## Output Locations

| Artifact | Path |
|---|---|
| Paper trade log | `artifacts_template/reports/paper_trades/paper_trades.csv` |
| Live config | `configs/reliance_swing_live.yaml` |
| Order logs | `artifacts_template/reports/order_logs/` |
| New module tests | `tests/test_openalgo_adapter.py`, `tests/test_inference_scheduler.py` |
