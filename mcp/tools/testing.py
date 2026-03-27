"""Testing & verification tools for OpenAlgo MCP."""
import json
import requests


def health_check(host: str, cookies: dict = None) -> str:
    """Run a full system health check on the OpenAlgo platform.

    Returns status of: Flask server, broker connection, database,
    WebSocket server, and master contracts.
    """
    results = {}

    # Flask server
    try:
        r = requests.get(f"{host}/health/api/current", cookies=cookies, timeout=5)
        results["health"] = r.json()
    except Exception as e:
        results["health"] = {"status": "error", "error": str(e)}

    # Broker capabilities
    try:
        r = requests.get(f"{host}/capabilities", cookies=cookies, timeout=5)
        results["broker"] = r.json()
    except Exception as e:
        results["broker"] = {"status": "error", "error": str(e)}

    # WebSocket
    try:
        r = requests.get(f"{host}/api/websocket/status", cookies=cookies, timeout=5)
        results["websocket"] = r.json()
    except Exception as e:
        results["websocket"] = {"status": "error", "error": str(e)}

    # Master contracts
    try:
        r = requests.get(f"{host}/master-contract/smart-status", cookies=cookies, timeout=5)
        results["master_contracts"] = r.json()
    except Exception as e:
        results["master_contracts"] = {"status": "error", "error": str(e)}

    return json.dumps(results, indent=2)


def broker_status(host: str, cookies: dict = None) -> str:
    """Check broker connection status and available capabilities.

    Returns connected broker name, supported features, and order types.
    """
    try:
        r = requests.get(f"{host}/capabilities", cookies=cookies, timeout=5)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def websocket_status(host: str, cookies: dict = None) -> str:
    """Check WebSocket server status for real-time data streaming.

    Returns connection status, active subscriptions, and metrics.
    """
    try:
        r = requests.get(f"{host}/api/websocket/status", cookies=cookies, timeout=5)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def master_contract_status(host: str, cookies: dict = None) -> str:
    """Check if master contracts (instrument lists) are downloaded and ready.

    Master contracts are required for symbol resolution and trading.
    """
    try:
        r = requests.get(f"{host}/master-contract/smart-status", cookies=cookies, timeout=5)
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def test_api(host: str, method: str, endpoint: str, api_key: str = "", body: dict = None, cookies: dict = None) -> str:
    """Test any OpenAlgo API endpoint directly.

    A generic tool to call any endpoint for testing purposes.

    Args:
        method: HTTP method ('GET' or 'POST')
        endpoint: API path (e.g., '/api/v1/agent/status')
        body: JSON body for POST requests (optional)
    """
    try:
        url = f"{host}{endpoint}"
        if body is None:
            body = {}
        if api_key and "apikey" not in body:
            body["apikey"] = api_key

        if method.upper() == "GET":
            r = requests.get(url, cookies=cookies, timeout=15)
        else:
            r = requests.post(url, json=body, cookies=cookies, timeout=15)

        try:
            return json.dumps({"status_code": r.status_code, "response": r.json()}, indent=2)
        except ValueError:
            return json.dumps({"status_code": r.status_code, "response": r.text[:500]}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
