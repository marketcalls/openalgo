"""Daily Market Report Generator.

Inspired by hgnx/automated-market-report and DMTSource/daily-stock-forecast.
Generates a comprehensive daily market summary using all existing OpenAlgo AI modules.

Sources: OHLCV data, technical signals, news sentiment, strategy analysis.
Output: JSON (for frontend) — no external dependencies beyond what OpenAlgo already has.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from utils.logging import get_logger

logger = get_logger(__name__)

# Major Indian indices and blue chips for overview
MARKET_INDICES = ["NIFTY", "BANKNIFTY"]
NIFTY50_TOP20 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "TITAN", "SUNPHARMA", "WIPRO", "HCLTECH", "ULTRACEMCO",
]


def _safe(fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning("Daily report module %s failed: %s", fn.__name__, e)
        return default


def generate_daily_report(
    symbols: list[str] | None = None,
    exchange: str = "NSE",
    api_key: str = "",
) -> dict:
    """Generate a comprehensive daily market report.

    Args:
        symbols: List of symbols to analyze (default: NIFTY50 top 20)
        exchange: Exchange (NSE/BSE)
        api_key: OpenAlgo API key for data access

    Returns:
        Complete daily report as dict.
    """
    if not symbols:
        symbols = NIFTY50_TOP20

    report_time = datetime.now(timezone.utc).isoformat()

    # 1. Scan all symbols for signals
    symbol_scans = _scan_symbols(symbols, exchange, api_key)

    # 2. Market overview (aggregate from scans)
    overview = _compute_market_overview(symbol_scans)

    # 3. Top movers
    top_gainers, top_losers = _compute_top_movers(symbol_scans)

    # 4. Signal distribution
    signal_dist = _compute_signal_distribution(symbol_scans)

    # 5. Sector analysis (simplified — group by signal direction)
    sector_analysis = _compute_sector_analysis(symbol_scans)

    # 6. News sentiment (aggregate)
    news_summary = _fetch_news_summary(symbols[:5], exchange)

    # 7. Key levels for top symbols
    key_levels = _compute_key_levels(symbols[:5], exchange, api_key)

    # 8. AI commentary (one-line market summary)
    market_summary = _generate_market_summary(overview, signal_dist, top_gainers, top_losers)

    return {
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "report_time": report_time,
        "exchange": exchange,
        "symbols_analyzed": len(symbol_scans),
        "market_summary": market_summary,
        "market_overview": overview,
        "signal_distribution": signal_dist,
        "top_gainers": top_gainers[:5],
        "top_losers": top_losers[:5],
        "sector_analysis": sector_analysis,
        "news_sentiment": news_summary,
        "key_levels": key_levels,
        "scans": symbol_scans,
    }


def _scan_symbols(symbols: list[str], exchange: str, api_key: str) -> list[dict]:
    """Run quick analysis on all symbols."""
    from services.ai_analysis_service import analyze_symbol

    results = []
    for sym in symbols:
        try:
            r = analyze_symbol(sym, exchange, "D", api_key)
            last_close = float(r.candles[-1]["close"]) if r.candles else 0
            prev_close = float(r.candles[-2]["close"]) if r.candles and len(r.candles) > 1 else last_close
            change = last_close - prev_close
            change_pct = (change / prev_close * 100) if prev_close > 0 else 0

            results.append({
                "symbol": sym,
                "price": round(last_close, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "signal": r.signal or "HOLD",
                "confidence": r.confidence or 0,
                "score": round(r.score or 0, 4),
                "regime": r.regime or "RANGING",
                "trade_setup": r.trade_setup or {},
                "error": r.error,
            })
        except Exception as e:
            logger.warning("Scan failed for %s: %s", sym, e)
            results.append({
                "symbol": sym, "price": 0, "change": 0, "change_pct": 0,
                "signal": "HOLD", "confidence": 0, "score": 0,
                "regime": "RANGING", "trade_setup": {}, "error": str(e),
            })

    return results


def _compute_market_overview(scans: list[dict]) -> dict:
    """Compute aggregate market stats."""
    valid = [s for s in scans if not s.get("error")]
    if not valid:
        return {"status": "No data", "avg_score": 0, "avg_confidence": 0, "bullish_pct": 0, "bearish_pct": 0}

    scores = [s["score"] for s in valid]
    confidences = [s["confidence"] for s in valid]
    bullish = sum(1 for s in valid if s["score"] > 0.1)
    bearish = sum(1 for s in valid if s["score"] < -0.1)

    avg_score = sum(scores) / len(scores)
    if avg_score > 0.2:
        status = "Strongly Bullish"
    elif avg_score > 0.05:
        status = "Mildly Bullish"
    elif avg_score < -0.2:
        status = "Strongly Bearish"
    elif avg_score < -0.05:
        status = "Mildly Bearish"
    else:
        status = "Neutral / Mixed"

    return {
        "status": status,
        "avg_score": round(avg_score, 4),
        "avg_confidence": round(sum(confidences) / len(confidences), 1),
        "bullish_pct": round(bullish / len(valid) * 100, 1),
        "bearish_pct": round(bearish / len(valid) * 100, 1),
        "neutral_pct": round((len(valid) - bullish - bearish) / len(valid) * 100, 1),
        "total_symbols": len(valid),
    }


def _compute_top_movers(scans: list[dict]) -> tuple[list[dict], list[dict]]:
    """Get top gainers and losers."""
    valid = [s for s in scans if s.get("price", 0) > 0 and not s.get("error")]
    sorted_scans = sorted(valid, key=lambda x: x.get("change_pct", 0), reverse=True)
    gainers = [s for s in sorted_scans if s.get("change_pct", 0) > 0]
    losers = [s for s in reversed(sorted_scans) if s.get("change_pct", 0) < 0]
    return gainers, losers


def _compute_signal_distribution(scans: list[dict]) -> dict:
    """Count signal types across all scanned symbols."""
    dist = {"STRONG_BUY": 0, "BUY": 0, "HOLD": 0, "SELL": 0, "STRONG_SELL": 0}
    for s in scans:
        sig = s.get("signal", "HOLD")
        if sig in dist:
            dist[sig] += 1
        else:
            dist["HOLD"] += 1
    return dist


def _compute_sector_analysis(scans: list[dict]) -> list[dict]:
    """Simplified sector analysis — group symbols by signal direction."""
    bullish = [s["symbol"] for s in scans if s.get("score", 0) > 0.1]
    bearish = [s["symbol"] for s in scans if s.get("score", 0) < -0.1]
    neutral = [s["symbol"] for s in scans if -0.1 <= s.get("score", 0) <= 0.1]

    return [
        {"group": "Bullish", "count": len(bullish), "symbols": bullish[:10]},
        {"group": "Bearish", "count": len(bearish), "symbols": bearish[:10]},
        {"group": "Neutral", "count": len(neutral), "symbols": neutral[:10]},
    ]


def _fetch_news_summary(symbols: list[str], exchange: str) -> dict:
    """Fetch news sentiment for top symbols."""
    try:
        from ai.news_sentiment import analyze_news_sentiment
        all_articles = 0
        total_compound = 0
        source_map: dict[str, int] = {}

        for sym in symbols[:3]:  # Only top 3 to avoid rate limits
            result = analyze_news_sentiment(sym, exchange, max_per_source=5)
            all_articles += result.get("total_articles", 0)
            total_compound += result.get("overall_sentiment", {}).get("compound", 0)
            for src in result.get("source_breakdown", []):
                source_map[src["source"]] = source_map.get(src["source"], 0) + src["count"]

        avg = total_compound / max(len(symbols[:3]), 1)
        from ai.news_sentiment import classify_sentiment
        label = classify_sentiment(avg)

        return {
            "total_articles": all_articles,
            "avg_sentiment": round(avg, 4),
            "label": label,
            "top_sources": dict(sorted(source_map.items(), key=lambda x: -x[1])[:5]),
        }
    except Exception as e:
        logger.warning("News summary failed: %s", e)
        return {"total_articles": 0, "avg_sentiment": 0, "label": "Unavailable", "top_sources": {}}


def _compute_key_levels(symbols: list[str], exchange: str, api_key: str) -> list[dict]:
    """Compute key support/resistance levels for top symbols."""
    try:
        from services.strategy_analysis_service import analyze_support_resistance
    except ImportError:
        return []

    levels = []
    for sym in symbols[:5]:
        try:
            result = analyze_support_resistance(sym, exchange, "D", api_key)
            levels.append({
                "symbol": sym,
                "pivot": result.get("pivots", {}).get("pp"),
                "r1": result.get("pivots", {}).get("r1"),
                "s1": result.get("pivots", {}).get("s1"),
                "r2": result.get("pivots", {}).get("r2"),
                "s2": result.get("pivots", {}).get("s2"),
            })
        except Exception:
            pass

    return levels


def _generate_market_summary(
    overview: dict, signals: dict, gainers: list, losers: list,
) -> str:
    """Generate a one-paragraph market summary."""
    status = overview.get("status", "Mixed")
    bull_pct = overview.get("bullish_pct", 0)
    bear_pct = overview.get("bearish_pct", 0)
    total = overview.get("total_symbols", 0)

    parts = [f"Market is {status}."]
    parts.append(f"{bull_pct}% of {total} stocks show bullish signals, {bear_pct}% bearish.")

    buy_count = signals.get("STRONG_BUY", 0) + signals.get("BUY", 0)
    sell_count = signals.get("STRONG_SELL", 0) + signals.get("SELL", 0)
    if buy_count > sell_count:
        parts.append(f"Buy signals ({buy_count}) outnumber sell signals ({sell_count}).")
    elif sell_count > buy_count:
        parts.append(f"Sell signals ({sell_count}) dominate over buy signals ({buy_count}).")
    else:
        parts.append("Buy and sell signals are balanced.")

    if gainers:
        top = gainers[0]
        parts.append(f"Top gainer: {top['symbol']} ({top['change_pct']:+.1f}%).")
    if losers:
        bottom = losers[0]
        parts.append(f"Top loser: {bottom['symbol']} ({bottom['change_pct']:+.1f}%).")

    return " ".join(parts)
