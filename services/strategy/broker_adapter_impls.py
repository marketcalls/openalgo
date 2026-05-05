"""Concrete BrokerAdapter implementations.

LiveBrokerAdapter and SandboxBrokerAdapter are thin pass-throughs to the
existing OpenAlgo order services. The strategy engine uses these instead of
importing the order services directly — see plan §5.1.

Phase 1 design note (re-visited in Phase 6):
    The underlying place_order_service / place_options_order_service / etc.
    auto-route to sandbox when get_analyze_mode() is True (a global flag).
    Both adapters here delegate to those services. Practical effect: with
    global analyze ON, even a strategy.mode='live' run will land in sandbox.
    Per-strategy mode-override (independent of the global flag) is the
    Phase 6 sandbox-parity-sweep deliverable.
"""

from __future__ import annotations

from typing import Any

# Lazy imports inside methods avoid a circular load via restx_api/__init__.py
# which imports the same services we'd otherwise pull at module-load time.
from services.strategy.broker_adapter import BrokerAdapter, ServiceResult
from utils.logging import get_logger

logger = get_logger(__name__)


def _ensure_apikey(payload: dict, api_key: str) -> dict:
    """Helper: stamp api_key into payload (services expect it inside the dict)."""
    payload = dict(payload)  # shallow copy so the caller's dict isn't mutated
    payload.setdefault("apikey", api_key)
    return payload


class LiveBrokerAdapter(BrokerAdapter):
    """Routes to live broker via existing place_order_service etc.

    Inherits the global analyze-mode flag from those services — if global
    analyze is ON, this adapter still ends up in sandbox. The strategy engine
    relies on the strategy.mode field for attribution (strategy_orders.mode)
    rather than for routing in Phase 1.
    """

    mode = "live"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def place_order(self, order_data: dict) -> ServiceResult:
        from services.place_order_service import place_order as place_order_svc
        return place_order_svc(
            order_data=_ensure_apikey(order_data, self.api_key),
            api_key=self.api_key,
        )

    def place_options_order(self, options_data: dict) -> ServiceResult:
        from services.place_options_order_service import place_options_order as options_svc
        return options_svc(
            options_data=_ensure_apikey(options_data, self.api_key),
            api_key=self.api_key,
        )

    def place_options_multiorder(self, multiorder_data: dict) -> ServiceResult:
        from services.options_multiorder_service import place_options_multiorder as multi_svc
        return multi_svc(
            multiorder_data=_ensure_apikey(multiorder_data, self.api_key),
            api_key=self.api_key,
        )

    def basket_order(self, basket_data: dict) -> ServiceResult:
        from services.basket_order_service import place_basket_order
        return place_basket_order(
            basket_data=_ensure_apikey(basket_data, self.api_key),
            api_key=self.api_key,
        )

    def cancel_order(self, orderid: str) -> ServiceResult:
        from services.cancel_order_service import cancel_order as cancel_order_svc
        return cancel_order_svc(orderid=orderid, api_key=self.api_key)

    def get_order_status(self, orderid: str) -> ServiceResult:
        from services.orderstatus_service import get_order_status as get_order_status_svc
        return get_order_status_svc(
            status_data={"orderid": orderid},
            api_key=self.api_key,
        )


class SandboxBrokerAdapter(BrokerAdapter):
    """Sandbox routing — same shape as Live but always lands in sandbox.

    Phase 1 implementation: delegates to the same upstream services. They
    auto-detect analyze mode and use sandbox_service internally. If global
    analyze is OFF, this adapter currently still places orders to live —
    Phase 6 will add per-call mode override so strategy.mode='sandbox' is
    truly independent of the global flag.

    SC parity: zero slippage — sandbox_service fills at LTP, no override
    here.
    """

    mode = "sandbox"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def place_order(self, order_data: dict) -> ServiceResult:
        from services.place_order_service import place_order as place_order_svc
        return place_order_svc(
            order_data=_ensure_apikey(order_data, self.api_key),
            api_key=self.api_key,
        )

    def place_options_order(self, options_data: dict) -> ServiceResult:
        from services.place_options_order_service import place_options_order as options_svc
        return options_svc(
            options_data=_ensure_apikey(options_data, self.api_key),
            api_key=self.api_key,
        )

    def place_options_multiorder(self, multiorder_data: dict) -> ServiceResult:
        from services.options_multiorder_service import place_options_multiorder as multi_svc
        return multi_svc(
            multiorder_data=_ensure_apikey(multiorder_data, self.api_key),
            api_key=self.api_key,
        )

    def basket_order(self, basket_data: dict) -> ServiceResult:
        from services.basket_order_service import place_basket_order
        return place_basket_order(
            basket_data=_ensure_apikey(basket_data, self.api_key),
            api_key=self.api_key,
        )

    def cancel_order(self, orderid: str) -> ServiceResult:
        from services.cancel_order_service import cancel_order as cancel_order_svc
        return cancel_order_svc(orderid=orderid, api_key=self.api_key)

    def get_order_status(self, orderid: str) -> ServiceResult:
        from services.orderstatus_service import get_order_status as get_order_status_svc
        return get_order_status_svc(
            status_data={"orderid": orderid},
            api_key=self.api_key,
        )


def get_adapter(mode: str, api_key: str) -> BrokerAdapter:
    """Factory: select the right adapter for a strategy run's mode."""
    mode = (mode or "live").lower()
    if mode == "sandbox":
        return SandboxBrokerAdapter(api_key)
    return LiveBrokerAdapter(api_key)
