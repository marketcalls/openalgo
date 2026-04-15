from abc import ABC, abstractmethod
from typing import Any


class VendorCapabilityError(Exception):
    """Raised when the vendor does not support the requested capability (e.g. depth)."""


class VendorSymbolError(Exception):
    """Raised when a symbol/exchange pair cannot be mapped to the vendor's namespace."""


class BaseDataVendor(ABC):
    """Interface every data vendor must implement.

    Mirrors the shape of broker/<name>/api/data.py::BrokerData so services can
    treat broker-sourced and vendor-sourced data handlers interchangeably.
    """

    name: str = ""
    supported_exchanges: list[str] = []
    capabilities: dict[str, bool] = {
        "ltp": False,
        "quote": False,
        "depth": False,
        "history": False,
    }

    timeframe_map: dict[str, Any] = {}

    @abstractmethod
    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """Return a single quote dict with keys: ask, bid, high, low, ltp, open, prev_close, volume, oi."""

    def get_multiquotes(self, symbols: list[dict]) -> list[dict]:
        """Default fallback: loop get_quotes. Vendors can override for batched APIs."""
        results: list[dict] = []
        for item in symbols:
            sym = item.get("symbol", "")
            exch = item.get("exchange", "")
            try:
                results.append({"symbol": sym, "exchange": exch, "data": self.get_quotes(sym, exch)})
            except Exception as exc:
                results.append({"symbol": sym, "exchange": exch, "error": str(exc)})
        return results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        raise VendorCapabilityError(
            f"Market depth is not supported by data vendor '{self.name}'"
        )

    @abstractmethod
    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str):
        """Return a pandas DataFrame with columns: timestamp, open, high, low, close, volume, oi."""

    def get_market_timings(self, exchange: str) -> dict:
        return {"start": "09:15:00", "end": "15:30:00"}
