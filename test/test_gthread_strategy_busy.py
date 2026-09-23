"""A broker queue refusal reaches the trader as a sentence and HTTP 429.

Under the gthread worker a broker request whose turn would come too late is
refused with ``utils.broker_backpressure.BrokerBusyError`` rather than holding a
request thread for the whole wait. The order services used to fold every
exception from the broker call into "internal error" and 500, which reads as a
fault and invites the wrong retry. Each now answers 429 with the error's own
sentence and publishes the same failure event as before. Under eventlet and the
development server the error is never raised, so nothing changes there.
"""

from types import SimpleNamespace

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from utils.broker_backpressure import BROKER_BUSY_MESSAGE, BrokerBusyError


class _BusyBroker:
    """Every broker call refuses, as a limiter under gthread would."""

    def __getattr__(self, name):
        def refuse(*_args, **_kwargs):
            raise BrokerBusyError(retry_after=42.0)

        return refuse


@pytest.fixture
def published(monkeypatch):
    from utils.event_bus import bus

    events = []
    monkeypatch.setattr(bus, "publish", lambda event: events.append(event))
    return events


def _live(monkeypatch, module, loader="import_broker_module"):
    monkeypatch.setattr(module, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(module, loader, lambda broker: _BusyBroker())


def _assert_busy(result, published):
    ok, body, code = result
    assert ok is False
    assert code == 429
    assert body == {"status": "error", "message": BROKER_BUSY_MESSAGE}
    assert published, "no failure event was published"


def test_place_order(monkeypatch, published):
    import services.place_order_service as module

    _live(monkeypatch, module)
    order = {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": "1"}
    _assert_busy(module.place_order_with_auth(order, "t", "b", {"apikey": "k"}), published)


def test_place_smart_order(monkeypatch, published):
    import services.place_smart_order_service as module

    _live(monkeypatch, module)
    monkeypatch.setattr(module, "validate_smart_order", lambda data: (True, None))
    order = {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": "1"}
    _assert_busy(module.place_smart_order_with_auth(order, "t", "b", {"apikey": "k"}), published)


def test_cancel_order(monkeypatch, published):
    import services.cancel_order_service as module

    _live(monkeypatch, module)
    _assert_busy(module.cancel_order_with_auth("OID1", "t", "b", {"apikey": "k"}), published)


def test_cancel_all_orders(monkeypatch, published):
    import services.cancel_all_order_service as module

    _live(monkeypatch, module)
    _assert_busy(module.cancel_all_orders_with_auth({}, "t", "b", {"apikey": "k"}), published)


def test_modify_order(monkeypatch, published):
    import services.modify_order_service as module

    _live(monkeypatch, module)
    order = {"orderid": "OID1", "symbol": "SBIN"}
    _assert_busy(module.modify_order_with_auth(order, "t", "b", {"apikey": "k"}), published)


def test_close_position(monkeypatch, published):
    import services.close_position_service as module

    _live(monkeypatch, module)
    _assert_busy(module.close_position_with_auth({}, "t", "b", {"apikey": "k"}), published)


def test_place_gtt_order(monkeypatch, published):
    import services.place_gtt_order_service as module

    _live(monkeypatch, module, loader="import_broker_gtt_module")
    order = {"symbol": "SBIN", "exchange": "NSE", "trigger_type": "SINGLE"}
    _assert_busy(module.place_gtt_order_with_auth(order, "t", "b", {"apikey": "k"}), published)


def test_modify_gtt_order(monkeypatch, published):
    import services.modify_gtt_order_service as module

    _live(monkeypatch, module, loader="import_broker_gtt_module")
    order = {"trigger_id": "T1", "symbol": "SBIN"}
    _assert_busy(module.modify_gtt_order_with_auth(order, "t", "b", {"apikey": "k"}), published)


def test_cancel_gtt_order(monkeypatch, published):
    import services.cancel_gtt_order_service as module

    _live(monkeypatch, module, loader="import_broker_gtt_module")
    _assert_busy(module.cancel_gtt_order_with_auth("T1", "t", "b", {"apikey": "k"}), published)


def test_a_basket_leg_carries_the_sentence():
    import services.basket_order_service as module

    leg = module.place_single_order({"symbol": "SBIN"}, _BusyBroker(), "t", 1, 0)

    assert leg == {"symbol": "SBIN", "status": "error", "message": BROKER_BUSY_MESSAGE}


def test_a_split_leg_carries_the_sentence():
    import services.split_order_service as module

    leg = module.place_single_order({"symbol": "SBIN", "quantity": "5"}, _BusyBroker(), "t", 1, 2)

    assert leg["status"] == "error"
    assert leg["message"] == BROKER_BUSY_MESSAGE


def test_an_options_order_refused_while_resolving_is_a_429(monkeypatch):
    import services.place_options_order_service as module

    def refuse(*_args, **_kwargs):
        raise BrokerBusyError()

    monkeypatch.setattr(module, "get_option_symbol", refuse)
    options = {
        "apikey": "k",
        "strategy": "s",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28MAY26",
        "offset": "ATM",
        "option_type": "CE",
        "action": "BUY",
        "quantity": "75",
        "pricetype": "MARKET",
        "product": "MIS",
    }

    ok, body, code = module.place_options_order(options, api_key="k")

    assert (ok, code) == (False, 429)
    assert body == {"status": "error", "message": BROKER_BUSY_MESSAGE}


def test_an_options_leg_refused_while_resolving_carries_the_sentence(monkeypatch):
    import services.options_multiorder_service as module

    def refuse(*_args, **_kwargs):
        raise BrokerBusyError()

    monkeypatch.setattr(module, "resolve_leg_symbol", refuse)
    monkeypatch.setattr(module, "resolve_leg_symbol_by_strike", refuse)
    leg = {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": "75"}
    common = {"underlying": "NIFTY", "exchange": "NSE_INDEX", "expiry_date": "28MAY26"}

    result = module.resolve_and_place_leg(leg, common, "k", 0, 1)

    assert result["status"] == "error"
    assert result["message"] == BROKER_BUSY_MESSAGE


def test_an_ordinary_broker_failure_still_reads_as_before(monkeypatch, published):
    """Only the busy refusal changed; any other exception is the old 500."""
    import services.place_order_service as module

    monkeypatch.setattr(module, "get_analyze_mode", lambda: False)
    broken = SimpleNamespace(place_order_api=lambda *a: (_ for _ in ()).throw(ValueError("x")))
    monkeypatch.setattr(module, "import_broker_module", lambda broker: broken)

    ok, body, code = module.place_order_with_auth(
        {"symbol": "SBIN", "exchange": "NSE"}, "t", "b", {"apikey": "k"}
    )

    assert (ok, code) == (False, 500)
    assert body["message"] == "Failed to place order due to internal error"
