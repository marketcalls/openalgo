"""Bridge between OpenAlgo data services and AI indicator engine.

Fetches OHLCV via OpenAlgo's history_service and returns a clean DataFrame.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OHLCVResult:
    success: bool
    df: pd.DataFrame
    symbol: str
    exchange: str
    interval: str
    error: str | None


def _call_history_service(
    symbol: str, exchange: str, interval: str, api_key: str,
    start_date: str | None = None, end_date: str | None = None,
    timeout: int = 30,
) -> dict:
    """Call OpenAlgo's history service to fetch OHLCV data.

    Uses the real get_history() signature from services/history_service.py:
    get_history(symbol, exchange, interval, start_date, end_date, api_key, source)
    Returns: (success: bool, response_data: dict, status_code: int)
    """
    import concurrent.futures

    from services.history_service import get_history

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        days = 365 if interval in ("D", "W", "M") else 60
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Try broker API first with timeout, fallback to local DuckDB (historify)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            get_history,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            source="api",
        )
        try:
            success, response_data, status_code = future.result(timeout=timeout)
            if success:
                return response_data
        except concurrent.futures.TimeoutError:
            logger.warning(f"Broker API timed out for {symbol}, trying local DB...")

    # Fallback: try local DuckDB/historify data
    try:
        success, response_data, status_code = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            source="db",
        )
        if success:
            logger.info(f"Using local DB data for {symbol}")
            return response_data
    except Exception as e:
        logger.debug(f"Local DB fallback failed for {symbol}: {e}")

    return {"status": "error", "message": f"No data available for {symbol} (broker timed out, no local data)"}


def fetch_ohlcv(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "1d",
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
) -> OHLCVResult:
    """Fetch OHLCV data and return as a clean DataFrame.

    Returns OHLCVResult with DataFrame having columns: open, high, low, close, volume
    """
    try:
        response = _call_history_service(
            symbol, exchange, interval, api_key, start_date, end_date,
        )

        if isinstance(response, tuple):
            response = response[0]

        if isinstance(response, dict) and response.get("status") == "error":
            return OHLCVResult(
                success=False, df=pd.DataFrame(),
                symbol=symbol, exchange=exchange, interval=interval,
                error=response.get("message", "Unknown error"),
            )

        data = response.get("data", response) if isinstance(response, dict) else response

        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            df = pd.DataFrame(data)
        elif isinstance(data, pd.DataFrame):
            df = data
        else:
            return OHLCVResult(
                success=False, df=pd.DataFrame(),
                symbol=symbol, exchange=exchange, interval=interval,
                error=f"Unexpected data type: {type(data)}",
            )

        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                return OHLCVResult(
                    success=False, df=pd.DataFrame(),
                    symbol=symbol, exchange=exchange, interval=interval,
                    error=f"Missing column: {col}",
                )

        df = df[required].astype(float)

        return OHLCVResult(
            success=True, df=df,
            symbol=symbol, exchange=exchange, interval=interval,
            error=None,
        )

    except Exception as e:
        logger.error(f"fetch_ohlcv error for {symbol}: {e}")
        return OHLCVResult(
            success=False, df=pd.DataFrame(),
            symbol=symbol, exchange=exchange, interval=interval,
            error=str(e),
        )
