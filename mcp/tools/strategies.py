"""Strategy management tools for OpenAlgo MCP."""
import json
import requests


def list_strategies(host: str, cookies: dict = None) -> str:
    """List all webhook-based trading strategies.

    Returns strategy names, IDs, enabled status, and webhook URLs.
    """
    try:
        r = requests.get(f"{host}/strategy/api/strategies", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_strategy(host: str, strategy_id: str, cookies: dict = None) -> str:
    """Get details of a specific webhook strategy.

    Args:
        strategy_id: The strategy ID to look up
    """
    try:
        r = requests.get(f"{host}/strategy/api/strategy/{strategy_id}", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def toggle_strategy(host: str, strategy_id: str, cookies: dict = None) -> str:
    """Enable or disable a webhook strategy.

    Args:
        strategy_id: The strategy ID to toggle
    """
    try:
        r = requests.post(f"{host}/strategy/api/strategy/{strategy_id}/toggle", cookies=cookies, timeout=5)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def list_python_strategies(host: str, cookies: dict = None) -> str:
    """List all Python trading strategies with their run status.

    Returns strategy names, IDs, running status, PID, and schedule info.
    """
    try:
        r = requests.get(f"{host}/python/api/strategies", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_python_strategy(host: str, strategy_id: str, cookies: dict = None) -> str:
    """Get details and source code of a Python strategy.

    Args:
        strategy_id: The Python strategy ID
    """
    try:
        r = requests.get(f"{host}/python/api/strategy/{strategy_id}", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def start_python_strategy(host: str, strategy_id: str, cookies: dict = None) -> str:
    """Start a Python trading strategy.

    Args:
        strategy_id: The Python strategy ID to start
    """
    try:
        r = requests.post(f"{host}/python/start/{strategy_id}", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def stop_python_strategy(host: str, strategy_id: str, cookies: dict = None) -> str:
    """Stop a running Python trading strategy.

    Args:
        strategy_id: The Python strategy ID to stop
    """
    try:
        r = requests.post(f"{host}/python/stop/{strategy_id}", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_strategy_logs(host: str, strategy_id: str, cookies: dict = None) -> str:
    """Get execution logs for a Python strategy.

    Args:
        strategy_id: The Python strategy ID
    """
    try:
        r = requests.get(f"{host}/python/api/logs/{strategy_id}", cookies=cookies, timeout=10)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
