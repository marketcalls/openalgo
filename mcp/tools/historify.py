"""Historical data (Historify) tools for OpenAlgo MCP."""
import json
import requests


def historify_catalog(host: str, cookies: dict = None) -> str:
    """List all available historical data grouped by exchange and symbol.

    Returns catalog of downloaded data with intervals and date ranges.
    """
    try:
        r = requests.get(f"{host}/historify/api/catalog/grouped", cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def historify_download(
    host: str, symbol: str, exchange: str = "NSE",
    interval: str = "1d", cookies: dict = None,
) -> str:
    """Download historical OHLCV data for a symbol from the broker.

    Data is stored in the local DuckDB database for fast access.

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE')
        exchange: Exchange ('NSE', 'BSE', 'NFO')
        interval: Timeframe ('1m', '5m', '15m', '1h', '1d')
    """
    try:
        r = requests.post(
            f"{host}/historify/api/download",
            json={"symbol": symbol, "exchange": exchange, "interval": interval},
            cookies=cookies, timeout=30,
        )
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def historify_stats(host: str, cookies: dict = None) -> str:
    """Get Historify database statistics.

    Returns total symbols, data points, date range, and storage size.
    """
    try:
        r = requests.get(f"{host}/historify/api/stats", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def historify_data(
    host: str, symbol: str, exchange: str = "NSE",
    interval: str = "1d", start_date: str = None, end_date: str = None,
    cookies: dict = None,
) -> str:
    """Get stored historical OHLCV data for a symbol.

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE')
        exchange: Exchange ('NSE', 'BSE')
        interval: Timeframe ('1m', '5m', '15m', '1h', '1d')
        start_date: Start date (YYYY-MM-DD, optional)
        end_date: End date (YYYY-MM-DD, optional)
    """
    try:
        params = {"symbol": symbol, "exchange": exchange, "interval": interval}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        r = requests.get(f"{host}/historify/api/data", params=params, cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
