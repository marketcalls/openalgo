"""The charges API: what an order costs, before it is placed.

``POST /api/v1/charges`` answers with brokerage and statutory charges for one
order, under the brokerage plan saved on /sandbox/commissions. It calls no
broker. The figures are the ones a sandbox fill of the same order pays, laid
out as ``charges.total``, ``charges.brokerage``, ``charges.taxes`` and
``charges.other_charges``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from flask import Flask
from flask_restx import Api
from test_gthread_sandbox_support import (
    configs_restored,
    prepare_databases,
    quote,
    release_sessions,
    remove_symbols,
    reset_user,
    run_in_thread,
    seed_symbols,
    set_charges,
)

D = Decimal
USER = "charges_api_user"
KEY = "a-valid-openalgo-key"
#: Instruments these tests add and remove. None is named after a real
#: underlying, so a row left behind by a killed run cannot change what
#: another test reads.
OPTION = "CHGTEST27DEC3525000CE"
INDEX = "CHGTESTIDX"
PERPETUAL = "CHGTESTUSDFUT"

EXTRA_SYMBOLS = [
    {
        "symbol": OPTION,
        "brsymbol": OPTION,
        "name": "CHGTEST",
        "exchange": "NFO",
        "brexchange": "NFO",
        "token": "990001",
        "expiry": "27-DEC-35",
        "strike": 25000.0,
        "lotsize": 75,
        "instrumenttype": "CE",
        "tick_size": 0.05,
        "contract_value": 1.0,
    },
    {
        "symbol": INDEX,
        "brsymbol": INDEX,
        "name": "CHGTEST",
        "exchange": "NSE_INDEX",
        "brexchange": "NSE_INDEX",
        "token": "990002",
        "lotsize": 1,
        "instrumenttype": "INDEX",
        "tick_size": 0.05,
        "contract_value": 1.0,
    },
    {
        "symbol": PERPETUAL,
        "brsymbol": PERPETUAL,
        "name": "CHGTEST",
        "exchange": "CRYPTO",
        "brexchange": "CRYPTO",
        "token": "990003",
        "lotsize": 1,
        "instrumenttype": "PERPFUT",
        "tick_size": 0.5,
        "contract_value": 0.001,
    },
]


class _Recorder:
    """Stands in for the request-log executor and keeps what it was handed."""

    def __init__(self):
        self.calls = []

    def submit(self, function, *args):
        self.calls.append(args)


@pytest.fixture(autouse=True)
def _limiter_left_as_found():
    """Put the shared limiter's on/off flag back after each test."""
    from limiter import limiter

    enabled = limiter.enabled
    yield
    limiter.enabled = enabled


@pytest.fixture(autouse=True)
def plan(monkeypatch):
    """The default brokerage plan, a known API key, and a recorded request log."""
    import services.charges_service as service
    from database.sandbox_db import db_session, set_configs
    from sandbox.charges import config_keys, default_config_values
    from sandbox.execution_engine import ExecutionEngine

    prepare_databases()
    seed_symbols(EXTRA_SYMBOLS)
    reset_user(USER)
    release_sessions()
    log = _Recorder()
    monkeypatch.setattr(service, "executor", log)
    monkeypatch.setattr(service, "verify_api_key", lambda key: USER if key == KEY else None)
    monkeypatch.setattr(ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(2600))
    try:
        with configs_restored(list(config_keys())):
            assert set_configs(default_config_values())
            db_session.remove()
            yield log
    finally:
        release_sessions()
        remove_symbols(EXTRA_SYMBOLS)


def order(**changes):
    request = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "product": "CNC",
        "quantity": 50,
        "price": 2500,
    }
    request.update(changes)
    return request


def charges(**changes):
    from services.charges_service import calculate_charges

    success, response, status = calculate_charges(order(**changes), api_key=KEY)
    release_sessions()
    assert success and status == 200, response
    return response["data"]


def every_line(result) -> Decimal:
    block = result["charges"]
    lines = [block["brokerage"], *block["taxes"].values(), *block["other_charges"].values()]
    return sum(D(str(line)) for line in lines)


# ---------------------------------------------------------------------------
# The response
# ---------------------------------------------------------------------------


def test_the_response_is_laid_out_as_total_brokerage_taxes_and_other_charges():
    result = charges()

    assert set(result) == {
        "symbol",
        "exchange",
        "product",
        "action",
        "quantity",
        "price",
        "segment",
        "trade_value",
        "charges",
    }
    assert set(result["charges"]) == {"total", "brokerage", "taxes", "other_charges"}
    assert set(result["charges"]["taxes"]) == {"gst", "stt", "stamp_duty"}
    assert set(result["charges"]["other_charges"]) == {
        "transaction",
        "clearing",
        "ipft",
        "sebi_turnover",
    }


def test_a_delivery_buy_line_by_line():
    """50 RELIANCE at 2500, a trade value of 1,25,000, under the default plan."""
    result = charges()

    assert result["segment"] == "Equity Delivery"
    assert result["trade_value"] == 125000.0
    assert result["quantity"] == 50 and result["price"] == 2500.0
    assert result["charges"] == {
        "total": 172.28,
        "brokerage": 20.0,  # 20, the lower of 20 and 2.5%
        "taxes": {
            "gst": 4.31,  # 18% of brokerage, exchange charges and SEBI fees
            "stt": 125.0,  # 0.1%
            "stamp_duty": 19.0,  # 0.015% on the buy is 18.75, to the nearest rupee
        },
        "other_charges": {
            "transaction": 3.71,  # 0.00297%
            "clearing": 0.0,
            "ipft": 0.13,  # 0.0001%
            "sebi_turnover": 0.13,  # 10 per crore
        },
    }


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"action": "SELL", "price": 2600},
        {"product": "MIS"},
        {"product": "MIS", "action": "SELL", "quantity": 7, "price": 1234.55},
        {"exchange": "BSE"},
        {"symbol": OPTION, "exchange": "NFO", "product": "NRML", "quantity": 75, "price": 100},
        {
            "symbol": OPTION,
            "exchange": "NFO",
            "product": "NRML",
            "action": "SELL",
            "quantity": 150,
            "price": 110.35,
        },
    ],
)
def test_the_total_is_the_sum_of_every_line(changes):
    result = charges(**changes)

    assert D(str(result["charges"]["total"])) == every_line(result)


def test_the_exchange_levy_is_listed_apart_and_not_charged_twice():
    """transaction and ipft together are the one exchange charge a fill pays."""
    from sandbox.charges import SEGMENTS_BY_KEY, compute_charges

    row = SEGMENTS_BY_KEY["fno_options"]
    paid = compute_charges(
        "fno_options", "NFO", "SELL", D("1000000"), row.default_flat, row.default_percent
    )

    other = charges(
        symbol=OPTION, exchange="NFO", product="NRML", action="SELL", quantity=10000, price=100
    )["charges"]["other_charges"]

    assert other["transaction"] == 350.3  # 0.03503%
    assert other["ipft"] == 5.0  # 0.0005%
    assert D(str(other["transaction"])) + D(str(other["ipft"])) == paid.exchange_charges


def test_an_exchange_with_no_levy_reports_none():
    other = charges(exchange="BSE")["charges"]["other_charges"]

    assert other["ipft"] == 0.0
    assert other["transaction"] == 4.69  # 0.00375% of 1,25,000


def test_an_option_sell_pays_stt_on_its_premium_and_no_stamp_duty():
    block = charges(
        symbol=OPTION, exchange="NFO", product="NRML", action="SELL", quantity=75, price=110
    )

    assert block["segment"] == "F&O Options"
    assert block["trade_value"] == 8250.0
    assert block["charges"]["brokerage"] == 20.0
    # 0.15% of the premium is 12.375, and STT goes to the nearest rupee.
    assert block["charges"]["taxes"]["stt"] == 12.0
    assert block["charges"]["taxes"]["stamp_duty"] == 0.0


def test_intraday_and_delivery_are_told_apart_by_the_product():
    delivery = charges(product="CNC")
    intraday = charges(product="MIS")

    assert delivery["segment"] == "Equity Delivery"
    assert intraday["segment"] == "Equity Intraday"
    assert delivery["charges"]["taxes"]["stt"] == 125.0
    assert intraday["charges"]["taxes"]["stt"] == 0.0  # intraday STT is on the sell
    assert intraday["charges"]["taxes"]["stamp_duty"] == 4.0  # 3.75, to the nearest rupee


# ---------------------------------------------------------------------------
# It agrees with the sandbox
# ---------------------------------------------------------------------------


def _fill(action, quantity, price):
    from database.sandbox_db import SandboxTrades, db_session
    from sandbox.order_manager import OrderManager

    request = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": action,
        "quantity": quantity,
        "price": float(price),
        "price_type": "LIMIT",
        "product": "CNC",
    }
    ok, response, _ = run_in_thread(
        lambda: OrderManager(USER).place_order(request, prefetched_quote=quote(price))
    )
    assert ok, response
    db_session.remove()
    trade = SandboxTrades.query.filter_by(orderid=response["orderid"]).first()
    paid = trade.total_charges
    db_session.remove()
    return paid


def test_the_api_quotes_what_a_sandbox_fill_of_the_same_order_pays():
    set_charges(True)
    quoted = charges(quantity=50, price=2500)

    paid = _fill("BUY", 50, D("2500"))

    assert D(str(quoted["charges"]["total"])) == paid == D("172.28")


def test_the_estimate_does_not_depend_on_the_sandbox_switch():
    """With charges off a sandbox fill is free. The trade still costs this live."""
    set_charges(False)

    assert charges()["charges"]["total"] == 172.28
    assert _fill("BUY", 50, D("2500")) == 0


def test_a_saved_plan_changes_the_brokerage_quoted():
    from sandbox.charge_manager import save_charge_settings

    ok, message = save_charge_settings(
        {"segments": {"equity_delivery": {"flat": "0", "percent": "0.5"}}}
    )
    release_sessions()
    assert ok, message

    block = charges()["charges"]

    assert block["brokerage"] == 625.0  # 0.5% of 1,25,000
    assert block["taxes"]["stt"] == 125.0  # statutory lines do not move


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------


def test_crypto_is_charged_nothing_until_a_fee_is_entered():
    result = charges(symbol=PERPETUAL, exchange="CRYPTO", product="NRML", quantity=10, price=62000)

    assert result["segment"] == "Crypto Futures and Spot"
    assert result["trade_value"] == 620.0  # ten contracts of 0.001 at 62,000
    assert result["charges"] == {
        "total": 0.0,
        "brokerage": 0.0,
        "taxes": {"gst": 0.0, "stt": 0.0, "stamp_duty": 0.0},
        "other_charges": {"transaction": 0.0, "clearing": 0.0, "ipft": 0.0, "sebi_turnover": 0.0},
    }


def test_a_crypto_fee_is_charged_as_entered_with_nothing_added():
    from sandbox.charge_manager import save_charge_settings

    ok, message = save_charge_settings(
        {"segments": {"crypto_futures": {"flat": "0", "percent": "0.05"}}}
    )
    release_sessions()
    assert ok, message

    block = charges(
        symbol=PERPETUAL, exchange="CRYPTO", product="NRML", quantity=1000, price=62000
    )["charges"]

    assert block["brokerage"] == 31.0  # 0.05% of 62,000
    assert block["total"] == 31.0
    assert block["taxes"] == {"gst": 0.0, "stt": 0.0, "stamp_duty": 0.0}


def test_the_contract_multiplier_survives_a_lookup_that_misses_the_symbol_cache():
    """The database fallback of the symbol lookup used to drop it, so a crypto
    contract read before the cache loaded was valued at 1000 times its worth."""
    from database.token_db_enhanced import get_symbol_info_dbquery

    info = get_symbol_info_dbquery(PERPETUAL, "CRYPTO")
    release_sessions()

    assert info.contract_value == 0.001


def test_a_fractional_crypto_quantity_is_priced_as_given():
    result = charges(symbol=PERPETUAL, exchange="CRYPTO", product="NRML", quantity=2.5, price=60000)

    assert result["quantity"] == 2.5
    assert result["trade_value"] == 150.0


# ---------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes,fragment",
    [
        ({"symbol": ""}, "Missing mandatory field: symbol"),
        ({"price": None}, "Missing mandatory field: price"),
        ({"exchange": "LSE"}, "Invalid exchange"),
        ({"product": "BO"}, "Invalid product type"),
        ({"action": "HOLD"}, "Invalid action"),
        ({"quantity": 0}, "Quantity must be a positive number"),
        ({"quantity": "many"}, "Quantity must be a positive number"),
        ({"quantity": float("nan")}, "Quantity must be a positive number"),
        ({"price": -1}, "Price must be a positive number"),
        ({"price": float("inf")}, "Price must be a positive number"),
        ({"symbol": "X" * 51}, "between 1 and 50 characters"),
    ],
)
def test_a_request_that_cannot_be_priced_is_refused_with_the_reason(changes, fragment):
    from services.charges_service import calculate_charges

    success, response, status = calculate_charges(order(**changes), api_key=KEY)

    assert not success and status == 400
    assert response["status"] == "error" and fragment in response["message"]


def test_a_symbol_that_is_not_in_the_master_contract_is_refused():
    from services.charges_service import calculate_charges

    success, response, status = calculate_charges(order(symbol="NOSUCHSCRIP"), api_key=KEY)
    release_sessions()

    assert not success and status == 400
    assert response["message"] == "Symbol NOSUCHSCRIP not found on NSE"


def test_an_index_cannot_be_ordered_so_it_has_no_charges():
    from services.charges_service import calculate_charges

    success, response, status = calculate_charges(
        order(symbol=INDEX, exchange="NSE_INDEX", product="MIS", price=25000), api_key=KEY
    )
    release_sessions()

    assert not success and status == 400
    assert response["message"] == (
        "Orders cannot be placed on NSE_INDEX, so no charges apply to it"
    )


def test_an_unknown_api_key_is_refused_and_is_not_logged(plan):
    from services.charges_service import calculate_charges

    success, response, status = calculate_charges(order(), api_key="not-a-key")

    assert not success and status == 403
    assert response == {"status": "error", "message": "Invalid openalgo apikey"}
    assert plan.calls == []


def test_a_caller_must_say_who_it_is():
    from services.charges_service import calculate_charges

    success, response, status = calculate_charges(order())

    assert not success and status == 400
    assert "api_key" in response["message"]


def test_an_internal_caller_that_is_already_authenticated_needs_no_key():
    from services.charges_service import calculate_charges

    success, response, status = calculate_charges(order(), auth_token="token", broker="any")
    release_sessions()

    assert success and status == 200
    assert response["data"]["charges"]["total"] == 172.28


def test_the_request_log_never_holds_the_api_key(plan):
    from services.charges_service import calculate_charges

    calculate_charges({**order(), "apikey": KEY}, api_key=KEY)
    calculate_charges({**order(quantity=0), "apikey": KEY}, api_key=KEY)
    release_sessions()

    assert len(plan.calls) == 2
    for api_type, request, _response in plan.calls:
        assert api_type == "charges"
        assert "apikey" not in request
        assert KEY not in str(request)


# ---------------------------------------------------------------------------
# The REST endpoint and the playground
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    import restx_api.charges as endpoint
    from limiter import limiter

    monkeypatch.setattr(endpoint, "log_executor", _Recorder())
    app = Flask(__name__)
    app.config["RATELIMIT_ENABLED"] = False
    limiter.init_app(app)
    rest = Api(app, prefix="/api/v1")
    rest.add_namespace(endpoint.api, path="/charges")
    return app.test_client()


def test_post_api_v1_charges_answers_with_the_charges(client):
    response = client.post("/api/v1/charges", json={**order(), "apikey": KEY})
    release_sessions()

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["symbol"] == "RELIANCE"
    assert body["data"]["charges"]["total"] == 172.28
    assert "apikey" not in body["data"]


def test_the_endpoint_is_registered_with_the_rest_of_the_v1_api():
    import restx_api

    paths = {
        (namespace.name, path)
        for namespace in restx_api.api.namespaces
        for path in [restx_api.api.ns_paths.get(namespace)]
    }
    assert ("charges", "/charges") in paths


@pytest.mark.parametrize(
    "body,fragment",
    [
        (order(), "apikey"),
        ({**order(), "apikey": KEY, "price": 0}, "Price must be a positive number"),
        ({**order(), "apikey": KEY, "quantity": 1.5}, "Fractional quantity"),
        ({**order(), "apikey": KEY, "exchange": "LSE"}, "exchange"),
        ({"apikey": KEY, "symbol": "RELIANCE"}, "exchange"),
    ],
)
def test_the_endpoint_refuses_a_malformed_request(client, body, fragment):
    response = client.post("/api/v1/charges", json=body)

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error" and fragment in payload["message"]


def test_the_endpoint_passes_on_a_refused_key(client):
    response = client.post("/api/v1/charges", json={**order(), "apikey": "not-a-key"})

    assert response.status_code == 403
    assert response.get_json()["message"] == "Invalid openalgo apikey"


@pytest.mark.parametrize("broker_type,symbol", [("IN_stock", "RELIANCE"), ("crypto", "BTCUSDFUT")])
def test_the_playground_lists_charges_with_a_request_that_validates(broker_type, symbol):
    import json

    from blueprints.playground import load_bruno_endpoints
    from restx_api.schemas import ChargesSchema

    account = load_bruno_endpoints(broker_type=broker_type)["account"]
    entry = next(e for e in account if e["path"] == "/api/v1/charges")

    assert entry["method"] == "POST"
    body = entry["body"]
    sample = body if isinstance(body, dict) else json.loads(body)
    assert sample["symbol"] == symbol
    # The sample is a request the endpoint accepts once a key is filled in.
    loaded = ChargesSchema().load({**sample, "apikey": KEY})
    assert loaded["symbol"] == symbol and loaded["price"] > 0
