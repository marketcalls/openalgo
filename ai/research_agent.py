"""Autonomous Financial Research Agent — inspired by virattt/dexter.

Takes a stock symbol (+ optional question) and generates a comprehensive
research report by orchestrating all available OpenAlgo AI modules.

Unlike Dexter (TypeScript), this runs entirely in Python using existing
OpenAlgo infrastructure — no external API keys required beyond Ollama/Gemini.
"""

from __future__ import annotations

from datetime import datetime, timezone

from utils.logging import get_logger

logger = get_logger(__name__)


def _safe(fn, *args, label="module", default=None, **kwargs):
    """Run function safely, return (result, error_msg)."""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        logger.warning("Research agent — %s failed: %s", label, e)
        return default, str(e)


def run_research(
    symbol: str,
    exchange: str = "NSE",
    question: str = "",
    api_key: str = "",
) -> dict:
    """Run autonomous financial research on a symbol.

    Executes a multi-step research plan:
    1. Technical Analysis (signals, indicators, regime)
    2. Strategy Analysis (Fibonacci, SMC, Elliott Wave confluence)
    3. News Sentiment (recent headlines + aggregate sentiment)
    4. Multi-Timeframe (confluence across 6 timeframes)
    5. Risk Assessment (hedge analytics, volatility regime)
    6. Support/Resistance (key levels)
    7. Synthesis (combine all findings into actionable report)

    Args:
        symbol: Stock symbol (e.g., "RELIANCE")
        exchange: Exchange (NSE/BSE)
        question: Optional specific question (e.g., "Should I buy RELIANCE?")
        api_key: OpenAlgo API key

    Returns:
        Comprehensive research report dict.
    """
    if not question:
        question = f"Should I invest in {symbol}? What are the key risks and opportunities?"

    steps = []
    findings = {}

    # ─── Step 1: Technical Analysis ───
    steps.append({"step": 1, "task": "Technical Analysis", "status": "running"})
    tech_data, tech_err = _run_technical(symbol, exchange, api_key)
    steps[-1]["status"] = "done" if tech_data else "failed"
    steps[-1]["error"] = tech_err
    findings["technical"] = tech_data

    # ─── Step 2: Strategy Confluence ───
    steps.append({"step": 2, "task": "Strategy Confluence", "status": "running"})
    strategy_data, strat_err = _run_strategy_decision(symbol, exchange, api_key)
    steps[-1]["status"] = "done" if strategy_data else "failed"
    steps[-1]["error"] = strat_err
    findings["strategy"] = strategy_data

    # ─── Step 3: News Sentiment ───
    steps.append({"step": 3, "task": "News Sentiment", "status": "running"})
    news_data, news_err = _run_news(symbol, exchange)
    steps[-1]["status"] = "done" if news_data else "failed"
    steps[-1]["error"] = news_err
    findings["news"] = news_data

    # ─── Step 4: Multi-Timeframe ───
    steps.append({"step": 4, "task": "Multi-Timeframe Analysis", "status": "running"})
    mtf_data, mtf_err = _run_multi_timeframe(symbol, exchange, api_key)
    steps[-1]["status"] = "done" if mtf_data else "failed"
    steps[-1]["error"] = mtf_err
    findings["multi_timeframe"] = mtf_data

    # ─── Step 5: Risk Assessment ───
    steps.append({"step": 5, "task": "Risk Assessment", "status": "running"})
    risk_data, risk_err = _run_risk(symbol, exchange, api_key)
    steps[-1]["status"] = "done" if risk_data else "failed"
    steps[-1]["error"] = risk_err
    findings["risk"] = risk_data

    # ─── Step 6: Key Levels ───
    steps.append({"step": 6, "task": "Support & Resistance", "status": "running"})
    levels_data, levels_err = _run_levels(symbol, exchange, api_key)
    steps[-1]["status"] = "done" if levels_data else "failed"
    steps[-1]["error"] = levels_err
    findings["levels"] = levels_data

    # ─── Step 7: Synthesize Report ───
    steps.append({"step": 7, "task": "Synthesize Findings", "status": "running"})
    report = _synthesize(symbol, exchange, question, findings)
    steps[-1]["status"] = "done"

    completed = sum(1 for s in steps if s["status"] == "done")
    failed = sum(1 for s in steps if s["status"] == "failed")

    return {
        "symbol": symbol,
        "exchange": exchange,
        "question": question,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps_completed": completed,
        "steps_failed": failed,
        "steps": steps,
        "report": report,
        "findings": findings,
    }


# ─── Research Step Implementations ────────────────────────────────────

def _run_technical(symbol: str, exchange: str, api_key: str):
    from services.ai_analysis_service import analyze_symbol
    r = analyze_symbol(symbol, exchange, "D", api_key)
    if not r.success:
        return None, r.error
    return {
        "signal": r.signal,
        "confidence": r.confidence,
        "score": round(r.score or 0, 4),
        "regime": r.regime,
        "sub_scores": r.sub_scores,
        "indicators": {
            "rsi": r.latest_indicators.get("rsi_14"),
            "macd": r.latest_indicators.get("macd"),
            "adx": r.latest_indicators.get("adx_14"),
            "atr": r.latest_indicators.get("atr_14"),
        },
        "trade_setup": r.trade_setup,
    }, None


def _run_strategy_decision(symbol: str, exchange: str, api_key: str):
    from services.strategy_analysis_service import analyze_strategy_decision
    return analyze_strategy_decision(symbol, exchange, "D", api_key), None


def _run_news(symbol: str, exchange: str):
    from ai.news_sentiment import analyze_news_sentiment
    result = analyze_news_sentiment(symbol, exchange, max_per_source=5)
    return {
        "overall_label": result["overall_sentiment"]["label"],
        "compound": result["overall_sentiment"]["compound"],
        "bullish_count": result["overall_sentiment"]["bullish_count"],
        "bearish_count": result["overall_sentiment"]["bearish_count"],
        "total_articles": result["total_articles"],
        "top_headlines": [
            {"title": a["title"], "label": a["label"], "source": a["source"]}
            for a in result["articles"][:5]
        ],
    }, None


def _run_multi_timeframe(symbol: str, exchange: str, api_key: str):
    from services.strategy_analysis_service import analyze_multi_timeframe
    result = analyze_multi_timeframe(symbol, exchange, api_key)
    return {
        "signal": result["confluence"]["signal"],
        "confidence": result["confluence"]["confidence"],
        "agreement_pct": result["confluence"]["agreement_pct"],
        "aligned": result["confluence"]["aligned_timeframes"],
        "conflicting": result["confluence"]["conflicting_timeframes"],
    }, None


def _run_risk(symbol: str, exchange: str, api_key: str):
    from services.strategy_analysis_service import analyze_hedge_strategy
    result = analyze_hedge_strategy(symbol, exchange, "D", api_key)
    fs = result.get("from_scratch", {})
    return {
        "zscore": fs.get("mean_reversion", {}).get("current_zscore"),
        "momentum_signal": fs.get("momentum", {}).get("signal"),
        "momentum_composite": fs.get("momentum", {}).get("composite"),
        "vol_regime": fs.get("volatility_regime", {}).get("regime"),
        "vol_percentile": fs.get("volatility_regime", {}).get("vol_percentile"),
        "sharpe": fs.get("risk_metrics", {}).get("sharpe_ratio"),
        "max_dd": fs.get("risk_metrics", {}).get("max_drawdown_pct"),
        "var_95": fs.get("risk_metrics", {}).get("var_95"),
    }, None


def _run_levels(symbol: str, exchange: str, api_key: str):
    from services.strategy_analysis_service import analyze_support_resistance
    return analyze_support_resistance(symbol, exchange, "D", api_key), None


# ─── Synthesis ────────────────────────────────────────────────────────

def _synthesize(symbol: str, exchange: str, question: str, findings: dict) -> dict:
    """Combine all findings into a structured research report."""

    # Extract key data points
    tech = findings.get("technical") or {}
    strat = findings.get("strategy") or {}
    news = findings.get("news") or {}
    mtf = findings.get("multi_timeframe") or {}
    risk = findings.get("risk") or {}
    levels = findings.get("levels") or {}

    # Determine overall verdict
    signals = []
    if tech.get("signal"):
        signals.append(("Technical", tech["signal"], tech.get("confidence", 0)))
    if strat.get("action"):
        signals.append(("Strategy", strat["action"], strat.get("confluence", {}).get("score", 0)))
    if mtf.get("signal"):
        signals.append(("Multi-TF", mtf["signal"], mtf.get("confidence", 0)))

    bullish_signals = sum(1 for _, s, _ in signals if s in ("STRONG_BUY", "BUY"))
    bearish_signals = sum(1 for _, s, _ in signals if s in ("STRONG_SELL", "SELL"))

    if bullish_signals > bearish_signals:
        verdict = "BULLISH"
        verdict_detail = "Multiple analysis modules agree on bullish outlook"
    elif bearish_signals > bullish_signals:
        verdict = "BEARISH"
        verdict_detail = "Multiple analysis modules agree on bearish outlook"
    else:
        verdict = "NEUTRAL"
        verdict_detail = "Mixed signals — no clear directional consensus"

    # Confidence (average across modules)
    confidences = [c for _, _, c in signals if c > 0]
    avg_confidence = round(sum(confidences) / len(confidences)) if confidences else 0

    # Build reasoning
    reasoning = []

    if tech.get("signal"):
        reasoning.append(f"Technical signal: {tech['signal']} with {tech.get('confidence', 0)}% confidence")
    if tech.get("regime"):
        reasoning.append(f"Market regime: {tech['regime']}")
    if tech.get("indicators", {}).get("rsi"):
        rsi = tech["indicators"]["rsi"]
        if rsi > 70:
            reasoning.append(f"RSI at {rsi:.0f} — overbought territory, pullback risk")
        elif rsi < 30:
            reasoning.append(f"RSI at {rsi:.0f} — oversold territory, potential bounce")
        else:
            reasoning.append(f"RSI at {rsi:.0f} — in normal range")

    if strat.get("confluence", {}).get("votes"):
        bull = strat["confluence"].get("bullish_count", 0)
        bear = strat["confluence"].get("bearish_count", 0)
        reasoning.append(f"Strategy confluence: {bull} bullish, {bear} bearish modules")

    if news.get("total_articles"):
        reasoning.append(f"News sentiment: {news['overall_label']} ({news['total_articles']} articles)")

    if mtf.get("agreement_pct"):
        reasoning.append(f"Multi-TF agreement: {mtf['agreement_pct']}% across timeframes")

    if risk.get("vol_regime"):
        reasoning.append(f"Volatility regime: {risk['vol_regime']} (percentile: {risk.get('vol_percentile', 'N/A')})")
    if risk.get("sharpe") is not None:
        reasoning.append(f"Risk-adjusted return: Sharpe {risk['sharpe']}, Max DD {risk.get('max_dd', 'N/A')}%")

    # Risks
    risks = []
    if risk.get("vol_regime") in ("high", "elevated"):
        risks.append("High volatility increases risk of sharp moves against position")
    if risk.get("max_dd") and risk["max_dd"] < -15:
        risks.append(f"Historical max drawdown of {risk['max_dd']}% suggests significant downside risk")
    if risk.get("zscore") and abs(risk["zscore"]) > 2:
        risks.append(f"Z-score at {risk['zscore']:.1f} — extreme deviation from mean, reversion risk")
    if news.get("overall_label") == "Bearish" and verdict == "BULLISH":
        risks.append("News sentiment is bearish despite technical bullishness — sentiment divergence")
    if not risks:
        risks.append("No significant risk factors identified in current analysis")

    # Opportunities
    opportunities = []
    if strat.get("entry"):
        entry = strat["entry"]
        opportunities.append(f"Entry zone: {entry.get('low', 'N/A')} - {entry.get('high', 'N/A')}")
    if strat.get("targets"):
        for t in strat["targets"][:2]:
            opportunities.append(f"Target: {t.get('label', '')} at {t.get('price', 'N/A')} (R:R {t.get('rr_ratio', 'N/A')})")
    if levels.get("pivots", {}).get("s1"):
        opportunities.append(f"Support at {levels['pivots']['s1']}, Resistance at {levels['pivots'].get('r1', 'N/A')}")

    # Build answer to question
    if "buy" in question.lower() or "invest" in question.lower():
        if verdict == "BULLISH":
            answer = f"Based on comprehensive analysis, {symbol} shows a BULLISH setup. "
            answer += f"Technical signals, strategy confluence, and multi-timeframe analysis "
            answer += f"support a buy with {avg_confidence}% average confidence."
        elif verdict == "BEARISH":
            answer = f"{symbol} currently shows BEARISH signals. "
            answer += f"Consider waiting for a reversal or better entry point."
        else:
            answer = f"{symbol} shows MIXED signals. "
            answer += f"There is no clear edge — consider waiting for confirmation."
    else:
        answer = f"Analysis of {symbol}: {verdict} outlook with {avg_confidence}% confidence. "
        answer += f"{len(reasoning)} data points analyzed across {len(signals)} modules."

    return {
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "confidence": avg_confidence,
        "answer": answer,
        "reasoning": reasoning,
        "risks": risks,
        "opportunities": opportunities,
        "signals_summary": [
            {"module": m, "signal": s, "confidence": c}
            for m, s, c in signals
        ],
        "trade_setup": strat.get("entry") and {
            "entry": strat.get("entry"),
            "stop_loss": strat.get("stop_loss"),
            "targets": strat.get("targets", []),
        },
    }
