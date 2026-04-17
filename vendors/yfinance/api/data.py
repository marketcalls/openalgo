from datetime import datetime, timedelta

import pandas as pd

from utils.logging import get_logger
from vendors.base_vendor import (
    BaseDataVendor,
    VendorCapabilityError,
    VendorSymbolError,
)
from vendors.yfinance.mapping.symbol_map import (
    SUPPORTED_EXCHANGES,
    to_openalgo,
    to_vendor,
)

logger = get_logger(__name__)

try:
    import yfinance as yf
except ImportError as exc:
    yf = None
    _YF_IMPORT_ERROR: Exception | None = exc
else:
    _YF_IMPORT_ERROR = None


class VendorData(BaseDataVendor):
    name = "yfinance"
    supported_exchanges = sorted(SUPPORTED_EXCHANGES)
    capabilities = {"ltp": True, "quote": True, "depth": False, "history": True}

    timeframe_map = {
        "1m": "1m",
        "2m": "2m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "60m": "60m",
        "1h": "60m",
        "D": "1d",
        "W": "1wk",
        "M": "1mo",
    }

    _HISTORY_MAX_DAYS = {
        "1m": 7,
        "2m": 60,
        "5m": 60,
        "15m": 60,
        "30m": 60,
        "60m": 730,
        "1h": 730,
    }

    def __init__(self, api_key: str | None = None, api_secret: str | None = None):
        if yf is None:
            raise RuntimeError(
                f"yfinance package is not installed. Run `uv add yfinance`. "
                f"Original import error: {_YF_IMPORT_ERROR}"
            )
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""

    def _ticker(self, symbol: str, exchange: str):
        yf_ticker = to_vendor(symbol, exchange)
        return yf_ticker, yf.Ticker(yf_ticker)

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        yf_ticker, ticker = self._ticker(symbol, exchange)
        logger.debug("yfinance get_quotes ticker=%s (oa=%s:%s)", yf_ticker, exchange, symbol)

        fast = getattr(ticker, "fast_info", None) or {}

        def _pick(*keys, default=0):
            for key in keys:
                value = None
                try:
                    value = fast[key] if hasattr(fast, "__getitem__") else getattr(fast, key, None)
                except (KeyError, AttributeError, TypeError):
                    value = None
                if value is not None:
                    return value
            return default

        ltp = _pick("last_price", "lastPrice")
        open_ = _pick("open", "regularMarketOpen")
        high = _pick("day_high", "dayHigh")
        low = _pick("day_low", "dayLow")
        prev_close = _pick("previous_close", "previousClose", "regular_market_previous_close")
        volume = _pick("last_volume", "regularMarketVolume", "volume")

        if not ltp:
            try:
                hist = ticker.history(period="1d", interval="1m")
                if not hist.empty:
                    last = hist.iloc[-1]
                    ltp = float(last.get("Close", 0) or 0)
                    open_ = open_ or float(last.get("Open", 0) or 0)
                    high = high or float(hist["High"].max())
                    low = low or float(hist["Low"].min())
                    volume = volume or int(hist["Volume"].sum())
            except Exception as exc:
                logger.debug("yfinance fallback history fetch failed for %s: %s", yf_ticker, exc)

        return {
            "ask": 0,
            "bid": 0,
            "high": float(high or 0),
            "low": float(low or 0),
            "ltp": float(ltp or 0),
            "open": float(open_ or 0),
            "prev_close": float(prev_close or 0),
            "volume": int(volume or 0),
            "oi": 0,
        }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        raise VendorCapabilityError(
            "Market depth is not supported by data vendor 'yfinance'"
        )

    def get_history(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        yf_ticker, ticker = self._ticker(symbol, exchange)
        yf_interval = self.timeframe_map.get(interval)
        if yf_interval is None:
            raise ValueError(
                f"yfinance vendor does not support interval '{interval}'. "
                f"Supported: {', '.join(self.timeframe_map.keys())}"
            )

        start = pd.to_datetime(start_date).to_pydatetime()
        end = pd.to_datetime(end_date).to_pydatetime() + timedelta(days=1)

        max_days = self._HISTORY_MAX_DAYS.get(interval)
        if max_days is not None:
            earliest = datetime.utcnow() - timedelta(days=max_days)
            if start < earliest:
                logger.debug(
                    "yfinance clamping start date for %s interval=%s: %s -> %s",
                    yf_ticker,
                    interval,
                    start,
                    earliest,
                )
                start = earliest

        df = ticker.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=yf_interval,
            auto_adjust=False,
            actions=False,
        )

        if df is None or df.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])

        df = df.reset_index()
        ts_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])

        def _float_col(name: str) -> pd.Series:
            if name in df.columns:
                return pd.to_numeric(df[name], errors="coerce").fillna(0.0).astype(float)
            return pd.Series([0.0] * len(df), dtype=float)

        def _int_col(name: str) -> pd.Series:
            if name in df.columns:
                return pd.to_numeric(df[name], errors="coerce").fillna(0).astype("int64")
            return pd.Series([0] * len(df), dtype="int64")

        out = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(df[ts_col], errors="coerce").astype("int64") // 10**9,
                "open": _float_col("Open"),
                "high": _float_col("High"),
                "low": _float_col("Low"),
                "close": _float_col("Close"),
                "volume": _int_col("Volume"),
            }
        )
        out["oi"] = 0
        return out

    def get_multiquotes(self, symbols: list[dict]) -> list[dict]:
        results: list[dict] = []
        for item in symbols:
            sym = item.get("symbol", "")
            exch = item.get("exchange", "")
            try:
                results.append({"symbol": sym, "exchange": exch, "data": self.get_quotes(sym, exch)})
            except VendorSymbolError as exc:
                results.append({"symbol": sym, "exchange": exch, "error": str(exc)})
            except Exception as exc:
                logger.exception("yfinance get_quotes failed for %s:%s", exch, sym)
                results.append({"symbol": sym, "exchange": exch, "error": str(exc)})
        return results
