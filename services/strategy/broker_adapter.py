"""BrokerAdapter — single abstraction over live broker and sandbox.

The strategy engine uses ONLY this interface to place / cancel / query orders.
It never imports services.place_order_service, services.basket_order_service,
services.sandbox_service, etc. directly. That isolation is what gives us:

  - Clean live/sandbox parity (one engine, two adapters).
  - Drop-in mocks for unit tests.
  - A single place to enforce kill-switch / audit / rate-limiting cross-cuts.

Phase 0 ships the abstract interface. LiveBrokerAdapter and SandboxBrokerAdapter
are filled in during Phase 1 once the leg resolver and execution service land.

The four placement methods mirror existing services so the adapter implementation
stays thin:

  place_order              → services/place_order_service.place_order
  place_options_order      → services/place_options_order_service.place_options_order
  place_options_multiorder → services/options_multiorder_service.place_options_multiorder
  basket_order             → services/basket_order_service.place_basket_order

NOTE: place_smart_order_service is intentionally NOT in this interface.
The strategy engine resolves exits via the explicit price_order path with
symbol read from strategy_positions — see plan §5.2 + §5.3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Tuple

# Triple = (success: bool, response: dict, http_status: int) — matches the
# convention used across services/ for consistency.
ServiceResult = Tuple[bool, dict, int]


class BrokerAdapter(ABC):
    """Abstract base. Concrete implementations: LiveBrokerAdapter, SandboxBrokerAdapter."""

    #: 'live' | 'sandbox' — used by callers for logging and routing decisions.
    mode: str = ""

    # ---------------- Order placement ----------------

    @abstractmethod
    def place_order(self, order_data: dict) -> ServiceResult:
        """Place a single order with an explicit symbol.

        order_data fields (matches services.place_order_service.place_order):
          strategy, symbol, exchange, action, quantity, pricetype, product,
          price?, trigger_price?, disclosed_quantity?
        """

    @abstractmethod
    def place_options_order(self, options_data: dict) -> ServiceResult:
        """Place a single options order with strike resolution from offset.

        options_data fields:
          underlying, exchange, expiry_date, strike_int?, offset, option_type,
          action, quantity, pricetype, product, strategy?, splitsize?
        """

    @abstractmethod
    def place_options_multiorder(self, multiorder_data: dict) -> ServiceResult:
        """Place multiple option legs with shared underlying. BUYs go first
        for margin efficiency.

        multiorder_data fields:
          underlying, exchange, expiry_date?, strategy?, legs[]
        """

    @abstractmethod
    def basket_order(self, basket_data: dict) -> ServiceResult:
        """Place a basket of explicit-symbol orders in one call.

        basket_data fields:
          strategy?, orders[] — each with symbol, exchange, action, quantity,
          pricetype, product
        """

    # ---------------- Cancellation + status ----------------

    @abstractmethod
    def cancel_order(self, orderid: str) -> ServiceResult:
        """Cancel a single open order by broker order id."""

    @abstractmethod
    def get_order_status(self, orderid: str) -> ServiceResult:
        """Fetch the current status of an order. Used by the order_update_channel
        poll fallback when the broker WS is unavailable."""

    # ---------------- Convenience metadata ----------------

    def __repr__(self) -> str:
        return f"<{type(self).__name__} mode={self.mode!r}>"
