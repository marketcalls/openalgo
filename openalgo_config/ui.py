"""Runtime helpers for OpenAlgo strategy configuration declarations.

Strategy authors can declare editable settings with ``ui.*`` calls. The
OpenAlgo host discovers those calls statically during upload, while this module
returns the active runtime value when the strategy process is started.
"""

from __future__ import annotations

import builtins
import json
import os
from typing import Any


def _runtime_values() -> dict[str, Any]:
    raw = os.getenv("OPENALGO_CONFIG_JSON")
    if not raw:
        return {}
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return values if isinstance(values, dict) else {}


class _UI:
    def __init__(self) -> None:
        self._values: dict[str, Any] | None = None

    @property
    def values(self) -> dict[str, Any]:
        if self._values is None:
            self._values = _runtime_values()
        return self._values

    def _get(self, key: str, default: Any = None) -> Any:
        value = self.values.get(key, default)
        return default if value is None else value

    def int(self, key: str, *, default: int = 0, **_: Any) -> int:
        return builtins.int(self._get(key, default))

    def float(self, key: str, *, default: float = 0.0, **_: Any) -> float:
        return builtins.float(self._get(key, default))

    def bool(self, key: str, *, default: bool = False, **_: Any) -> bool:
        value = self._get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return builtins.bool(value)

    def string(self, key: str, *, default: str = "", **_: Any) -> str:
        return str(self._get(key, default))

    def select(self, key: str, *, default: Any = None, **_: Any) -> Any:
        return self._get(key, default)

    def symbol(self, key: str = "symbol", *, default: str = "", **_: Any) -> str:
        return str(self._get(key, default))

    def exchange(self, key: str = "exchange", *, default: str = "NSE", **_: Any) -> str:
        return str(self._get(key, default))

    def product(self, key: str = "product", *, default: str = "MIS", **_: Any) -> str:
        return str(self._get(key, default))

    def quantity(self, key: str = "quantity", *, default: int = 1, **_: Any) -> int:
        return builtins.int(self._get(key, default))


ui = _UI()

__all__ = ["ui"]
