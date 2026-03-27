"""Options analytics tools for OpenAlgo MCP — OI, Greeks, IV, Straddle, GEX."""
import json
import requests


def oi_tracker(
    host: str, symbol: str, expiry: str = None, cookies: dict = None,
) -> str:
    """Get Open Interest data with CE/PE OI bars, PCR overlay, and ATM strike marker.

    Args:
        symbol: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'RELIANCE')
        expiry: Expiry date (YYYY-MM-DD, optional — uses nearest if not specified)
    """
    try:
        payload = {"symbol": symbol}
        if expiry:
            payload["expiry"] = expiry
        r = requests.post(f"{host}/oitracker/api/oi-data", json=payload, cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def max_pain_chart(
    host: str, symbol: str, expiry: str = None, cookies: dict = None,
) -> str:
    """Calculate Max Pain strike for an options symbol.

    Max Pain is the strike where option writers have minimum loss.
    Price tends to gravitate toward max pain near expiry.

    Args:
        symbol: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        expiry: Expiry date (YYYY-MM-DD, optional)
    """
    try:
        payload = {"symbol": symbol}
        if expiry:
            payload["expiry"] = expiry
        r = requests.post(f"{host}/oitracker/api/maxpain", json=payload, cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def iv_chart(
    host: str, symbol: str, interval: str = "1d", cookies: dict = None,
) -> str:
    """Get Implied Volatility historical chart data.

    Args:
        symbol: Option or underlying symbol
        interval: Timeframe ('1d', '1h', '15m')
    """
    try:
        r = requests.post(
            f"{host}/ivchart/api/iv-data",
            json={"symbol": symbol, "interval": interval},
            cookies=cookies, timeout=15,
        )
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def iv_smile(
    host: str, symbol: str, expiry: str = None, cookies: dict = None,
) -> str:
    """Get IV Smile curve — Call/Put IV across strikes with ATM IV and skew analysis.

    Args:
        symbol: Underlying symbol (e.g., 'NIFTY')
        expiry: Expiry date (optional)
    """
    try:
        payload = {"symbol": symbol}
        if expiry:
            payload["expiry"] = expiry
        r = requests.post(f"{host}/ivsmile/api/iv-smile-data", json=payload, cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def straddle_data(
    host: str, symbol: str, expiry: str = None, cookies: dict = None,
) -> str:
    """Get ATM Straddle chart data with rolling strike, Spot, and Synthetic Futures overlay.

    Args:
        symbol: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        expiry: Expiry date (optional)
    """
    try:
        payload = {"symbol": symbol}
        if expiry:
            payload["expiry"] = expiry
        r = requests.post(f"{host}/straddle/api/straddle-data", json=payload, cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def gex_dashboard(
    host: str, symbol: str, expiry: str = None, cookies: dict = None,
) -> str:
    """Get Gamma Exposure (GEX) analysis — OI Walls, Net GEX per strike, top gamma strikes.

    GEX helps identify key support/resistance levels based on dealer hedging.

    Args:
        symbol: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        expiry: Expiry date (optional)
    """
    try:
        payload = {"symbol": symbol}
        if expiry:
            payload["expiry"] = expiry
        r = requests.post(f"{host}/gex/api/gex-data", json=payload, cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
