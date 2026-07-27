import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import database.auth_db as auth_db
import services.order_router_service as order_router_service
import services.pending_order_execution_service as execution_service
from services.action_center_service import parse_pending_order


def _configure_execution(monkeypatch, api_type, order_data, broker):
    pending_order = SimpleNamespace(
        status="approved",
        order_data=json.dumps(order_data),
        api_type=api_type,
        user_id="test-user",
    )
    updates = []

    monkeypatch.setattr(
        execution_service,
        "get_pending_order_by_id",
        lambda pending_order_id: pending_order,
    )
    monkeypatch.setattr(
        execution_service,
        "get_api_key_for_tradingview",
        lambda user_id: "test-api-key",
    )
    monkeypatch.setattr(
        execution_service,
        "get_auth_token",
        lambda user_id: "test-auth-token",
    )
    monkeypatch.setattr(
        execution_service,
        "update_broker_status",
        lambda pending_order_id, broker_order_id, broker_status: updates.append(
            (pending_order_id, broker_order_id, broker_status)
        ),
    )

    class AuthQuery:
        def filter_by(self, **kwargs):
            assert kwargs == {"name": "test-user"}
            return self

        def first(self):
            return SimpleNamespace(broker=broker)

    monkeypatch.setattr(auth_db, "Auth", SimpleNamespace(query=AuthQuery()))
    return updates


def _pending_for_display(api_type, order_data):
    return SimpleNamespace(
        id=42,
        user_id="test-user",
        api_type=api_type,
        order_data=json.dumps(order_data),
        status="pending",
        created_at_ist="2026-07-10 12:00:00 IST",
        approved_at_ist=None,
        approved_by=None,
        rejected_at_ist=None,
        rejected_by=None,
        rejected_reason=None,
        broker_order_id=None,
        broker_status=None,
    )


def test_options_multiorder_dispatch_tracks_nested_child_orders(monkeypatch):
    order_data = {
        "strategy": "iron-condor",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "30JUL26",
        "legs": [{"action": "BUY"}, {"action": "SELL"}],
    }
    updates = _configure_execution(monkeypatch, "optionsmultiorder", order_data, "zerodha")

    def fake_place_options_multiorder(**kwargs):
        assert kwargs == {
            "multiorder_data": order_data,
            "api_key": "test-api-key",
            "auth_token": "test-auth-token",
            "broker": "zerodha",
        }
        return (
            True,
            {
                "status": "success",
                "results": [
                    {"status": "success", "orderid": "ORDER-1"},
                    {
                        "status": "success",
                        "split_results": [
                            {"status": "success", "orderid": "ORDER-2"},
                            {"status": "error", "message": "rejected"},
                        ],
                    },
                ],
            },
            200,
        )

    monkeypatch.setitem(
        sys.modules,
        "services.options_multiorder_service",
        SimpleNamespace(place_options_multiorder=fake_place_options_multiorder),
    )

    success, response, status_code = execution_service.execute_approved_order(42)

    assert success is True
    assert status_code == 200
    assert response["broker_order_ids"] == ["ORDER-1", "ORDER-2"]
    assert response["broker_order_id"] == "ORDER-1,ORDER-2"
    assert updates == [(42, "ORDER-1,ORDER-2", "partial")]


def test_options_multiorder_rejects_when_no_child_order_was_submitted(monkeypatch):
    updates = _configure_execution(
        monkeypatch,
        "optionsmultiorder",
        {"underlying": "NIFTY", "exchange": "NSE_INDEX", "legs": [{"action": "BUY"}]},
        "zerodha",
    )
    monkeypatch.setitem(
        sys.modules,
        "services.options_multiorder_service",
        SimpleNamespace(
            place_options_multiorder=lambda **kwargs: (
                True,
                {
                    "status": "success",
                    "results": [{"status": "error", "message": "rejected"}],
                },
                200,
            )
        ),
    )

    success, response, status_code = execution_service.execute_approved_order(42)

    assert success is False
    assert status_code == 502
    assert response["status"] == "error"
    assert response["message"] == "No child orders were submitted successfully"
    assert updates == [(42, None, "rejected")]


@pytest.mark.parametrize("broker", ["dhan", "zerodha"])
def test_place_gtt_dispatch_tracks_trigger_for_pilot_brokers(monkeypatch, broker):
    order_data = {
        "strategy": "gtt-test",
        "trigger_type": "SINGLE",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
    }
    updates = _configure_execution(monkeypatch, "placegttorder", order_data, broker)

    def fake_place_gtt_order(**kwargs):
        assert kwargs == {
            "order_data": order_data,
            "api_key": "test-api-key",
            "auth_token": "test-auth-token",
            "broker": broker,
        }
        return True, {"status": "success", "trigger_id": "TRIGGER-1"}, 200

    monkeypatch.setattr(
        "services.place_gtt_order_service.place_gtt_order",
        fake_place_gtt_order,
    )

    success, response, status_code = execution_service.execute_approved_order(42)

    assert success is True
    assert status_code == 200
    assert response["broker_order_id"] == "TRIGGER-1"
    assert updates == [(42, "TRIGGER-1", "open")]


def test_place_gtt_preserves_capability_failure(monkeypatch):
    updates = _configure_execution(
        monkeypatch,
        "placegttorder",
        {"trigger_type": "SINGLE", "symbol": "RELIANCE"},
        "unsupported",
    )
    monkeypatch.setattr(
        "services.place_gtt_order_service.place_gtt_order",
        lambda **kwargs: (
            False,
            {
                "status": "error",
                "message": "GTT orders are not supported for broker 'unsupported' yet",
            },
            501,
        ),
    )

    success, response, status_code = execution_service.execute_approved_order(42)

    assert success is False
    assert status_code == 501
    assert "not supported" in response["message"]
    assert updates == [(42, None, "rejected")]


def test_dhan_created_response_is_a_successful_gtt(monkeypatch):
    import services.place_gtt_order_service as gtt_service

    fake_response = SimpleNamespace(status=201)
    fake_broker_module = SimpleNamespace(
        place_gtt_order=lambda order_data, auth_token: (
            fake_response,
            {"orderId": "DHAN-TRIGGER"},
            "DHAN-TRIGGER",
        )
    )
    monkeypatch.setattr(gtt_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(gtt_service, "import_broker_gtt_module", lambda broker: fake_broker_module)
    monkeypatch.setattr(gtt_service.bus, "publish", lambda event: None)

    success, response, status_code = gtt_service.place_gtt_order_with_auth(
        {
            "trigger_type": "SINGLE",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "trigger_price": 100,
        },
        "test-auth-token",
        "dhan",
        {"apikey": "test-api-key"},
    )

    assert success is True
    assert response == {"status": "success", "trigger_id": "DHAN-TRIGGER"}
    assert status_code == 200


def test_only_pilot_brokers_ship_gtt_modules():
    repository_root = Path(__file__).resolve().parents[1]
    brokers = {
        path.parent.parent.name for path in (repository_root / "broker").glob("*/api/gtt_api.py")
    }
    assert brokers == {"dhan", "zerodha"}


def test_queue_order_remains_successful_when_notification_fails(monkeypatch):
    monkeypatch.setattr(order_router_service, "verify_api_key", lambda api_key: "test-user")
    monkeypatch.setattr(
        order_router_service,
        "create_pending_order",
        lambda user_id, api_type, order_data: 73,
    )
    monkeypatch.setattr(
        order_router_service.socketio,
        "start_background_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("socket unavailable")),
    )

    success, response, status_code = order_router_service.queue_order(
        "test-api-key",
        {"strategy": "test", "apikey": "test-api-key"},
        "placeorder",
    )

    assert success is True
    assert status_code == 200
    assert response["pending_order_id"] == 73


def test_action_center_parses_options_multiorder_summary():
    parsed = parse_pending_order(
        _pending_for_display(
            "optionsmultiorder",
            {
                "strategy": "iron-condor",
                "underlying": "NIFTY",
                "exchange": "NSE_INDEX",
                "legs": [
                    {"action": "BUY", "quantity": 50, "product": "NRML"},
                    {"action": "SELL", "quantity": 50, "product": "NRML"},
                ],
            },
        )
    )

    assert parsed["symbol"] == "NIFTY (2 legs)"
    assert parsed["action"] == "MULTI"
    assert parsed["quantity"] == 100
    assert parsed["product_type"] == "NRML"


def test_action_center_parses_gtt_summary():
    parsed = parse_pending_order(
        _pending_for_display(
            "placegttorder",
            {
                "strategy": "gtt-test",
                "trigger_type": "OCO",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "action": "SELL",
                "quantity": 1,
                "price": 100,
                "triggerprice_sl": 95,
                "triggerprice_tg": 110,
                "pricetype": "LIMIT",
                "product": "CNC",
            },
        )
    )

    assert parsed["symbol"] == "RELIANCE"
    assert parsed["action"] == "SELL"
    assert parsed["trigger_price"] == "95 / 110"
    assert parsed["product_type"] == "CNC"
