from types import SimpleNamespace

import pytest

from events import OrderFailedEvent, OrderPlacedEvent, SmartOrderNoActionEvent
from services import place_smart_order_service, sandbox_service


def _base_order(**overrides):
    payload = {
        "apikey": "test-api-key",
        "strategy": "pytest",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "SELL",
        "product": "MIS",
        "pricetype": "MARKET",
        "quantity": "0",
        "position_size": "0",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "noop_message",
    [
        "No OpenPosition Found. Not placing Exit order.",
        "No open position found. Not placing exit order.",
        "Position already at target size",
        "No position to square off",
        "Position already matches target size of 10",
        "No action needed. Position size matches current position",
    ],
)
def test_live_smart_order_noop_messages_return_200_and_publish_no_action_event(
    monkeypatch, noop_message
):
    published = []
    monkeypatch.setattr(place_smart_order_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(place_smart_order_service.bus, "publish", published.append)

    fake_broker = SimpleNamespace(
        place_smartorder_api=lambda _data, _auth: (
            None,
            {"status": "success", "message": noop_message},
            None,
        )
    )
    monkeypatch.setattr(
        place_smart_order_service, "import_broker_module", lambda _name: fake_broker
    )

    order = _base_order()
    ok, body, status = place_smart_order_service.place_smart_order_with_auth(
        order_data=order.copy(),
        auth_token="token",
        broker="angel",
        original_data=order.copy(),
    )

    assert ok is True
    assert status == 200
    assert body["status"] == "success"
    assert len(published) == 1
    assert isinstance(published[0], SmartOrderNoActionEvent)


def test_sandbox_smart_order_preserves_pricetype():
    captured = {}

    class FakePositionManager:
        def get_open_positions(self):
            return True, {"data": []}, 200

    class FakeOrderManager:
        def place_order(self, data):
            captured.update(data)
            return True, {"status": "success", "orderid": "SBX1", "mode": "analyze"}, 200

    order = _base_order(action="BUY", pricetype="LIMIT", price="750.5", quantity="10", position_size="10")
    ok, _resp, status = sandbox_service._place_smart_order_locked(
        position_manager=FakePositionManager(),
        order_manager=FakeOrderManager(),
        order_data=order,
        symbol="SBIN",
        exchange="NSE",
        product="MIS",
        target_quantity=10,
        original_quantity=10,
    )

    assert ok is True
    assert status == 200
    assert captured["price_type"] == "LIMIT"


def test_sandbox_smart_order_failure_publishes_order_failed_event(monkeypatch):
    published = []
    monkeypatch.setattr(place_smart_order_service, "get_analyze_mode", lambda: True)
    monkeypatch.setattr(place_smart_order_service.bus, "publish", published.append)
    monkeypatch.setattr(
        sandbox_service,
        "sandbox_place_smart_order",
        lambda _data, _key, _orig: (
            False,
            {"status": "error", "message": "Insufficient funds", "mode": "analyze"},
            400,
        ),
    )

    order = _base_order(action="BUY", quantity="10", position_size="10")
    ok, body, status = place_smart_order_service.place_smart_order_with_auth(
        order_data=order.copy(),
        auth_token="token",
        broker="angel",
        original_data=order.copy(),
    )

    assert ok is False
    assert status == 400
    assert body["status"] == "error"
    assert len(published) == 1
    assert isinstance(published[0], OrderFailedEvent)
    assert not any(isinstance(ev, OrderPlacedEvent) for ev in published)
