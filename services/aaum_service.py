import os
from typing import Any

import httpx

from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Runtime-mutable AAUM URL (can be changed via /api/v1/aaum/config POST)
# ---------------------------------------------------------------------------
_aaum_url: str = os.getenv("AAUM_URL", "http://localhost:8080")

# Fallback local URL when Colab tunnel is unreachable
_LOCAL_AAUM_URL = "http://localhost:8080"

# Timeouts: analysis is compute-heavy (600s for 9 agents + data collection), others are fast (30s)
ANALYSIS_TIMEOUT = float(os.getenv("AAUM_ANALYSIS_TIMEOUT", "600"))
DEFAULT_TIMEOUT = float(os.getenv("AAUM_DEFAULT_TIMEOUT", "30"))

# Colab tunnel URLs get a longer connect timeout (tunnels are slower to handshake)
_COLAB_CONNECT_TIMEOUT = 30.0
_LOCAL_CONNECT_TIMEOUT = 10.0


def get_aaum_url() -> str:
    """Return the current AAUM base URL (runtime-mutable)."""
    return _aaum_url


def set_aaum_url(url: str) -> None:
    """Set AAUM base URL at runtime (no restart needed)."""
    global _aaum_url
    _aaum_url = url.rstrip("/")
    logger.info(f"AAUM URL updated to: {_aaum_url}")


def is_colab_url(url: str | None = None) -> bool:
    """Check if the URL points to a Colab tunnel (Cloudflare or ngrok)."""
    u = (url or _aaum_url).lower()
    return "trycloudflare.com" in u or "ngrok" in u


def _detect_backend_label(url: str | None = None) -> str:
    """Return a human-readable label for the current backend: colab / local / mock."""
    u = url or _aaum_url
    if is_colab_url(u):
        return "colab"
    if "localhost" in u or "127.0.0.1" in u:
        return "local"
    return "remote"


def _make_client(timeout: float, base_url: str | None = None) -> httpx.Client:
    """Create an httpx client with the given timeout."""
    url = base_url or _aaum_url
    connect_timeout = _COLAB_CONNECT_TIMEOUT if is_colab_url(url) else _LOCAL_CONNECT_TIMEOUT
    return httpx.Client(
        base_url=url,
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        headers={"Content-Type": "application/json"},
    )


def _try_request(
    method: str,
    path: str,
    timeout: float,
    json: dict | None = None,
) -> httpx.Response | None:
    """
    Try the primary AAUM URL first. If it fails and the primary is a Colab
    tunnel, retry against localhost:8080 as fallback.
    Returns the response or None if all attempts fail.
    """
    primary = _aaum_url
    urls_to_try = [primary]
    # If primary is a Colab tunnel, also try local as fallback
    if is_colab_url(primary) and _LOCAL_AAUM_URL != primary:
        urls_to_try.append(_LOCAL_AAUM_URL)

    last_err: Exception | None = None
    for url in urls_to_try:
        label = _detect_backend_label(url)
        try:
            logger.info(f"AAUM request: {method.upper()} {url}{path} (backend={label})")
            with _make_client(timeout, base_url=url) as client:
                if method == "post":
                    resp = client.post(path, json=json)
                else:
                    resp = client.get(path)
            logger.info(f"AAUM response: {resp.status_code} from {label}")
            return resp
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"AAUM {label} ({url}) unreachable: {e}")
            last_err = e
            continue
        except Exception as e:
            logger.warning(f"AAUM {label} ({url}) error: {e}")
            last_err = e
            continue

    if last_err:
        logger.warning(f"All AAUM backends failed. Last error: {last_err}")
    return None


def check_health() -> dict[str, Any]:
    """
    Check AAUM backend health. Probes the configured URL (and local fallback).
    Returns a dict with status, backend label, and reachability of each target.
    """
    results: dict[str, Any] = {
        "configured_url": _aaum_url,
        "backend": _detect_backend_label(),
        "is_colab": is_colab_url(),
        "colab": {"reachable": False, "status_code": None, "url": None},
        "local": {"reachable": False, "status_code": None, "url": _LOCAL_AAUM_URL},
    }

    # Check Colab / primary URL
    if is_colab_url():
        results["colab"]["url"] = _aaum_url
        try:
            with _make_client(10.0, base_url=_aaum_url) as client:
                resp = client.get("/health")
            results["colab"]["reachable"] = resp.status_code < 500
            results["colab"]["status_code"] = resp.status_code
        except Exception as e:
            results["colab"]["error"] = str(e)

    # Check local
    try:
        with _make_client(5.0, base_url=_LOCAL_AAUM_URL) as client:
            resp = client.get("/health")
        results["local"]["reachable"] = resp.status_code < 500
        results["local"]["status_code"] = resp.status_code
    except Exception as e:
        results["local"]["error"] = str(e)

    # Overall status
    any_reachable = results["colab"]["reachable"] or results["local"]["reachable"]
    if any_reachable:
        results["status"] = "healthy"
    else:
        results["status"] = "offline"

    return results


def _transform_aaum_response(raw: dict[str, Any], symbol: str) -> dict[str, Any]:
    """
    Transform AAUM's flat analysis response into the 7-panel structure
    that the frontend AnalysisResultSchema (Zod) expects.

    AAUM returns: status, query, consensus, agent_analyses, risk_assessment, etc.
    Frontend expects: symbol, action, confidence, equity_signal, layers, agent_debate, etc.
    """
    import uuid
    from datetime import datetime

    # Handle rejected status — still show useful data
    is_rejected = raw.get("status") == "rejected"

    # Map consensus to action
    consensus = (raw.get("consensus") or raw.get("ensemble_recommendation") or "NO_ACTION").upper()
    action = consensus if consensus in ("BUY", "SELL", "HOLD", "NO_ACTION") else "NO_ACTION"

    # Confidence: use ensemble_confidence or consensus_confidence
    confidence = raw.get("ensemble_confidence") or raw.get("consensus_confidence") or 0.0
    if isinstance(confidence, float) and confidence <= 1.0:
        confidence = int(confidence * 100)

    # If agents ran, compute confidence from their individual scores
    agents_list = raw.get("agent_analyses") or []
    if agents_list and confidence == 0:
        agent_confs = []
        for a in agents_list:
            c = a.get("confidence", 0)
            if isinstance(c, float) and c <= 1.0:
                c = int(c * 100)
            agent_confs.append(c)
        confidence = int(sum(agent_confs) / len(agent_confs)) if agent_confs else 0

    # Build agent debate from agent_analyses
    agents = raw.get("agent_analyses") or []
    bulls, bears, neutrals = [], [], []
    for agent in agents:
        agent_entry = {
            "agent_name": agent.get("agent_name", agent.get("name", "Unknown")),
            "action": (agent.get("recommendation", agent.get("action", "HOLD"))).upper(),
            "confidence": int(float(agent.get("confidence", 50)) * 100) if float(agent.get("confidence", 50)) <= 1.0 else int(agent.get("confidence", 50)),
            "reasoning": agent.get("reasoning", agent.get("analysis", "No reasoning")),
            "key_metrics": agent.get("key_metrics", agent.get("metrics", {})),
        }
        rec = agent_entry["action"]
        if rec == "BUY":
            bulls.append(agent_entry)
        elif rec == "SELL":
            bears.append(agent_entry)
        else:
            neutrals.append(agent_entry)

    # Real 12-layer names from AAUM architecture
    LAYER_NAMES = [
        "Growth", "Value", "Momentum", "Quant", "Macro", "Sentiment",
        "Sector", "Options", "Risk", "Portfolio", "Exit", "Execution",
    ]
    # Map agents to layers (agents correspond to layers 1-9)
    agent_map = {}
    for agent in agents:
        name = (agent.get("agent_name") or agent.get("name") or "").lower()
        for i, ln in enumerate(LAYER_NAMES):
            if ln.lower() in name or name in ln.lower():
                agent_map[i] = agent
                break

    layers = []
    for i in range(12):
        agent = agent_map.get(i)
        if agent:
            rec = (agent.get("recommendation") or agent.get("action") or "HOLD").upper()
            sig = "bullish" if rec == "BUY" else "bearish" if rec == "SELL" else "neutral"
            conf = agent.get("confidence", 50)
            if isinstance(conf, float) and conf <= 1.0:
                conf = int(conf * 100)
            reasoning = agent.get("reasoning") or agent.get("analysis") or "Agent analysis complete"
        else:
            sig = "bullish" if action == "BUY" else "bearish" if action == "SELL" else "neutral"
            conf = max(int(confidence), 1)
            reasoning = "No dedicated agent for this layer"

        layers.append({
            "layer_number": i + 1,
            "layer_name": LAYER_NAMES[i],
            "signal": sig,
            "confidence": max(int(conf), 1),
            "reasoning": reasoning,
        })

    # Safety / risk
    safety_passed = raw.get("safety_passed", False)
    risk_decision = "APPROVE" if safety_passed else "REJECT"
    survival = 75 if safety_passed else 30
    violations = raw.get("safety_violations") or []
    veto_reason = "; ".join(str(v) for v in violations) if violations else None

    # If rejected by deterministic gate, mark it clearly but still show data
    if is_rejected and not agents_list:
        # No agents ran — provide informative defaults
        confidence = max(confidence, 10)  # Show at least some value
        risk_decision = "REJECT"
        survival = 20
        if not veto_reason:
            veto_reason = "Deterministic safety gate rejected before agent analysis"

    # Confluence from buy/sell scores
    buy_score = raw.get("buy_score", 0) or 0
    sell_score = raw.get("sell_score", 0) or 0
    confluence = max(int((buy_score + sell_score) * 50), int(confidence))

    return {
        "symbol": symbol.upper(),
        "action": action,
        "confidence": int(confidence),
        "confluence": max(confluence, 1),
        "total_layers": 12,
        "regime": "neutral",
        "equity_signal": {
            "entry_price": 0,
            "stop_loss": 0,
            "target_1": 0,
            "target_2": None,
            "target_3": None,
            "rr_ratio": 0,
            "atr_14": 0,
            "position_size_pct": 0,
            "quantity": 0,
            "lot_size": None,
        },
        "options_strategy": None,
        "layers": layers,
        "agent_debate": {
            "bulls": bulls,
            "bears": bears,
            "neutral": neutrals,
            "conviction_pct": int(confidence),
            "verdict": action,
        },
        "portfolio": None,
        "survival_score": survival,
        "risk_decision": risk_decision,
        "veto_reason": veto_reason,
        "analysis_id": raw.get("feedback_id") or str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
    }


def analyze_mock(symbol: str) -> dict[str, Any]:
    """
    Return a realistic mock AnalysisResponse matching the frontend Zod schema.
    Used for demo/testing during off-market hours when AAUM is unavailable.
    """
    import uuid
    import random
    from datetime import datetime

    symbol = symbol.upper()

    # Per-stock mock prices to make data look realistic
    STOCK_DATA = {
        "RELIANCE": {"price": 2485.60, "atr": 42.5, "lot": 250},
        "SBIN":     {"price": 788.35,  "atr": 15.8, "lot": 1500},
        "INFY":     {"price": 1542.20, "atr": 28.3, "lot": 600},
        "TCS":      {"price": 3890.75, "atr": 55.1, "lot": 175},
        "HDFC":     {"price": 1625.40, "atr": 31.2, "lot": 550},
        "HDFCBANK": {"price": 1625.40, "atr": 31.2, "lot": 550},
    }
    sd = STOCK_DATA.get(symbol, {"price": 1000.0, "atr": 20.0, "lot": 500})
    price = sd["price"]
    atr = sd["atr"]
    lot = sd["lot"]

    # Derive entry/SL/targets from price and ATR
    entry = round(price, 2)
    sl = round(price - 1.5 * atr, 2)
    t1 = round(price + 2.0 * atr, 2)
    t2 = round(price + 3.5 * atr, 2)
    t3 = round(price + 5.0 * atr, 2)
    rr = round((t1 - entry) / (entry - sl), 2) if entry != sl else 2.0

    # Seed RNG per symbol for deterministic but varied results
    rng = random.Random(hash(symbol) & 0xFFFFFFFF)

    # 12-layer confluence map with realistic signals
    LAYER_NAMES = [
        "Growth", "Value", "Momentum", "Quant", "Macro", "Sentiment",
        "Sector", "Options", "Risk", "Portfolio", "Exit", "Execution",
    ]
    LAYER_REASONINGS = {
        "Growth":    f"Revenue CAGR 18.2% (3Y), EPS growth 22% YoY. {symbol} shows strong topline expansion.",
        "Value":     f"P/E 24.3 vs sector median 28.1. P/B 3.8 within 1-sigma band. Fairly valued with margin of safety.",
        "Momentum":  f"RSI(14) = 58.3, MACD bullish crossover 2 days ago. ADX 26.4 confirms emerging trend.",
        "Quant":     f"Alpha factor score 0.72, Sharpe 1.34 (rolling 60d). Z-score mean-reversion signal at +0.8 sigma.",
        "Macro":     f"RBI policy neutral, INR/USD stable at 83.2. 10Y yield 7.15% — no headwinds for equity.",
        "Sentiment": f"FII net buyers 3/5 sessions. Put-Call ratio 0.82 (mildly bullish). Social sentiment score +0.64.",
        "Sector":    f"Sector relative strength +4.2% vs Nifty50 (20d). Sector rotation model: mid-cycle accumulation.",
        "Options":   f"IV percentile 38, max pain at {round(price * 0.98, 0)}. OI buildup supports {round(price * 1.02, 0)} CE writers unwinding.",
        "Risk":      f"VaR(95%) = {round(atr * 2.2, 1)}, CVaR = {round(atr * 3.1, 1)}. Drawdown from ATH: -8.3%. Within risk budget.",
        "Portfolio":  f"Current allocation 4.2%. Suggested 5.5% (+1.3%). Correlation with portfolio: 0.41 — diversification benefit.",
        "Exit":      f"Trailing stop at {round(price - 1.2 * atr, 2)}. Time-stop: 15 sessions. Profit target hit probability 68%.",
        "Execution": f"Avg daily volume {rng.randint(8, 25)}M shares. Bid-ask spread 0.02%. Slippage estimate: 0.05%. Ready to execute.",
    }

    layers = []
    bullish_count = 0
    for i, name in enumerate(LAYER_NAMES):
        # Most layers bullish for a BUY signal, a few neutral for realism
        if name in ("Risk", "Portfolio", "Exit"):
            sig = rng.choice(["bullish", "bullish", "neutral"])
        else:
            sig = rng.choice(["bullish", "bullish", "bullish", "neutral"])
        conf = rng.randint(62, 92) if sig == "bullish" else rng.randint(40, 58)
        if sig == "bullish":
            bullish_count += 1
        layers.append({
            "layer_number": i + 1,
            "layer_name": name,
            "signal": sig,
            "confidence": conf,
            "reasoning": LAYER_REASONINGS[name],
        })

    # 9 agents for debate
    AGENTS = [
        ("Rakesh (Growth)",     "BUY",  rng.randint(70, 90), f"Strong earnings momentum. {symbol} revenue beat estimates by 6%."),
        ("Graham (Value)",      "BUY",  rng.randint(65, 85), f"Trading below intrinsic value. DCF target {round(price * 1.18, 0)} implies 18% upside."),
        ("Momentum Agent",      "BUY",  rng.randint(68, 88), f"Breakout above 20-DMA with volume confirmation. MACD histogram expanding."),
        ("Quant Agent",         "BUY",  rng.randint(60, 82), f"Multi-factor alpha score in top decile. Statistical edge: +1.2% expected 5-day return."),
        ("Rajan (Macro)",       "HOLD", rng.randint(50, 65), f"Macro environment neutral. No policy catalysts near-term but no headwinds either."),
        ("Pulse (Sentiment)",   "BUY",  rng.randint(62, 80), f"Social sentiment +0.64, news flow positive. FII accumulation detected."),
        ("Rotation (Sector)",   "BUY",  rng.randint(65, 85), f"Sector in accumulation phase. Relative strength rank: top 3 in Nifty50."),
        ("Deriv (Options)",     "BUY",  rng.randint(58, 78), f"OI data supports upside. PCR 0.82, max pain rising. IV crush post-results favorable."),
        ("Risk Agent",          "HOLD", rng.randint(55, 70), f"Position within risk limits. VaR acceptable. Suggest trailing stop at {sl}."),
    ]

    bulls, bears, neutrals = [], [], []
    for agent_name, action, conf, reasoning in AGENTS:
        entry_data = {
            "agent_name": agent_name,
            "action": action,
            "confidence": conf,
            "reasoning": reasoning,
            "key_metrics": {},
        }
        if action == "BUY":
            bulls.append(entry_data)
        elif action == "SELL":
            bears.append(entry_data)
        else:
            neutrals.append(entry_data)

    overall_confidence = int(sum(a[2] for a in AGENTS) / len(AGENTS))

    # Nearest monthly expiry placeholder
    expiry_str = "2026-03-26"

    # Build CE strike near ATM
    ce_strike = round(price / 50) * 50  # Round to nearest 50

    return {
        "symbol": symbol,
        "action": "BUY",
        "confidence": overall_confidence,
        "confluence": bullish_count,
        "total_layers": 12,
        "regime": "bull",
        "equity_signal": {
            "entry_price": entry,
            "stop_loss": sl,
            "target_1": t1,
            "target_2": t2,
            "target_3": t3,
            "rr_ratio": rr,
            "atr_14": atr,
            "position_size_pct": 5.5,
            "quantity": lot,
            "lot_size": lot,
        },
        "options_strategy": {
            "strategy_name": "Bull Call Spread",
            "legs": [
                {
                    "action": "BUY",
                    "strike": ce_strike,
                    "option_type": "CE",
                    "premium": round(atr * 1.8, 2),
                    "quantity": lot,
                },
                {
                    "action": "SELL",
                    "strike": ce_strike + round(atr * 3, -1),
                    "option_type": "CE",
                    "premium": round(atr * 0.7, 2),
                    "quantity": lot,
                },
            ],
            "greeks": {
                "delta": 0.42,
                "gamma": 0.008,
                "theta": -12.5,
                "vega": 18.3,
            },
            "pop": 62.0,
            "max_profit": round(atr * 3 * lot * 0.6, 2),
            "max_loss": round(atr * 1.1 * lot * 0.3, 2),
            "breakeven": [round(ce_strike + atr * 1.1, 2)],
        },
        "layers": layers,
        "agent_debate": {
            "bulls": bulls,
            "bears": bears,
            "neutral": neutrals,
            "conviction_pct": overall_confidence,
            "verdict": "BUY",
        },
        "portfolio": {
            "positions": [
                {
                    "symbol": symbol,
                    "exchange": "NSE",
                    "quantity": 0,
                    "avg_price": 0.0,
                    "ltp": price,
                    "pnl": 0.0,
                },
            ],
            "total_pnl": 0.0,
        },
        "survival_score": rng.randint(68, 85),
        "risk_decision": "APPROVE",
        "veto_reason": None,
        "analysis_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
    }


def analyze(symbol: str, config: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any], int]:
    """
    Proxy to AAUM POST /api/v1/analysis/run.
    Transforms AAUM response into the frontend's 7-panel AnalysisResultSchema.

    Retry logic:
      1. Try configured AAUM URL (may be Colab tunnel)
      2. If Colab fails, try localhost:8080
      3. If all fail, return mock data

    Args:
        symbol: Trading symbol to analyze (e.g. "SBIN", "RELIANCE")
        config: Optional analysis configuration dict

    Returns:
        Tuple of (success, response_data, http_status_code)
    """
    payload: dict[str, Any] = {
        "query": symbol,
        "include_safety": False,  # Skip Piotroski/safety pre-gate so agents run
        "include_search": False,  # Skip web search (faster, no Perplexica needed)
    }
    if config:
        payload.update(config)

    try:
        resp = _try_request("post", "/api/v1/analysis/run", ANALYSIS_TIMEOUT, json=payload)

        if resp is None:
            # All backends unreachable — fall back to mock
            backend = _detect_backend_label()
            logger.warning(
                f"AAUM unreachable (tried {backend}) — falling back to mock data for {symbol}"
            )
            mock = analyze_mock(symbol)
            mock["_mock"] = True
            mock["_mock_reason"] = f"AAUM server unreachable at {_aaum_url}"
            mock["_backend"] = "mock"
            return True, {"status": "success", "data": mock}, 200

        data = resp.json()

        if resp.status_code >= 400:
            logger.warning(f"AAUM analysis returned {resp.status_code} for {symbol}: {data}")
            return False, {
                "status": "error",
                "message": data.get("detail", data.get("message", "AAUM analysis failed")),
            }, resp.status_code

        # Transform AAUM's flat response into the frontend's 7-panel schema
        transformed = _transform_aaum_response(data, symbol)
        transformed["_backend"] = _detect_backend_label()
        return True, {"status": "success", "data": transformed}, resp.status_code

    except Exception as e:
        logger.exception(f"Unexpected error calling AAUM analysis: {e}")
        return False, {
            "status": "error",
            "message": f"AAUM communication error: {str(e)}",
        }, 500


def get_trade_card(symbol: str) -> tuple[bool, dict[str, Any], int]:
    """
    Proxy to AAUM POST /api/v3/trade-card/{symbol}.

    Args:
        symbol: Trading symbol (e.g. "SBIN", "RELIANCE")

    Returns:
        Tuple of (success, response_data, http_status_code)
    """
    try:
        resp = _try_request("post", f"/api/v3/trade-card/{symbol}", DEFAULT_TIMEOUT)

        if resp is None:
            return False, {
                "status": "error",
                "message": f"AAUM server unreachable at {_aaum_url}",
            }, 503

        data = resp.json()

        if resp.status_code >= 400:
            logger.warning(f"AAUM trade-card returned {resp.status_code} for {symbol}: {data}")
            return False, {
                "status": "error",
                "message": data.get("detail", data.get("message", "AAUM trade-card failed")),
            }, resp.status_code

        return True, {"status": "success", "data": data}, resp.status_code

    except Exception as e:
        logger.exception(f"Unexpected error calling AAUM trade-card: {e}")
        return False, {
            "status": "error",
            "message": f"AAUM communication error: {str(e)}",
        }, 500


def execute_trade(trade_intent: dict[str, Any]) -> tuple[bool, dict[str, Any], int]:
    """
    Forward a TradeIntent to AAUM for execution via POST /api/v1/execute.

    Args:
        trade_intent: TradeIntent dict from AAUM trade-card
                      (contains symbol, action, quantity, order_type, etc.)

    Returns:
        Tuple of (success, response_data, http_status_code)
    """
    try:
        resp = _try_request("post", "/api/v1/execute", DEFAULT_TIMEOUT, json=trade_intent)

        if resp is None:
            return False, {
                "status": "error",
                "message": f"AAUM server unreachable at {_aaum_url}",
            }, 503

        data = resp.json()

        if resp.status_code >= 400:
            logger.warning(f"AAUM execute returned {resp.status_code}: {data}")
            return False, {
                "status": "error",
                "message": data.get("detail", data.get("message", "AAUM execute failed")),
            }, resp.status_code

        return True, {"status": "success", "data": data}, resp.status_code

    except Exception as e:
        logger.exception(f"Unexpected error calling AAUM execute: {e}")
        return False, {
            "status": "error",
            "message": f"AAUM communication error: {str(e)}",
        }, 500
