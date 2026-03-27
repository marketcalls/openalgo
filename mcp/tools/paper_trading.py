"""Paper Trading / Sandbox tools for OpenAlgo MCP."""
import json
import requests


def paper_trading_status(host: str, cookies: dict = None) -> str:
    """Check if paper trading (analyzer/sandbox) mode is enabled.

    Returns the current analyzer mode status including whether
    orders are being simulated or sent to the broker.
    """
    try:
        r = requests.get(f"{host}/auth/analyzer-mode", cookies=cookies, timeout=5)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def paper_trading_enable(host: str, cookies: dict = None) -> str:
    """Enable paper trading mode. All orders will be simulated (not sent to broker).

    Use this before testing trading strategies to avoid real money risk.
    """
    try:
        r = requests.post(f"{host}/auth/analyzer-toggle", cookies=cookies, timeout=5)
        data = r.json()
        if data.get("analyze_mode"):
            return json.dumps({"status": "success", "message": "Paper trading ENABLED. Orders will be simulated."})
        # Toggle again if it was disabled
        r = requests.post(f"{host}/auth/analyzer-toggle", cookies=cookies, timeout=5)
        return json.dumps(r.json())
    except Exception as e:
        return json.dumps({"error": str(e)})


def paper_trading_disable(host: str, cookies: dict = None) -> str:
    """Disable paper trading mode. Orders will be sent to the real broker.

    WARNING: After disabling, all orders will execute with real money.
    """
    try:
        r = requests.get(f"{host}/auth/analyzer-mode", cookies=cookies, timeout=5)
        data = r.json()
        if not data.get("analyze_mode", True):
            return json.dumps({"status": "success", "message": "Paper trading already DISABLED. Live mode active."})
        r = requests.post(f"{host}/auth/analyzer-toggle", cookies=cookies, timeout=5)
        return json.dumps({"status": "success", "message": "Paper trading DISABLED. Live trading mode active."})
    except Exception as e:
        return json.dumps({"error": str(e)})


def paper_pnl(host: str, api_key: str) -> str:
    """Get paper trading P&L breakdown by symbol (sandbox mode only).

    Returns profit/loss for each symbol traded in paper mode.
    """
    try:
        r = requests.post(
            f"{host}/api/v1/pnl/symbols",
            json={"apikey": api_key},
            timeout=10,
        )
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def paper_reset(host: str, cookies: dict = None) -> str:
    """Reset the paper trading portfolio. Clears all simulated positions and P&L.

    Use this to start fresh with paper trading.
    """
    try:
        r = requests.post(f"{host}/sandbox/reset", cookies=cookies, timeout=5)
        return json.dumps({"status": "success", "message": "Paper portfolio reset."})
    except Exception as e:
        return json.dumps({"error": str(e)})
