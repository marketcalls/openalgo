"""Use Adanos sentiment as a confirmation layer before sending orders to OpenAlgo.

This example keeps the OpenAlgo execution path untouched:

1. Fetch source-level sentiment from Adanos
2. Build a lightweight composite inside Python
3. Place an OpenAlgo order only if thresholds pass

By default the script runs in dry-run mode and only logs the decision.
"""

import os
from statistics import mean

import requests
from openalgo import api

OPENALGO_HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
OPENALGO_API_KEY = os.getenv("OPENALGO_API_KEY", "your-openalgo-api-key")
ADANOS_API_KEY = os.getenv("ADANOS_API_KEY", "your-adanos-api-key")

SYMBOL = os.getenv("SYMBOL", "INFY").upper()
EXCHANGE = os.getenv("EXCHANGE", "NSE")
PRODUCT = os.getenv("PRODUCT", "MIS")
QUANTITY = int(os.getenv("QUANTITY", "1"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "7"))

MIN_AVG_BUZZ = float(os.getenv("MIN_AVG_BUZZ", "60"))
MIN_BULLISH_AVG = float(os.getenv("MIN_BULLISH_AVG", "55"))
BLOCK_FALLING = os.getenv("BLOCK_FALLING", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
ORDER_MODE = os.getenv("ORDER_MODE", "standard").lower()

ADANOS_ENDPOINTS = {
    "reddit": "https://api.adanos.org/reddit/stocks/v1/stock/{ticker}",
    "x": "https://api.adanos.org/x/stocks/v1/stock/{ticker}",
    "news": "https://api.adanos.org/news/stocks/v1/stock/{ticker}",
    "polymarket": "https://api.adanos.org/polymarket/stocks/v1/stock/{ticker}",
}

client = api(api_key=OPENALGO_API_KEY, host=OPENALGO_HOST)


def to_float(value, default=0.0):
    """Convert nullable or string values to float safely."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def to_int(value, default=0):
    """Convert nullable or string values to int safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        normalized = str(value).replace(",", "").strip()
        return int(float(normalized))
    except (TypeError, ValueError):
        return default


def fetch_source_signal(session, source, ticker):
    """Fetch one source signal from Adanos."""
    response = session.get(
        ADANOS_ENDPOINTS[source].format(ticker=ticker),
        params={"days": LOOKBACK_DAYS},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()

    volume = payload.get("trade_count")
    if volume is None:
        volume = payload.get("trades")
    if volume is None:
        volume = payload.get("mentions", 0)

    return {
        "source": source,
        "buzz": to_float(payload.get("buzz_score")),
        "bullish_pct": to_float(payload.get("bullish_pct")),
        "trend": str(payload.get("trend") or "stable").lower(),
        "volume": to_int(volume),
    }


def get_source_signals(ticker):
    """Fetch every available source and skip failing ones."""
    session = requests.Session()
    session.headers["X-API-Key"] = ADANOS_API_KEY

    signals = []
    for source in ADANOS_ENDPOINTS:
        try:
            signals.append(fetch_source_signal(session, source, ticker))
        except requests.RequestException as exc:
            print(f"Skipping {source}: {exc}")

    return signals


def classify_alignment(bullish_values):
    """Classify how closely the enabled sources agree."""
    spread = max(bullish_values) - min(bullish_values)
    if spread <= 15:
        return "Aligned"
    if spread <= 30:
        return "Mixed"
    return "Wide divergence"


def build_composite(signals):
    """Build a lightweight composite from source-level signals."""
    if not signals:
        raise ValueError("No Adanos sources returned data for this symbol.")

    buzz_values = [signal["buzz"] for signal in signals]
    bullish_values = [signal["bullish_pct"] for signal in signals]
    trends = [signal["trend"] for signal in signals]

    return {
        "average_buzz": round(mean(buzz_values), 1),
        "bullish_avg": round(mean(bullish_values), 1),
        "conviction": round(mean(buzz_values) * 0.6 + mean(bullish_values) * 0.4, 1),
        "source_alignment": classify_alignment(bullish_values),
        "rising_sources": sum(1 for trend in trends if trend == "rising"),
        "falling_sources": sum(1 for trend in trends if trend == "falling"),
    }


def should_place_order(composite):
    """Return True when the sentiment gate passes."""
    if composite["average_buzz"] < MIN_AVG_BUZZ:
        return False
    if composite["bullish_avg"] < MIN_BULLISH_AVG:
        return False
    if BLOCK_FALLING and composite["falling_sources"] >= 2:
        return False
    return True


def main():
    signals = get_source_signals(SYMBOL)
    try:
        composite = build_composite(signals)
    except ValueError as exc:
        print(f"Decision: BLOCK trade ({exc})")
        return

    print(f"\nAdanos composite for {SYMBOL}")
    print("-" * 60)
    for signal in signals:
        metric_name = "trades" if signal["source"] == "polymarket" else "mentions"
        print(
            f"{signal['source']:>10} | buzz={signal['buzz']:.1f} | "
            f"bullish={signal['bullish_pct']:.1f}% | "
            f"{metric_name}={signal['volume']} | trend={signal['trend']}"
        )

    print("-" * 60)
    print(f"Average buzz:     {composite['average_buzz']}/100")
    print(f"Bullish average:  {composite['bullish_avg']}%")
    print(f"Conviction:       {composite['conviction']}/100")
    print(f"Source alignment: {composite['source_alignment']}")

    if not should_place_order(composite):
        print("Decision: BLOCK trade")
        return

    if DRY_RUN:
        print("Decision: PASS trade gate (dry run, no order sent)")
        return

    if ORDER_MODE == "smart":
        response = client.placesmartorder(
            strategy="Adanos Sentiment Gate",
            symbol=SYMBOL,
            action="BUY",
            exchange=EXCHANGE,
            price_type="MARKET",
            product=PRODUCT,
            quantity=QUANTITY,
            position_size=QUANTITY,
        )
    else:
        response = client.placeorder(
            strategy="Adanos Sentiment Gate",
            symbol=SYMBOL,
            action="BUY",
            exchange=EXCHANGE,
            price_type="MARKET",
            product=PRODUCT,
            quantity=QUANTITY,
        )
    print("Order Response:", response)


if __name__ == "__main__":
    main()
