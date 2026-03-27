"""ML & Intelligence tools for OpenAlgo MCP."""
import json
import requests


def ml_recommend(host: str, symbol: str, cookies: dict = None) -> str:
    """Get ML-powered trading recommendation for a symbol.

    Uses machine learning models to analyze patterns and provide
    buy/sell/hold recommendation with confidence and risk assessment.

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE', 'SBIN')
    """
    try:
        r = requests.get(f"{host}/ml_advisor/recommend/{symbol}", cookies=cookies, timeout=15)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def market_analysis(host: str, symbol: str, exchange: str = "NSE", api_key: str = "") -> str:
    """Get full market analysis report — combines trend, momentum, and OI analysis.

    Returns trend direction/strength, momentum bias, OI-based bias,
    and a unified recommendation.

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE')
        exchange: Exchange ('NSE', 'BSE')
    """
    try:
        r = requests.post(
            f"{host}/api/v1/market-analysis/report",
            json={"apikey": api_key, "symbol": symbol, "exchange": exchange},
            timeout=30,
        )
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
