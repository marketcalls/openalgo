"""AAUM Intelligence Service — thin httpx proxy to AAUM FastAPI sidecar.

All functions return tuple[bool, dict, int] following the OpenAlgo
service layer convention: (success, response_data, http_status_code).

AAUM_BASE_URL defaults to http://localhost:8080 (configure in .env).
httpx is already installed in OpenAlgo (httpx==0.28.1).
"""

import os
import logging

import httpx

logger = logging.getLogger(__name__)

AAUM_BASE_URL = os.getenv("AAUM_BASE_URL", "http://localhost:8080")
AAUM_TIMEOUT = int(os.getenv("AAUM_TIMEOUT", "120"))

# Sync httpx client — Flask is sync; AAUM FastAPI handles async internally.
# Module-level singleton with connection pooling.
client = httpx.Client(base_url=AAUM_BASE_URL, timeout=AAUM_TIMEOUT)

_OFFLINE = {
    "status": "error",
    "message": "AAUM Intelligence service is not running. "
               "Start it: cd C:/Users/sakth/Desktop/aaum && "
               "python -m uvicorn aaum.server:app --port 8080",
}
_TIMEOUT_MSG = {
    "status": "error",
    "message": "AAUM analysis timed out. The 9 LLM agents may still be running.",
}


def aaum_analyze(symbol: str) -> tuple[bool, dict, int]:
    """Run full 12-layer analysis for symbol. Takes 30–90 seconds."""
    try:
        resp = client.get(f"/api/v5/analyze/{symbol.upper()}")
        return resp.status_code == 200, resp.json(), resp.status_code
    except httpx.ConnectError:
        logger.warning("AAUM sidecar unreachable at %s", AAUM_BASE_URL)
        return False, _OFFLINE, 503
    except httpx.TimeoutException:
        logger.error("AAUM analyze timed out for %s", symbol)
        return False, _TIMEOUT_MSG, 504
    except Exception as e:
        logger.error("AAUM analyze error for %s: %s", symbol, e)
        return False, {"status": "error", "message": str(e)}, 500


def aaum_execute(
    symbol: str,
    paper: bool = True,
    analysis_id: str | None = None,
) -> tuple[bool, dict, int]:
    """Execute trade recommendation via AAUM → OpenAlgo."""
    try:
        resp = client.post(
            f"/api/v5/execute/{symbol.upper()}",
            json={"paper": paper, "analysis_id": analysis_id},
        )
        return resp.status_code == 200, resp.json(), resp.status_code
    except httpx.ConnectError:
        return False, _OFFLINE, 503
    except httpx.TimeoutException:
        return False, {"status": "error", "message": "Execute timed out"}, 504
    except Exception as e:
        logger.error("AAUM execute error: %s", e)
        return False, {"status": "error", "message": str(e)}, 500


def aaum_health() -> tuple[bool, dict, int]:
    """Lightweight health check — called every 30s by frontend."""
    try:
        resp = client.get("/api/v5/health", timeout=5)
        return True, resp.json(), resp.status_code
    except httpx.ConnectError:
        return False, {"status": "offline", "message": "AAUM sidecar not running"}, 503
    except Exception as e:
        logger.error("AAUM health check error: %s", e)
        return False, {"status": "offline", "message": str(e)}, 503


def aaum_safety(symbol: str) -> tuple[bool, dict, int]:
    """Quick safety pre-check for symbol."""
    try:
        resp = client.get(f"/api/v5/safety/{symbol.upper()}", timeout=20)
        return resp.status_code == 200, resp.json(), resp.status_code
    except httpx.ConnectError:
        return False, _OFFLINE, 503
    except Exception as e:
        logger.error("AAUM safety error for %s: %s", symbol, e)
        return False, {"status": "error", "message": str(e)}, 500
