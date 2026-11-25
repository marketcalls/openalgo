"""Pocketful funds, margin calculator and GTT rules.

Every HTTP call is stubbed at ``pocketful_request`` where the module under test
calls it, and the answers are the examples on Pocketful's own documentation
pages (offline copy of 2026-11-17), so a test fails if the plugin stops
reading the documented shape.
"""

from types import SimpleNamespace

import pytest

import broker.pocketful.api.funds as funds
import broker.pocketful.api.gtt_api as gtt_api
import broker.pocketful.api.margin_api as margin_api
import broker.pocketful.mapping.gtt_data as gtt_data
import broker.pocketful.mapping.margin_data as margin_data
from broker.pocketful.api.baseurl import PocketfulResponse, pack_token

TOKEN = pack_token("DEMO1", "jwt.abc.def")


class Broker:
    """Stands in for pocketful_request: records each call, replays answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, method, path, token, params=None, payload=None, timeout=None, headers=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "token": token,
                "params": params,
                "payload": payload,
                "headers": headers,
            }
        )
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def answer(body, status_code=200):
    return PocketfulResponse(status_code, body, "" if body is None else str(body))


# --- Docs examples ---------------------------------------------------------

FUNDS_DOC = {
    "data": {
        "client_id": "DEMO1",
        "headers": ["Description", ""],
        "values": [
            ["Available", "39.99"],
            ["Adhoc Deposit", "0.00"],
            ["Cash Deposit", "39.99"],
            ["Delivery", "0.00"],
            ["DP Collateral Benefit", "0.00"],
            ["DP Credit for Sale", "0.00"],
            ["DP Pledge Collateral", "0.00"],
            ["Manual Collateral", "0.00"],
            ["Pay In", "0.00"],
            ["Net Margin", "0.00"],
            ["Notion Deposit", "0.00"],
            ["Overdraft", "0.00"],
            ["Pay out", "0.00"],
            ["Pool Collateral Benefit", "0.00"],
            ["Pool Pledge Collateral", "0.00"],
            ["Premium", "0.00"],
            ["Sar Collateral Benefit", "0.00"],
            ["Sar Credit for Sale", "0.00"],
            ["Span Margin", "0.00"],
            ["Var Margin", "0.00"],
            ["Extreme Loss Margin", "0.00"],
            ["Option Credit For Sell", "0.00"],
        ],
    },
    "message": "",
    "status": "success",
}
FUNDS_ERROR_DOC = {
    "status": "error",
    "message": "Request Unauthorised",
    "error_code": 40000,
    "data": {},
}

MARGIN_ERROR_DOC = {
    "status": False,
    "message": "Invalid request parameters or unauthorized",
    "errorcode": "40001",
    "data": {},
}


def margin_answer(**combined):
    block = dict.fromkeys(
        (
            "deliveryMargin",
            "span",
            "somtierMargin",
            "additionalMargin",
            "spanSpreadMargin",
            "varMargin",
            "exposureMargin",
            "premiumMargin",
            "premiumBenefit",
            "extremeLossMargin",
            "maxSpan",
            "netSpan",
        ),
        0,
    )
    block.update(combined)
    return {
        "status": True,
        "message": "SUCCESS",
        "errorcode": "",
        "data": {"combinedMargin": block, "individualMarginValues": []},
    }


GTT_ID = "ea036a20-2073-4bfb-a852-34662c4bd770"
GTT_CREATED_DOC = {
    "data": {"id": GTT_ID},
    "message": "GTT created successfully",
    "status": "success",
}
GTT_CREATE_ERROR_DOC = {
    "data": {},
    "error_code": 44000,
    "message": "`order` `product` is invalid",
    "status": "error",
}
HELD_ID = "673a20c8-80d5-4a0c-8a34-23f20fe79661"
GTT_ROW_DOC = {
    "action_type": "single_order",
    "client_id": "DEMO1",
    "created_at": "2021-10-17 18:14:01",
    "expiry_time": "2022-10-17",
    "id": HELD_ID,
    "login_id": "DEMO1",
    "order": {
        "disclosed_qty": 0,
        "exchange": "NSE",
        "execution_type": "",
        "mode": "NEW",
        "order_side": "BUY",
        "order_type": "LIMIT",
        "price": 3611.5,
        "pro_cli": "CLIENT",
        "prod_type": "CNC",
        "quantity": 1,
        "segment": "Capital",
        "sl_order_price": 0,
        "sl_order_quantity": 0,
        "sl_trigger_price": 0,
        "square_off_price": 0,
        "token": 11536,
        "trading_symbol": "TCS-EQ",
        "trailing_stop_loss": 0,
        "trigger_price": 3611.45,
        "validity": "",
        "vendor_code": "00",
        "reject_code": 0,
        "reject_reason": "",
        "status": "Active",
        "type": "GTTStock",
        "updated_at": "2021-10-17 18:18:12",
    },
}
GTT_NO_DATA_DOC = {
    "data": {},
    "error_code": 45000,
    "message": "Error from backend: (500)-no gtt data found",
    "status": "error",
}
GTT_MODIFIED_DOC = {
    "data": {"id": HELD_ID},
    "message": "gtt request modified successfully",
    "status": "success",
}
GTT_CANCELLED_DOC = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {"id": "e06f52ab-6cf4-492d-a014-c6e0e5843a93"},
}
GTT_CANCEL_ERROR_DOC = {
    "data": {},
    "error_code": 45000,
    "message": "Error from backend: (500)-event id not found",
    "status": "error",
}


def book(*rows):
    return {"data": list(rows), "message": "", "status": "success"}


# --- Master contract stand-in ---------------------------------------------


def row(symbol, exchange, token, brsymbol, name="", instrumenttype="EQ", expiry="", tick=0.05):
    return SimpleNamespace(
        symbol=symbol,
        exchange=exchange,
        brexchange=exchange.replace("_INDEX", ""),
        token=token,
        brsymbol=brsymbol,
        name=name,
        instrumenttype=instrumenttype,
        expiry=expiry,
        tick_size=tick,
    )


SYMBOLS = {
    ("ADANIENT", "NSE"): row("ADANIENT", "NSE", "25", "ADANIENT-EQ", "ADANIENT"),
    ("ADANIENT29SEP26FUT", "NFO"): row(
        "ADANIENT29SEP26FUT", "NFO", "68417", "ADANIENT26SEPFUT", "ADANIENT", "FUT", "29-SEP-26"
    ),
    ("ADANIENT27OCT26FUT", "NFO"): row(
        "ADANIENT27OCT26FUT", "NFO", "48711", "ADANIENT26OCTFUT", "ADANIENT", "FUT", "27-OCT-26"
    ),
    ("NIFTY", "NSE_INDEX"): row("NIFTY", "NSE_INDEX", "26000", "Nifty 50", "NIFTY", tick=0),
    ("NIFTY24NOV2624000CE", "NFO"): row(
        "NIFTY24NOV2624000CE", "NFO", "40001", "NIFTY26N2424000CE", "NIFTY", "CE", "24-NOV-26"
    ),
    ("NIFTY24NOV2624000PE", "NFO"): row(
        "NIFTY24NOV2624000PE", "NFO", "40002", "NIFTY26N2424000PE", "NIFTY", "PE", "24-NOV-26"
    ),
    ("CRUDEOIL18DEC26FUT", "MCX"): row(
        "CRUDEOIL18DEC26FUT", "MCX", "445001", "CRUDEOIL26DECFUT", "CRUDEOIL", "FUT", "18-DEC-26"
    ),
    ("IDEA", "NSE"): row("IDEA", "NSE", "14366", "IDEA-EQ", "IDEA", tick=0.01),
    ("TCS", "NSE"): row("TCS", "NSE", "11536", "TCS-EQ", "TCS", tick=0.1),
}


@pytest.fixture
def master(monkeypatch):
    lookup = lambda symbol, exchange: SYMBOLS.get((symbol, exchange))  # noqa: E731
    monkeypatch.setattr(margin_data, "get_symbol_info", lookup)
    monkeypatch.setattr(gtt_data, "get_symbol_info", lookup)
    by_brsymbol = {(r.brsymbol, r.brexchange): r.symbol for r in SYMBOLS.values()}
    monkeypatch.setattr(
        gtt_data, "get_oa_symbol", lambda brsymbol, exchange: by_brsymbol.get((brsymbol, exchange))
    )
    monkeypatch.setattr(gtt_data, "get_symbol", lambda token, exchange: None)
    monkeypatch.setattr(gtt_api, "today_ist", lambda: gtt_data.datetime(2026, 11, 17).date())


# --- Funds -----------------------------------------------------------------


@pytest.fixture
def positions(monkeypatch):
    """The position book pipeline funds reads M2M from, stubbed per test."""
    import broker.pocketful.api.order_api as order_api
    import broker.pocketful.mapping.order_data as order_data

    state = {"book": {"status": "success", "data": []}}
    monkeypatch.setattr(order_api, "get_positions", lambda auth: state["book"])
    # Rows as the netwise book carries them; symbol mapping is not under test.
    monkeypatch.setattr(order_data, "map_position_data", lambda data: data["data"])
    return state


def netwise(symbol, bought=0, buy_amount=0, sold=0, sell_amount=0, ltp=0, multiplier=1):
    """One netwise position row (fetch-position-netwise.md), amounts in one unit."""
    return {
        "trading_symbol": symbol,
        "buy_quantity": bought,
        "buy_amount": buy_amount,
        "sell_quantity": sold,
        "sell_amount": sell_amount,
        "net_quantity": bought - sold,
        "net_amount": sell_amount - buy_amount,
        "ltp": ltp,
        "multiplier": multiplier,
    }


def test_funds_read_the_documented_answer(monkeypatch, positions):
    broker = Broker(answer(FUNDS_DOC))
    monkeypatch.setattr(funds, "pocketful_request", broker)

    assert funds.get_margin_data(TOKEN) == {
        "availablecash": "39.99",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }
    [call] = broker.calls
    assert call["method"] == "GET"
    assert call["path"] == "/api/v2/funds/view"
    assert call["params"] == {"client_id": "DEMO1", "type": "all"}


def test_funds_take_pledges_as_collateral_and_net_margin_as_used(monkeypatch, positions):
    body = {"data": dict(FUNDS_DOC["data"]), "message": "", "status": "success"}
    amounts = {
        "Available": "1,250.50",
        "DP Pledge Collateral": "100",
        "Pool Pledge Collateral": "50.25",
        "DP Collateral Benefit": "70",
        "Net Margin": "25.5",
    }
    body["data"]["values"] = [
        [label, amounts.get(label, value)] for label, value in FUNDS_DOC["data"]["values"]
    ]
    monkeypatch.setattr(funds, "pocketful_request", Broker(answer(body)))

    result = funds.get_margin_data(TOKEN)

    assert result["availablecash"] == "1250.50"
    # The benefit row is the same pledge seen another way: not added again.
    assert result["collateral"] == "150.25"
    assert result["utiliseddebits"] == "25.50"


def test_funds_m2m_comes_from_the_position_book(monkeypatch, positions):
    positions["book"] = {
        "status": "success",
        "data": [
            # The docs' example: bought and sold one, closed for 18.
            netwise("IDEA", bought=1, buy_amount=40520, sold=1, sell_amount=40538, ltp=40520),
            # Bought 100 at 100, sold 50 at 110, 50 still held at an LTP of 100:
            # 500 booked on the 50 sold, nothing open.
            netwise("TCS", bought=100, buy_amount=10000, sold=50, sell_amount=5500, ltp=100),
            # Sold 75 at 10, still short at an LTP of 6: 300 open, nothing booked.
            netwise("NIFTY24NOV2624000CE", sold=75, sell_amount=750, ltp=6),
        ],
    }
    monkeypatch.setattr(funds, "pocketful_request", Broker(answer(FUNDS_DOC)))

    result = funds.get_margin_data(TOKEN)

    assert result["m2mrealized"] == "518.00"
    assert result["m2munrealized"] == "300.00"


def test_a_short_closed_in_part_books_its_matched_quantity():
    from broker.pocketful.mapping.order_data import _position_pnl, position_pnl_split

    # Sold 100 at 100, bought 50 back at 90, short 50 at an LTP of 100.
    row = netwise("SBIN", bought=50, buy_amount=4500, sold=100, sell_amount=10000, ltp=100)

    realised, unrealised = position_pnl_split(row)

    assert (realised, unrealised) == (500.0, 0.0)
    assert realised + unrealised == _position_pnl(row)


def test_funds_stand_when_the_position_book_cannot_be_read(monkeypatch, positions):
    positions["book"] = {"status": "error", "message": "unreachable"}
    monkeypatch.setattr(funds, "pocketful_request", Broker(answer(FUNDS_DOC)))

    result = funds.get_margin_data(TOKEN)

    assert result["availablecash"] == "39.99"
    assert result["m2mrealized"] == "0.00"


@pytest.mark.parametrize(
    "reply",
    [
        answer(FUNDS_ERROR_DOC),
        answer(FUNDS_ERROR_DOC, 401),
        # A refusal is never read as funds, even when it carries a table.
        answer(dict(FUNDS_ERROR_DOC, data=FUNDS_DOC["data"])),
        answer(FUNDS_DOC, 500),
        answer(None, 502),
        answer({"status": "success", "data": {"values": "n/a"}}),
        ConnectionError("unreachable"),
    ],
)
def test_funds_failures_read_as_no_session(monkeypatch, positions, reply):
    monkeypatch.setattr(funds, "pocketful_request", Broker(reply))

    assert funds.get_margin_data(TOKEN) == {}


def test_funds_without_a_client_id_send_nothing(monkeypatch, positions):
    broker = Broker()
    monkeypatch.setattr(funds, "pocketful_request", broker)
    monkeypatch.setattr(funds, "client_id", lambda token: None)

    assert funds.get_margin_data("bare") == {}
    assert broker.calls == []


# --- Margin calculator -----------------------------------------------------

CALENDAR = [
    {
        "symbol": "ADANIENT29SEP26FUT",
        "exchange": "NFO",
        "action": "BUY",
        "quantity": "309",
        "product": "NRML",
        "pricetype": "LIMIT",
        "price": "2939.7",
    },
    {
        "symbol": "ADANIENT27OCT26FUT",
        "exchange": "NFO",
        "action": "SELL",
        "quantity": "309",
        "product": "NRML",
        "pricetype": "LIMIT",
        "price": "2954",
    },
]


def test_a_basket_goes_in_one_request_shaped_as_the_docs(monkeypatch, master):
    broker = Broker(answer(margin_answer(span=100000, exposureMargin=20000, spanSpreadMargin=5000)))
    monkeypatch.setattr(margin_api, "pocketful_request", broker)

    response, data = margin_api.calculate_margin_api(CALENDAR, TOKEN)

    assert response.status_code == 200
    assert data == {
        "status": "success",
        "data": {
            "total_margin_required": 125000.0,
            "span_margin": 100000.0,
            "exposure_margin": 20000.0,
        },
    }
    [call] = broker.calls
    assert call["method"] == "POST"
    assert call["path"] == "/api/space/v1/orderapis/marginCalculations"
    # margin-calculator.md lists a clientid header beside the session's own.
    assert call["headers"] == {"clientid": "DEMO1"}
    # The docs' own request, with the product sent by name (see margin_data).
    assert call["payload"] == {
        "data": [
            {
                "exchange": "NFO",
                "mode": "NEW",
                "price": "2939.7",
                "product": "NRML",
                "quantity": "309",
                "segment": "FutOpt",
                "series": "FUTSTK",
                "side": "BUY",
                "symbol": "ADANIENT26SEPFUT",
                "token": "68417",
                "underlying": "25",
            },
            {
                "exchange": "NFO",
                "mode": "NEW",
                "price": "2954",
                "product": "NRML",
                "quantity": "309",
                "segment": "FutOpt",
                "series": "FUTSTK",
                "side": "SELL",
                "symbol": "ADANIENT26OCTFUT",
                "token": "48711",
                "underlying": "25",
            },
        ]
    }


def test_index_options_and_cash_legs_take_their_series_and_underlying(monkeypatch, master):
    broker = Broker(answer(margin_answer(premiumMargin=3000, premiumBenefit=1000, varMargin=50)))
    monkeypatch.setattr(margin_api, "pocketful_request", broker)
    legs = [
        {
            "symbol": "NIFTY24NOV2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "quantity": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "price": 0,
        },
        {
            "symbol": "ADANIENT",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "product": "CNC",
            "pricetype": "LIMIT",
            "price": 2500,
        },
    ]

    response, data = margin_api.calculate_margin_api(legs, TOKEN)

    assert response.status_code == 200
    assert data["data"]["total_margin_required"] == 2050.0
    option, cash = broker.calls[0]["payload"]["data"]
    assert (option["series"], option["underlying"], option["price"]) == ("OPTIDX", "26000", "0")
    assert (cash["segment"], cash["series"], cash["underlying"]) == ("Capital", "EQ", "25")


def test_one_position_uses_the_same_calculator(monkeypatch, master):
    broker = Broker(answer(margin_answer(span=1, exposureMargin=1)))
    monkeypatch.setattr(margin_api, "pocketful_request", broker)

    response, _ = margin_api.calculate_margin_api(CALENDAR[:1], TOKEN)

    assert response.status_code == 200
    assert len(broker.calls[0]["payload"]["data"]) == 1


def test_an_empty_combined_block_falls_back_to_the_legs(monkeypatch, master):
    body = margin_answer()
    body["data"]["individualMarginValues"] = [
        {"span": 400, "exposureMargin": 100},
        {"span": 300, "exposureMargin": 50},
    ]
    monkeypatch.setattr(margin_api, "pocketful_request", Broker(answer(body)))

    _, data = margin_api.calculate_margin_api(CALENDAR, TOKEN)

    assert data["data"] == {
        "total_margin_required": 850.0,
        "span_margin": 700.0,
        "exposure_margin": 150.0,
    }


def test_a_refusal_sent_with_http_200_is_not_a_success(monkeypatch, master):
    monkeypatch.setattr(margin_api, "pocketful_request", Broker(answer(MARGIN_ERROR_DOC)))

    response, data = margin_api.calculate_margin_api(CALENDAR, TOKEN)

    assert response.status_code == 400
    assert data["status"] == "error"
    assert "Invalid request parameters or unauthorized" in data["message"]


@pytest.mark.parametrize(
    "reply",
    [answer(None, 200), answer({"status": True, "data": {}}), ConnectionError("down")],
)
def test_an_unreadable_or_missing_answer_is_a_502(monkeypatch, master, reply):
    monkeypatch.setattr(margin_api, "pocketful_request", Broker(reply))

    response, data = margin_api.calculate_margin_api(CALENDAR, TOKEN)

    assert response.status_code == 502
    assert data["status"] == "error"


@pytest.mark.parametrize(
    ("position", "words"),
    [
        ({"symbol": "NOSUCH", "exchange": "NSE"}, "not in the Pocketful master contract"),
        ({"symbol": "CRUDEOIL18DEC26FUT", "exchange": "MCX"}, "MCX"),
        ({"symbol": "NIFTY", "exchange": "NSE_INDEX"}, "NSE_INDEX"),
    ],
)
def test_a_leg_that_cannot_be_priced_refuses_the_basket_unsent(
    monkeypatch, master, position, words
):
    broker = Broker()
    monkeypatch.setattr(margin_api, "pocketful_request", broker)
    leg = {"action": "BUY", "quantity": 1, "product": "NRML", "pricetype": "MARKET", **position}

    response, data = margin_api.calculate_margin_api([CALENDAR[0], leg], TOKEN)

    assert response.status_code == 400
    assert words in data["message"]
    assert broker.calls == []


def test_the_margin_service_reports_an_http_200_refusal_as_a_failure(monkeypatch, master):
    import services.margin_service as service

    monkeypatch.setattr(margin_api, "pocketful_request", Broker(answer(MARGIN_ERROR_DOC)))
    monkeypatch.setattr(service, "executor", SimpleNamespace(submit=lambda *a, **k: None))

    ok, body, status = service.calculate_margin_with_auth(CALENDAR, TOKEN, "pocketful", {})

    assert (ok, status) == (False, 400)
    assert "Invalid request parameters" in body["message"]


# --- GTT -------------------------------------------------------------------

SINGLE = {
    "strategy": "test",
    "trigger_type": "SINGLE",
    "exchange": "NSE",
    "symbol": "IDEA",
    "action": "BUY",
    "product": "CNC",
    "quantity": 1,
    "pricetype": "LIMIT",
    "price": 11.3,
    "triggerprice_sl": None,
    "triggerprice_tg": 13.6,
    "trigger_price": 13.6,
}


def test_a_single_gtt_is_created_as_the_docs_show(monkeypatch, master):
    broker = Broker(answer(GTT_CREATED_DOC))
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)
    monkeypatch.setattr(gtt_data, "next_user_order_id", lambda: 122321)

    response, data, trigger_id = gtt_api.place_gtt_order(dict(SINGLE), TOKEN)

    assert (response.status, trigger_id) == (200, GTT_ID)
    assert data == {"status": "success", "trigger_id": GTT_ID}
    [call] = broker.calls
    assert (call["method"], call["path"]) == ("POST", "/api/v1/event/gtt")
    assert call["payload"] == {
        "action_type": "single_order",
        "expiry_time": "2027-11-17",
        "order": {
            "client_id": "DEMO1",
            "disclosed_quantity": 0,
            "exchange": "NSE",
            "instrument_token": "14366",
            "market_protection_percentage": 0,
            "order_side": "BUY",
            "order_type": "LIMIT",
            "price": 11.3,
            "product": "CNC",
            "quantity": 1,
            "sl_order_price": 0,
            "sl_order_quantity": 0,
            "sl_trigger_price": 0,
            "trigger_price": 13.6,
            "user_order_id": 122321,
        },
    }


@pytest.mark.parametrize(
    ("action", "trigger", "expected"),
    [("BUY", 13.6, 13.87), ("SELL", 1480.0, 1472.6)],
)
def test_a_market_gtt_is_a_limit_protected_from_its_trigger(
    monkeypatch, master, action, trigger, expected
):
    broker = Broker(answer(GTT_CREATED_DOC))
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)
    symbol = "IDEA" if trigger < 100 else "TCS"
    order = dict(SINGLE, symbol=symbol, action=action, pricetype="MARKET", price=0)
    order["trigger_price"] = order["triggerprice_tg"] = trigger

    gtt_api.place_gtt_order(order, TOKEN)

    sent = broker.calls[0]["payload"]["order"]
    assert sent["order_type"] == "LIMIT"
    assert sent["trigger_price"] == trigger
    # Measured from the trigger, where the child order is placed: a BUY above
    # it, a SELL below it (IDEA 2% on a 0.01 tick, TCS 0.5% on a 0.10 tick).
    assert sent["price"] == expected


def test_a_derivative_gtt_expires_with_its_contract_unless_told(monkeypatch, master):
    broker = Broker(answer(GTT_CREATED_DOC), answer(GTT_CREATED_DOC))
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)
    order = dict(SINGLE, symbol="NIFTY24NOV2624000CE", exchange="NFO", product="NRML", quantity=75)

    gtt_api.place_gtt_order(dict(order), TOKEN)
    gtt_api.place_gtt_order(dict(order, expires_at="2026-11-20T15:30:00+05:30"), TOKEN)

    assert [c["payload"]["expiry_time"] for c in broker.calls] == ["2026-11-24", "2026-11-20"]


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"trigger_type": "OCO", "stoploss": 9, "target": 14}, "OCO"),
        ({"pricetype": "LIMIT", "price": 0}, "limit price"),
        ({"exchange": "NSE_INDEX", "symbol": "NIFTY"}, "index"),
        ({"symbol": "NOSUCH"}, "master contract"),
        ({"expires_at": "2026-11-16"}, "expiry"),
        ({"trigger_price": 0, "triggerprice_tg": 0}, "trigger price"),
    ],
)
def test_a_gtt_pocketful_cannot_take_is_refused_unsent(monkeypatch, master, change, words):
    broker = Broker()
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)

    response, data, trigger_id = gtt_api.place_gtt_order(dict(SINGLE, **change), TOKEN)

    assert response.status == 400 and trigger_id is None
    assert words in data["message"]
    assert broker.calls == []


def test_a_refused_gtt_reads_as_pocketfuls_reason(monkeypatch, master):
    monkeypatch.setattr(gtt_api, "pocketful_request", Broker(answer(GTT_CREATE_ERROR_DOC)))

    response, data, trigger_id = gtt_api.place_gtt_order(dict(SINGLE), TOKEN)

    assert (response.status, trigger_id) == (400, None)
    assert data["message"] == "Pocketful refused to place the GTT: `order` `product` is invalid"


@pytest.mark.parametrize(
    "reply",
    [
        ConnectionError("timed out"),
        answer(None, 504),
        answer({"data": {}, "message": "GTT created successfully", "status": "success"}),
    ],
)
def test_an_unconfirmed_create_is_not_retried_and_says_to_check(monkeypatch, master, reply):
    broker = Broker(reply)
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)

    response, data, trigger_id = gtt_api.place_gtt_order(dict(SINGLE), TOKEN)

    assert trigger_id is None and response.status == 502
    assert "Check the GTT list before placing it again" in data["message"]
    assert len(broker.calls) == 1


MODIFY = dict(
    SINGLE,
    trigger_id=HELD_ID,
    symbol="TCS",
    price=3600,
    triggerprice_tg=3605,
    trigger_price=3605,
)


def test_a_modify_keeps_the_rules_expiry_and_sends_its_id(monkeypatch, master):
    broker = Broker(answer(book(GTT_ROW_DOC)), answer(GTT_MODIFIED_DOC))
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)

    data, status = gtt_api.modify_gtt_order(dict(MODIFY), TOKEN)

    assert (data, status) == ({"status": "success", "trigger_id": HELD_ID}, 200)
    read, write = broker.calls
    assert (read["method"], read["path"]) == ("GET", "/api/v1/event/gtt/DEMO1")
    assert read["params"] == {"client_id": "DEMO1"}
    assert (write["method"], write["path"]) == ("PUT", "/api/v1/event/gtt")
    body = write["payload"]
    assert (body["id"], body["expiry_time"], body["action_type"]) == (
        HELD_ID,
        "2022-10-17",
        "single_order",
    )
    assert (body["order"]["price"], body["order"]["trigger_price"]) == (3600.0, 3605.0)
    assert body["order"]["device"] == "web"


@pytest.mark.parametrize(
    ("held", "change", "words"),
    [
        ([], {}, "no longer active"),
        ([dict(GTT_ROW_DOC, order=dict(GTT_ROW_DOC["order"], status="Triggered"))], {}, "active"),
        ([GTT_ROW_DOC], {"symbol": "IDEA"}, "cannot be changed"),
        ([GTT_ROW_DOC], {"action": "SELL"}, "cannot be changed"),
        # Same token and side on another exchange: tokens are per exchange.
        (
            [dict(GTT_ROW_DOC, order=dict(GTT_ROW_DOC["order"], exchange="BSE"))],
            {},
            "cannot be changed",
        ),
        ([dict(GTT_ROW_DOC, action_type="oco_order")], {}, "not a single trigger"),
    ],
)
def test_a_modify_that_cannot_apply_is_refused_before_writing(
    monkeypatch, master, held, change, words
):
    broker = Broker(answer(book(*held)))
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)

    data, status = gtt_api.modify_gtt_order(dict(MODIFY, **change), TOKEN)

    assert status in (400, 404)
    assert words in data["message"]
    assert [call["method"] for call in broker.calls] == ["GET"]


def test_a_modify_pocketful_refuses_reads_without_its_backend_code(monkeypatch, master):
    refused = {
        "data": {},
        "error_code": 45000,
        "message": "Error from backend: (1600)-cannot modify, no data found with this id",
        "status": "error",
    }
    monkeypatch.setattr(
        gtt_api, "pocketful_request", Broker(answer(book(GTT_ROW_DOC)), answer(refused, 500))
    )

    data, status = gtt_api.modify_gtt_order(dict(MODIFY), TOKEN)

    assert status == 500
    assert data["message"] == (
        "Pocketful refused to change the GTT: Cannot modify, no data found with this id"
    )


def test_a_cancel_deletes_by_client_and_rule_id(monkeypatch):
    broker = Broker(answer(GTT_CANCELLED_DOC))
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)

    data, status = gtt_api.cancel_gtt_order("e06f52ab-6cf4-492d-a014-c6e0e5843a93", TOKEN)

    assert (data["status"], status) == ("success", 200)
    [call] = broker.calls
    assert call["method"] == "DELETE"
    assert call["path"] == "/api/v1/event/gtt/DEMO1/e06f52ab-6cf4-492d-a014-c6e0e5843a93"


def test_a_cancel_of_an_unknown_rule_reads_plainly(monkeypatch):
    monkeypatch.setattr(gtt_api, "pocketful_request", Broker(answer(GTT_CANCEL_ERROR_DOC, 500)))

    data, status = gtt_api.cancel_gtt_order(GTT_ID, TOKEN)

    assert status == 500
    assert data["message"] == "Pocketful refused to cancel the GTT: Event id not found"


@pytest.mark.parametrize("bad", ["", "../orders", "a/b", "id?x=1", "x" * 65])
def test_an_id_pocketful_did_not_issue_never_reaches_a_path(monkeypatch, bad):
    broker = Broker()
    monkeypatch.setattr(gtt_api, "pocketful_request", broker)

    assert gtt_api.cancel_gtt_order(bad, TOKEN)[1] == 400
    assert gtt_api.modify_gtt_order(dict(MODIFY, trigger_id=bad), TOKEN)[1] == 400
    assert broker.calls == []


def test_the_book_maps_the_documented_rule(monkeypatch, master):
    monkeypatch.setattr(gtt_api, "pocketful_request", Broker(answer(book(GTT_ROW_DOC))))

    data, status = gtt_api.get_gtt_book(TOKEN)

    assert status == 200
    assert data == {
        "status": "success",
        "data": [
            {
                "trigger_id": HELD_ID,
                "trigger_type": "single",
                "status": "active",
                "symbol": "TCS",
                "exchange": "NSE",
                "trigger_prices": [3611.45],
                "last_price": 0,
                "legs": [
                    {
                        "action": "BUY",
                        "quantity": 1,
                        "price": 3611.5,
                        "pricetype": "LIMIT",
                        "product": "CNC",
                    }
                ],
                "created_at": "2021-10-17 18:14:01",
                "updated_at": "2021-10-17 18:18:12",
                "expires_at": "2022-10-17",
            }
        ],
    }


def test_the_book_hides_finished_rules_unless_asked(monkeypatch, master):
    fired = dict(GTT_ROW_DOC, order=dict(GTT_ROW_DOC["order"], status="Triggered"))
    monkeypatch.setattr(
        gtt_api, "pocketful_request", Broker(answer(book(fired)), answer(book(fired)))
    )

    assert gtt_api.get_gtt_book(TOKEN)[0]["data"] == []
    history, _ = gtt_api.get_gtt_book(TOKEN, include_history=True)
    assert history["data"][0]["status"] == "triggered"


def test_no_rules_is_an_empty_book_not_an_error(monkeypatch, master):
    monkeypatch.setattr(gtt_api, "pocketful_request", Broker(answer(GTT_NO_DATA_DOC, 500)))

    assert gtt_api.get_gtt_book(TOKEN) == ({"status": "success", "data": []}, 200)


def test_a_book_pocketful_refuses_is_an_error(monkeypatch, master):
    monkeypatch.setattr(gtt_api, "pocketful_request", Broker(answer(FUNDS_ERROR_DOC, 401)))

    data, status = gtt_api.get_gtt_book(TOKEN)

    assert status == 401
    assert data["message"] == "Pocketful refused to list the GTT: Request Unauthorised"


def test_the_gtt_services_read_the_plugins_answers(monkeypatch, master):
    import services.cancel_gtt_order_service as cancel_service
    import services.gtt_orderbook_service as book_service
    import services.place_gtt_order_service as place_service

    for service in (place_service, cancel_service):
        monkeypatch.setattr(service.bus, "publish", lambda event: None)
    for service in (place_service, cancel_service, book_service):
        monkeypatch.setattr(service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(
        gtt_api,
        "pocketful_request",
        Broker(
            answer(GTT_CREATED_DOC),
            answer(GTT_CREATE_ERROR_DOC),
            answer(GTT_CANCELLED_DOC),
            answer(book(GTT_ROW_DOC)),
        ),
    )

    placed = place_service.place_gtt_order_with_auth(dict(SINGLE), TOKEN, "pocketful", {})
    refused = place_service.place_gtt_order_with_auth(dict(SINGLE), TOKEN, "pocketful", {})
    cancelled = cancel_service.cancel_gtt_order_with_auth(GTT_ID, TOKEN, "pocketful", {})
    listed = book_service.get_gtt_orderbook_with_auth(TOKEN, "pocketful", None)

    assert placed == (True, {"status": "success", "trigger_id": GTT_ID}, 200)
    assert refused[0] is False and refused[2] == 400
    assert cancelled[0] is True and cancelled[2] == 200
    assert listed[0] is True and listed[1]["data"][0]["trigger_id"] == HELD_ID
