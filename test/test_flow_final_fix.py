"""Focused regressions for the final Flow contract review.

These tests exercise the executor-to-client boundary.  The fake client records
every method invocation so an invalid runtime value cannot hide behind a
successful validation response or a broker-side default.
"""

from __future__ import annotations

from typing import Any

import pytest

import services.place_smart_order_service as smart_service
from services.flow_executor_service import NodeExecutor, WorkflowContext
from services.flow_workflow_validator import validate_workflow


class RecordingFlowClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, method: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, kwargs))
        return {"status": "success", "orderid": f"{method}-1"}

    def place_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("place_order", **kwargs)

    def place_smart_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("place_smart_order", **kwargs)

    def options_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("options_order", **kwargs)

    def options_multi_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("options_multi_order", **kwargs)

    def basket_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("basket_order", **kwargs)

    def split_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("split_order", **kwargs)

    def margin(self, **kwargs: Any) -> dict[str, Any]:
        return self._record("margin", **kwargs)

    def get_expiry(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_expiry", kwargs))
        return {"status": "success", "data": ["27-AUG-26"]}


def _executor(runtime_value: Any = None) -> tuple[NodeExecutor, RecordingFlowClient]:
    context = WorkflowContext()
    context.set_variable("runtime", runtime_value)
    client = RecordingFlowClient()
    executor = NodeExecutor(client, context, [])
    # Lot-size lookup is a database concern.  Runtime order validation must
    # happen before it, but valid option-order tests still need a deterministic
    # contract size.
    executor._resolve_lot_size = lambda underlying, exchange: 10  # type: ignore[method-assign]
    return executor, client


def _order_data(node_type: str, *, quantity: Any = 1, price: Any = 100) -> dict[str, Any]:
    common = {
        "action": "BUY",
        "product": "MIS",
        "priceType": "LIMIT",
        "price": price,
    }
    if node_type == "placeOrder":
        return {**common, "symbol": "SBIN", "exchange": "NSE", "quantity": quantity}
    if node_type == "smartOrder":
        return {
            **common,
            "symbol": "SBIN",
            "exchange": "NSE",
            "quantity": quantity,
            "positionSize": 0,
        }
    if node_type == "optionsOrder":
        return {
            **common,
            "underlying": "NIFTY",
            "expiryType": "current_week",
            "offset": "ATM",
            "optionType": "CE",
            "quantity": quantity,
        }
    if node_type == "optionsMultiOrder":
        return {
            **common,
            "underlying": "NIFTY",
            "expiryType": "current_week",
            "strategy": "straddle",
            "quantity": quantity,
        }
    if node_type == "basketOrder":
        return {
            **common,
            "orders": [
                {
                    "symbol": "SBIN",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": quantity,
                }
            ],
        }
    if node_type == "splitOrder":
        return {
            **common,
            "symbol": "SBIN",
            "exchange": "NSE",
            "quantity": quantity,
            "splitSize": 1,
        }
    raise AssertionError(f"Unhandled node type {node_type}")


def _execute(executor: NodeExecutor, node_type: str, data: dict[str, Any]) -> dict[str, Any]:
    method = {
        "placeOrder": executor.execute_place_order,
        "smartOrder": executor.execute_smart_order,
        "optionsOrder": executor.execute_options_order,
        "optionsMultiOrder": executor.execute_options_multi_order,
        "basketOrder": executor.execute_basket_order,
        "splitOrder": executor.execute_split_order,
    }[node_type]
    return method(data)


@pytest.mark.parametrize(
    "runtime_value",
    ["not-a-number", -1, True, float("nan"), float("inf"), 10**400, ""],
    ids=["nonnumeric", "negative", "boolean", "nan", "infinity", "overflow", "blank"],
)
@pytest.mark.parametrize(
    "node_type",
    [
        "placeOrder",
        "smartOrder",
        "optionsOrder",
        "optionsMultiOrder",
        "basketOrder",
        "splitOrder",
    ],
)
def test_resolved_invalid_quantity_never_reaches_any_order_client(node_type, runtime_value):
    """A supplied bad quantity must not become one (or any other order size)."""
    executor, client = _executor(runtime_value)
    result = _execute(executor, node_type, _order_data(node_type, quantity="{{runtime}}"))

    assert result["status"] == "error"
    assert client.calls == []


@pytest.mark.parametrize(
    "node_type",
    ["placeOrder", "optionsOrder", "optionsMultiOrder", "basketOrder", "splitOrder"],
)
def test_resolved_zero_quantity_is_rejected_outside_smart_order(node_type):
    """Only SmartOrder may use an explicit zero as an executable instruction."""
    executor, client = _executor(0)

    result = _execute(executor, node_type, _order_data(node_type, quantity="{{runtime}}"))

    assert result["status"] == "error"
    assert client.calls == []


def test_smart_order_keeps_explicit_resolved_zero_quantity():
    """SmartOrder alone uses zero as a valid target-position instruction."""
    executor, client = _executor(0)
    result = executor.execute_smart_order(
        _order_data("smartOrder", quantity="{{runtime}}", price=100)
    )

    assert result["status"] == "success"
    assert client.calls == [
        (
            "place_smart_order",
            {
                "symbol": "SBIN",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": 0,
                "position_size": 0,
                "price_type": "LIMIT",
                "product_type": "MIS",
                "price": 100.0,
                "trigger_price": 0.0,
                "strategy": "flow_workflow",
            },
        )
    ]


@pytest.mark.parametrize(
    "runtime_price",
    [0, float("nan"), float("inf"), float("-inf")],
    ids=["zero", "nan", "infinity", "negative-infinity"],
)
@pytest.mark.parametrize(
    "node_type",
    [
        "placeOrder",
        "smartOrder",
        "optionsOrder",
        "optionsMultiOrder",
        "basketOrder",
        "splitOrder",
    ],
)
def test_invalid_resolved_limit_price_never_reaches_any_order_client(
    node_type, runtime_price
):
    """LIMIT prices must be finite and positive at the final dispatch boundary."""
    executor, client = _executor(runtime_price)
    result = _execute(executor, node_type, _order_data(node_type, price="{{runtime}}"))

    assert result["status"] == "error"
    assert client.calls == []


@pytest.mark.parametrize(
    "runtime_trigger",
    [0, float("nan"), float("inf")],
    ids=["zero", "nan", "infinity"],
)
@pytest.mark.parametrize(
    "node_type",
    [
        "placeOrder",
        "smartOrder",
        "optionsOrder",
        "optionsMultiOrder",
        "basketOrder",
        "splitOrder",
    ],
)
def test_invalid_resolved_stop_trigger_never_reaches_any_order_client(
    node_type, runtime_trigger
):
    """Every effective SL order needs a finite positive trigger before dispatch."""
    executor, client = _executor(runtime_trigger)
    if node_type == "optionsMultiOrder":
        data = {
            "underlying": "NIFTY",
            "expiryType": "current_week",
            "strategy": "custom",
            "quantity": 1,
            "product": "MIS",
            "priceType": "SL",
            "price": 100,
            "triggerPrice": "{{runtime}}",
            "legs": [
                {
                    "offset": "ATM",
                    "optionType": "CE",
                    "action": "BUY",
                    "quantity": 1,
                }
            ],
        }
    else:
        data = _order_data(node_type, price=100)
        data.update({"priceType": "SL", "triggerPrice": "{{runtime}}"})

    result = _execute(executor, node_type, data)

    assert result["status"] == "error"
    assert client.calls == []


def test_validator_accepted_smart_order_constants_are_canonical_at_the_client():
    """Trimmed/lowercase constants accepted on import must not map to broker defaults."""
    data = {
        "symbol": "SBIN",
        "exchange": " nse ",
        "action": " buy ",
        "quantity": 1,
        "positionSize": 0,
        "product": " mis ",
        "priceType": " limit ",
        "price": 100,
    }
    workflow = {
        "name": "canonical-smart-order",
        "nodes": [
            {
                "id": "trigger",
                "type": "webhookTrigger",
                "position": {"x": 0, "y": 0},
                "data": {},
            },
            {
                "id": "order",
                "type": "smartOrder",
                "position": {"x": 0, "y": 100},
                "data": data,
            },
        ],
        "edges": [{"id": "edge", "source": "trigger", "target": "order"}],
    }
    assert validate_workflow(workflow) == []

    executor, client = _executor()
    result = executor.execute_smart_order(data)

    assert result["status"] == "success"
    _, sent = client.calls[0]
    assert sent["exchange"] == "NSE"
    assert sent["action"] == "BUY"
    assert sent["product_type"] == "MIS"
    assert sent["price_type"] == "LIMIT"


def _custom_multi_data(legs: Any) -> dict[str, Any]:
    return {
        "underlying": "NIFTY",
        "expiryType": "current_week",
        "strategy": "custom",
        "quantity": 1,
        "action": "SELL",
        "product": " mis ",
        "priceType": " sl ",
        "price": 110,
        "triggerPrice": 105,
        "legs": legs,
    }


def _strict_action_workflow(node_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": f"strict-{node_type}",
        "nodes": [
            {
                "id": "trigger",
                "type": "webhookTrigger",
                "position": {"x": 0, "y": 0},
                "data": {},
            },
            {
                "id": "action",
                "type": node_type,
                "position": {"x": 0, "y": 100},
                "data": data,
            },
        ],
        "edges": [{"id": "edge", "source": "trigger", "target": "action"}],
    }


@pytest.mark.parametrize("legacy_key", ["legs", "orderLegs"])
def test_custom_multi_validator_applies_common_prices_to_both_leg_spellings(legacy_key):
    """Static activation and runtime agree that omitted leg prices inherit common values."""
    leg = {
        "offset": "ATM",
        "optionType": "CE",
        "action": "BUY",
        "quantity": 1,
        "pricetype": " sl ",
    }
    data = _custom_multi_data(None)
    data.pop("legs")
    data[legacy_key] = [leg]

    assert validate_workflow(_strict_action_workflow("optionsMultiOrder", data)) == []


def test_custom_multi_resolves_raw_legs_and_applies_common_fields_with_overrides():
    """A whole-field list stays structured and each explicit leg value wins."""
    legs = [
        {
            "offset": " atm ",
            "optionType": " ce ",
            "action": " buy ",
            "quantity": 2,
            # Lowercase service spelling must override/inherit exactly like priceType.
            "pricetype": " sl ",
            # This legacy field is deliberately ignored; one common expiry is used.
            "expiryDate": "{{missing.legacy_expiry}}",
        },
        {
            "offset": "otm2",
            "optionType": "pe",
            "action": "sell",
            "quantity": 3,
            "product": " nrml ",
            "priceType": " limit ",
            "price": 120,
            "triggerPrice": 0,
        },
    ]
    executor, client = _executor(legs)

    result = executor.execute_options_multi_order(_custom_multi_data("{{runtime}}"))

    assert result["status"] == "success"
    assert [method for method, _ in client.calls] == ["get_expiry", "options_multi_order"]
    sent = client.calls[-1][1]
    assert sent["expiry_date"] == "27AUG26"
    assert sent["legs"] == [
        {
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 20,
            "pricetype": "SL",
            "product": "MIS",
            "price": 110.0,
            "trigger_price": 105.0,
            "splitsize": 0,
        },
        {
            "offset": "OTM2",
            "option_type": "PE",
            "action": "SELL",
            "quantity": 30,
            "pricetype": "LIMIT",
            "product": "NRML",
            "price": 120.0,
            "trigger_price": 0.0,
            "splitsize": 0,
        },
    ]


@pytest.mark.parametrize("structured_field", ["legs", "orders"])
def test_raw_structured_order_fields_are_left_for_atomic_nested_resolution(structured_field):
    """The graph-level scalar guard must not stringify and pre-reject a raw list."""
    context = WorkflowContext()
    context.set_variable(
        "runtime",
        [
            {
                "quantity": "{{qty}}",
                # Options Multi deliberately ignores this legacy property.
                "expiryDate": "{{missing.legacy_expiry}}",
            }
        ],
    )
    context.set_variable("qty", 2)
    executor = NodeExecutor(RecordingFlowClient(), context, [])

    assert executor.unresolved_order_fields({structured_field: "{{runtime}}"}) == []


def test_custom_multi_resolves_legacy_raw_order_legs():
    """Legacy orderLegs remains executable without lossy list stringification."""
    leg = {
        "offset": "ATM",
        "optionType": "CE",
        "action": "BUY",
        "quantity": 1,
        "product": "MIS",
        "pricetype": "MARKET",
    }
    executor, client = _executor([leg])
    data = _custom_multi_data(None)
    data.pop("legs")
    data["orderLegs"] = "{{runtime}}"
    data["priceType"] = "MARKET"

    result = executor.execute_options_multi_order(data)

    assert result["status"] == "success"
    assert client.calls[-1][1]["legs"][0]["pricetype"] == "MARKET"


@pytest.mark.parametrize(
    "runtime_legs",
    [[], {}, ["not-an-object"], "{{still.missing}}"],
    ids=["empty", "object", "non-object-entry", "unresolved"],
)
def test_custom_multi_requires_a_resolved_nonempty_object_list(runtime_legs):
    """An unusable custom-leg container fails before expiry or placement calls."""
    executor, client = _executor(runtime_legs)

    result = executor.execute_options_multi_order(_custom_multi_data("{{runtime}}"))

    assert result["status"] == "error"
    assert client.calls == []


@pytest.mark.parametrize(
    ("leg_update", "runtime_value", "message_field"),
    [
        ({"offset": "BAD"}, None, "offset"),
        ({"optionType": "XX"}, None, "optionType"),
        ({"action": "HOLD"}, None, "action"),
        ({"quantity": "{{runtime}}"}, "not-a-number", "quantity"),
        ({"product": "BAD"}, None, "product"),
        ({"pricetype": "BAD"}, None, "pricetype"),
        ({"price": "{{runtime}}"}, float("nan"), "price"),
        ({"triggerPrice": "{{runtime}}"}, 0, "trigger"),
    ],
)
def test_custom_multi_rejects_each_invalid_nested_order_field_before_any_client_call(
    leg_update, runtime_value, message_field
):
    """No nested typo may inherit or default into a different executable leg."""
    leg = {
        "offset": "ATM",
        "optionType": "CE",
        "action": "BUY",
        "quantity": 1,
        "product": "MIS",
        "pricetype": "SL",
        "price": 110,
        "triggerPrice": 105,
        **leg_update,
    }
    executor, client = _executor(runtime_value)

    result = executor.execute_options_multi_order(_custom_multi_data([leg]))

    assert result["status"] == "error"
    assert message_field.lower() in result["message"].lower()
    assert client.calls == []


def _smart_service_payload(**updates: Any) -> dict[str, Any]:
    return {
        "apikey": "key",
        "strategy": "flow",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "position_size": 0,
        "pricetype": "MARKET",
        "product": "MIS",
        **updates,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("pricetype", "NOT-A-TYPE"), ("product", "NOT-A-PRODUCT")],
)
def test_smart_order_service_rejects_actual_invalid_payload_keys_before_broker(
    monkeypatch, field, value
):
    """Service validation must guard the keys its broker call really consumes."""

    class Broker:
        def __init__(self) -> None:
            self.calls: list[tuple[dict[str, Any], str]] = []

        def place_smartorder_api(self, order_data, auth_token):
            self.calls.append((order_data, auth_token))
            raise AssertionError("invalid order reached broker placement")

    broker = Broker()
    monkeypatch.setattr(smart_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(smart_service, "import_broker_module", lambda broker_name: broker)
    monkeypatch.setattr(smart_service.bus, "publish", lambda event: None)
    payload = _smart_service_payload(**{field: value})

    success, response, status_code = smart_service.place_smart_order_with_auth(
        payload, "token", "fake", dict(payload)
    )

    assert success is False
    assert status_code == 400
    assert response["status"] == "error"
    assert field.removesuffix("type")[:7] in response["message"].lower()
    assert broker.calls == []


@pytest.mark.parametrize("container", ["list", "object"])
def test_margin_resolves_raw_structured_templates_into_validated_positions(container):
    """A raw list/object template reaches margin as the service's string-valued shape."""
    leg = {
        "symbol": " SBIN ",
        "exchange": " nse ",
        "action": " buy ",
        "quantity": 2,
        "product": " mis ",
        "pricetype": " limit ",
        "price": 100.5,
    }
    executor, client = _executor([leg] if container == "list" else leg)

    result = executor.execute_margin({"positionsJson": "{{runtime}}"})

    assert result["status"] == "success"
    assert [method for method, _ in client.calls] == ["margin"]
    assert client.calls[0][1]["positions"] == [
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "2",
            "product": "MIS",
            "pricetype": "LIMIT",
            "price": "100.5",
        }
    ]


@pytest.mark.parametrize(
    ("runtime_positions", "message_field"),
    [
        ([], "empty"),
        ([{"symbol": "SBIN"}], "exchange"),
        (
            [
                {
                    "symbol": "SBIN",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": "{{missing.qty}}",
                    "product": "MIS",
                    "pricetype": "MARKET",
                }
            ],
            "quantity",
        ),
        (
            [
                {
                    "symbol": "SBIN",
                    "exchange": "BAD",
                    "action": "BUY",
                    "quantity": 1,
                    "product": "MIS",
                    "pricetype": "MARKET",
                }
            ],
            "exchange",
        ),
        (
            [
                {
                    "symbol": "SBIN",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": True,
                    "product": "MIS",
                    "pricetype": "MARKET",
                }
            ],
            "quantity",
        ),
        (
            [
                {
                    "symbol": "SBIN",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": 1,
                    "product": "MIS",
                    "pricetype": "LIMIT",
                    "price": float("inf"),
                }
            ],
            "price",
        ),
    ],
)
def test_margin_rejects_invalid_raw_positions_before_client(runtime_positions, message_field):
    """The executor validates every resolved margin leg atomically."""
    executor, client = _executor(runtime_positions)

    result = executor.execute_margin({"positions": "{{runtime}}"})

    assert result["status"] == "error"
    assert message_field.lower() in result["message"].lower()
    assert client.calls == []


def test_basket_resolves_a_raw_list_template_with_atomic_normalization():
    """A list produced upstream follows the same path as a static imported basket."""
    orders = [
        {
            "symbol": " SBIN ",
            "exchange": " nse ",
            "action": " buy ",
            "quantity": "2",
            "product": " cnc ",
            "pricetype": " limit ",
            "price": 100.5,
        },
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "action": "SELL",
            "quantity": 1,
        },
    ]
    executor, client = _executor(orders)

    result = executor.execute_basket_order(
        {
            "orders": "{{runtime}}",
            "product": " mis ",
            "priceType": " market ",
        }
    )

    assert result["status"] == "success"
    assert client.calls == [
        (
            "basket_order",
            {
                "orders": [
                    {
                        "symbol": "SBIN",
                        "exchange": "NSE",
                        "action": "BUY",
                        "quantity": 2,
                        "product": "CNC",
                        "pricetype": "LIMIT",
                        "price": 100.5,
                        "triggerprice": 0.0,
                    },
                    {
                        "symbol": "INFY",
                        "exchange": "NSE",
                        "action": "SELL",
                        "quantity": 1,
                        "product": "MIS",
                        "pricetype": "MARKET",
                        "price": 0.0,
                        "triggerprice": 0.0,
                    },
                ],
                "strategy": "flow_basket",
            },
        )
    ]


@pytest.mark.parametrize(
    "runtime_orders",
    [{}, [], ["bad-row"], [{"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": "{{missing.qty}}"}]],
    ids=["object", "empty", "non-object-row", "unresolved-nested"],
)
def test_basket_rejects_invalid_raw_list_templates_without_a_partial_client_call(runtime_orders):
    """A malformed resolved basket cannot be reinterpreted as CSV or partly submitted."""
    executor, client = _executor(runtime_orders)

    result = executor.execute_basket_order({"orders": "{{runtime}}"})

    assert result["status"] == "error"
    assert client.calls == []
