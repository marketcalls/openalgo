"""A demanded native reduction cannot silently become an ordinary order."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]


def load_file(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def order_payload(**changes):
    return {
        "apikey": "synthetic-api-key",
        "strategy": "test-native-reduction",
        "exchange": "CRYPTO",
        "symbol": "TEST30JAN30100PE",
        "action": "SELL",
        "quantity": 250,
        "pricetype": "MARKET",
        "product": "NRML",
        **changes,
    }


@pytest.fixture
def bridge(monkeypatch):
    # Exercise the real route/schema/service without importing all API routes.
    schemas = load_file("delta_reduce_only_schemas", "restx_api/schemas.py")
    package = types.ModuleType("restx_api")
    package.__path__ = [str(ROOT / "restx_api")]
    monkeypatch.setitem(sys.modules, "restx_api", package)
    monkeypatch.setitem(sys.modules, "restx_api.schemas", schemas)
    service = load_file("delta_reduce_only_service", "services/place_order_service.py")
    monkeypatch.setitem(sys.modules, "services.place_order_service", service)
    limiter = types.ModuleType("limiter")
    limiter.limiter = types.SimpleNamespace(limit=lambda *args, **kwargs: lambda method: method)
    monkeypatch.setitem(sys.modules, "limiter", limiter)
    route = load_file("delta_reduce_only_route", "restx_api/place_order.py")

    from broker.deltaexchange.api import order_api
    from broker.deltaexchange.mapping import transform_data
    from services import order_router_service

    monkeypatch.setattr(service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(
        service, "get_auth_token_broker", lambda key: ("synthetic-auth", "deltaexchange")
    )
    monkeypatch.setattr(service, "import_broker_module", lambda broker: order_api)
    monkeypatch.setattr(service.bus, "publish", lambda event: None)
    monkeypatch.setattr(order_router_service, "should_route_to_pending", lambda *args: False)
    monkeypatch.setattr(order_api, "get_token", lambda *args: "7")
    monkeypatch.setattr("database.leverage_db.get_leverage", lambda: 0)
    monkeypatch.setenv("DELTA_DEFAULT_LEVERAGE", "")
    monkeypatch.setattr(transform_data, "get_br_symbol", lambda *args: "P-TEST-100-300130")
    monkeypatch.setattr(transform_data, "get_symbol_info", lambda *args: None)
    submitted = []

    def submit(endpoint, auth, method="GET", payload=None, **kwargs):
        assert endpoint == "/v2/orders" and method == "POST"
        submitted.append(json.loads(payload))
        return {"success": True, "result": {"id": 1234, "product_id": 7}}

    monkeypatch.setattr(order_api, "get_api_response", submit)
    app = Flask(__name__)

    def post(body):
        with app.test_request_context("/api/v1/placeorder", method="POST", json=body):
            return route.PlaceOrder().post()

    return types.SimpleNamespace(post=post, submitted=submitted, service=service)


def test_rest_reduce_only_true_reaches_native_delta_order(bridge):
    response = bridge.post(order_payload(reduce_only=True))
    assert response.status_code == 200
    assert response.get_json()["orderid"] == "7:1234"
    assert bridge.submitted == [
        {
            "product_id": 7,
            "product_symbol": "P-TEST-100-300130",
            "size": 250,
            "side": "sell",
            "order_type": "market_order",
            "time_in_force": "gtc",
            "reduce_only": True,
        }
    ]


@pytest.mark.parametrize("value", [False, "absent"])
def test_false_or_absent_keeps_existing_native_default(bridge, value):
    body = order_payload() if value == "absent" else order_payload(reduce_only=value)
    assert bridge.post(body).status_code == 200
    assert "reduce_only" not in bridge.submitted[0]


@pytest.mark.parametrize("broker", ["dhan", "zerodha"])
@pytest.mark.parametrize("value", [False, "absent"])
def test_ordinary_other_broker_order_keeps_existing_behavior(bridge, monkeypatch, broker, value):
    submitted = []

    def submit(body, auth):
        submitted.append(body)
        return types.SimpleNamespace(status=200), {"status": "success"}, "synthetic-order"

    monkeypatch.setattr(
        bridge.service, "get_auth_token_broker", lambda key: ("synthetic-auth", broker)
    )
    monkeypatch.setattr(
        bridge.service,
        "import_broker_module",
        lambda name: types.SimpleNamespace(place_order_api=submit),
    )
    body = order_payload() if value == "absent" else order_payload(reduce_only=value)
    assert bridge.post(body).status_code == 200
    assert len(submitted) == 1
    if value == "absent":
        assert "reduce_only" not in submitted[0]
    else:
        assert submitted[0]["reduce_only"] is False


@pytest.mark.parametrize("value", ["true", "false", "1", "0", 1, 0, 1.0, [], {}, None])
def test_non_boolean_is_refused_before_native_submission(bridge, value):
    assert bridge.post(order_payload(reduce_only=value)).status_code == 400
    valid, _, error = bridge.service.validate_order_data(order_payload(reduce_only=value))
    assert not valid and "reduce_only" in error
    assert bridge.submitted == []


@pytest.mark.parametrize(
    "broker,analyze",
    [
        ("dhan", False),
        ("zerodha", False),
        ("deltaexchange", True),
    ],
)
def test_unsupported_route_is_refused_before_native_submission(
    bridge, monkeypatch, broker, analyze
):
    monkeypatch.setattr(
        bridge.service, "get_auth_token_broker", lambda key: ("synthetic-auth", broker)
    )
    monkeypatch.setattr(bridge.service, "get_analyze_mode", lambda: analyze)
    response = bridge.post(order_payload(reduce_only=True))
    assert response.status_code == 422
    assert response.get_json()["failure_class"] == "unsupported_reduce_only"
    assert response.get_json()["data"] == {}
    assert bridge.submitted == []


@pytest.mark.parametrize(
    "broker,analyze",
    [
        ("dhan", False),
        ("zerodha", False),
        ("deltaexchange", True),
    ],
)
def test_semi_auto_refusal_precedes_pending_queue(bridge, monkeypatch, broker, analyze):
    from services import order_router_service

    queued = []
    monkeypatch.setattr(order_router_service, "should_route_to_pending", lambda *args: True)
    monkeypatch.setattr(order_router_service, "queue_order", lambda *args: queued.append(args))
    monkeypatch.setattr(
        bridge.service, "get_auth_token_broker", lambda key: ("synthetic-auth", broker)
    )
    monkeypatch.setattr(bridge.service, "get_analyze_mode", lambda: analyze)
    response = bridge.post(order_payload(reduce_only=True))
    assert response.status_code == 422
    assert response.get_json()["failure_class"] == "unsupported_reduce_only"
    assert queued == [] and bridge.submitted == []


def test_semi_auto_invalid_auth_refuses_before_pending_queue(bridge, monkeypatch):
    from services import order_router_service

    queued = []
    monkeypatch.setattr(order_router_service, "should_route_to_pending", lambda *args: True)
    monkeypatch.setattr(order_router_service, "queue_order", lambda *args: queued.append(args))
    monkeypatch.setattr(bridge.service, "get_auth_token_broker", lambda key: (None, None))
    assert bridge.post(order_payload(reduce_only=True)).status_code == 403
    assert queued == [] and bridge.submitted == []


@pytest.mark.parametrize("value", [False, "absent", True])
def test_supported_pending_queue_preserves_existing_payload(bridge, monkeypatch, value):
    from services import order_router_service

    queued = []
    monkeypatch.setattr(order_router_service, "should_route_to_pending", lambda *args: True)

    def queue(api_key, body, api_type):
        queued.append(body)
        return True, {"status": "success", "data": {"queued": True}}, 202

    monkeypatch.setattr(order_router_service, "queue_order", queue)
    body = order_payload() if value == "absent" else order_payload(reduce_only=value)
    assert bridge.post(body).status_code == 202
    if value == "absent":
        assert "reduce_only" not in queued[0]
    else:
        assert queued[0]["reduce_only"] is value
    assert bridge.submitted == []


def test_final_dispatch_rechecks_analyze_mode(bridge, monkeypatch):
    monkeypatch.setattr(bridge.service, "get_analyze_mode", lambda: True)
    body = order_payload(reduce_only=True)
    success, response, status = bridge.service.place_order_with_auth(
        body, "synthetic-auth", "deltaexchange", body
    )
    assert not success and status == 422
    assert response["failure_class"] == "unsupported_reduce_only"
    assert bridge.submitted == []


def test_existing_force_live_route_keeps_native_reduce_only(bridge, monkeypatch):
    monkeypatch.setattr(bridge.service, "get_analyze_mode", lambda: True)
    body = order_payload(reduce_only=True)
    success, _, status = bridge.service.place_order_with_auth(
        body, "synthetic-auth", "deltaexchange", body, force_live=True
    )
    assert success and status == 200
    assert bridge.submitted[0]["reduce_only"] is True


def test_force_live_cannot_bypass_broker_reduce_only_capability(bridge):
    body = order_payload(reduce_only=True)
    success, response, status = bridge.service.place_order_with_auth(
        body, "synthetic-auth", "dhan", body, force_live=True
    )
    assert not success and status == 422
    assert response["failure_class"] == "unsupported_reduce_only"
    assert bridge.submitted == []
