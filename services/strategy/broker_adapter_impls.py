"""Concrete BrokerAdapter implementations.

LiveBrokerAdapter and SandboxBrokerAdapter are thin pass-throughs to the
existing OpenAlgo order services. The strategy engine uses these instead of
importing the order services directly — see plan §5.1.

Phase 6 mode override:
    Each adapter wraps its delegate calls in a `with force_strategy_mode(...)`
    block from utils.strategy_mode_context. database.settings_db.get_analyze_mode
    consults the contextvar BEFORE the global analyze flag, so a v2
    SandboxBrokerAdapter call always lands in sandbox even with global
    analyze=False, and a LiveBrokerAdapter call always lands live even with
    global analyze=True. Strategy.mode now drives routing independent of the
    global toggle.
"""

from __future__ import annotations

from typing import Any

# Lazy imports inside methods avoid a circular load via restx_api/__init__.py
# which imports the same services we'd otherwise pull at module-load time.
from services.strategy.broker_adapter import BrokerAdapter, ServiceResult
from utils.logging import get_logger
from utils.strategy_mode_context import force_strategy_mode

logger = get_logger(__name__)


def _ensure_apikey(payload: dict, api_key: str) -> dict:
    """Helper: stamp api_key into payload (services expect it inside the dict)."""
    payload = dict(payload)  # shallow copy so the caller's dict isn't mutated
    payload.setdefault("apikey", api_key)
    return payload


class _BaseBrokerAdapter(BrokerAdapter):
    """Shared implementation — delegates to the existing OpenAlgo services
    inside a `with force_strategy_mode(self.mode)` block so the per-call
    contextvar override wins over the global analyze flag.

    Live and Sandbox adapters differ only by class-level `mode` attribute.
    Subclassing keeps each path self-documenting and the engine's
    `get_adapter()` factory simple.
    """

    mode: str = ""  # set in subclass

    def __init__(self, api_key: str):
        self.api_key = api_key

    def place_order(self, order_data: dict) -> ServiceResult:
        from services.place_order_service import place_order as place_order_svc
        with force_strategy_mode(self.mode):  # type: ignore[arg-type]
            return place_order_svc(
                order_data=_ensure_apikey(order_data, self.api_key),
                api_key=self.api_key,
            )

    def place_options_order(self, options_data: dict) -> ServiceResult:
        from services.place_options_order_service import place_options_order as options_svc
        with force_strategy_mode(self.mode):  # type: ignore[arg-type]
            return options_svc(
                options_data=_ensure_apikey(options_data, self.api_key),
                api_key=self.api_key,
            )

    def place_options_multiorder(self, multiorder_data: dict) -> ServiceResult:
        from services.options_multiorder_service import place_options_multiorder as multi_svc
        with force_strategy_mode(self.mode):  # type: ignore[arg-type]
            return multi_svc(
                multiorder_data=_ensure_apikey(multiorder_data, self.api_key),
                api_key=self.api_key,
            )

    def basket_order(self, basket_data: dict) -> ServiceResult:
        from services.basket_order_service import place_basket_order
        with force_strategy_mode(self.mode):  # type: ignore[arg-type]
            return place_basket_order(
                basket_data=_ensure_apikey(basket_data, self.api_key),
                api_key=self.api_key,
            )

    def cancel_order(self, orderid: str) -> ServiceResult:
        from services.cancel_order_service import cancel_order as cancel_order_svc
        with force_strategy_mode(self.mode):  # type: ignore[arg-type]
            return cancel_order_svc(orderid=orderid, api_key=self.api_key)

    def get_order_status(self, orderid: str) -> ServiceResult:
        from services.orderstatus_service import get_order_status as get_order_status_svc
        with force_strategy_mode(self.mode):  # type: ignore[arg-type]
            return get_order_status_svc(
                status_data={"orderid": orderid},
                api_key=self.api_key,
            )


class LiveBrokerAdapter(_BaseBrokerAdapter):
    """Forces live routing for the duration of every service call —
    bypasses the global analyze flag via utils.strategy_mode_context."""

    mode = "live"


class SandboxBrokerAdapter(_BaseBrokerAdapter):
    """Forces sandbox routing for the duration of every service call.
    Sandbox fills happen via services.sandbox_service at the live LTP —
    zero slippage per §14.2 #3."""

    mode = "sandbox"


def get_adapter(mode: str, api_key: str) -> BrokerAdapter:
    """Factory: select the right adapter for a strategy run's mode."""
    mode = (mode or "live").lower()
    if mode == "sandbox":
        return SandboxBrokerAdapter(api_key)
    return LiveBrokerAdapter(api_key)
