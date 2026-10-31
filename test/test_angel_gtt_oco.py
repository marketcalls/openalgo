"""Angel One GTT: one OpenAlgo OCO is one native Angel OCO rule.

OpenAlgo used to build an OCO from two independent Angel rules, which Angel did
not link: both legs could fire and sell twice. Angel's ``createRule`` accepts
``gttType: "OCO"`` with the target leg in ``triggerprice``/``price`` and the
stop-loss leg in ``stoplosstriggerprice``/``stoplossprice``. The response
shapes below are Angel's own, recorded on 31 Oct 2026 for an NFO option.
"""

import pytest

from broker.angel.api import gtt_api
from broker.angel.mapping import gtt_data

SYMBOL = "NIFTY03NOV2623000PE"
TOKEN = "53923"

OCO_RULE = {
    "stoplossprice": 49.5,
    "stoplosstriggerprice": 52.15,
    "gttType": "OCO",
    "status": "NEW",
    "createddate": "2026-10-31T13:43:23.111+05:30",
    "updateddate": "2026-10-31T13:43:23.111+05:30",
    "expirydate": "2026-11-03T05:30:00.000+05:30",
    "clientid": "X",
    "tradingsymbol": SYMBOL,
    "symboltoken": TOKEN,
    "exchange": "NFO",
    "producttype": "CARRYFORWARD",
    "transactiontype": "SELL",
    "price": 208.6,
    "qty": 65,
    "triggerprice": 208.6,
    "disclosedqty": 0,
    "id": 10045655,
}
SINGLE_RULE = {
    **{k: v for k, v in OCO_RULE.items() if not k.startswith("stoploss")},
    "gttType": "",
    "id": 9940546,
    "price": 0.1,
    "triggerprice": 0.1,
    "transactiontype": "BUY",
    "producttype": "MARGIN",
}


def ok(data):
    return {"status": True, "message": "SUCCESS", "errorcode": "", "data": data}


class Angel:
    """Records every GTT call and answers from a per-endpoint queue."""

    def __init__(self, monkeypatch, **answers):
        self.calls = []
        self.answers = answers
        monkeypatch.setattr(gtt_api, "get_api_response", self)
        monkeypatch.setattr(gtt_api, "get_token", lambda symbol, exchange: TOKEN)
        monkeypatch.setattr(gtt_data, "get_br_symbol", lambda symbol, exchange: symbol)
        monkeypatch.setattr(gtt_data, "get_oa_symbol", lambda brsymbol, exchange: brsymbol)

    def __call__(self, endpoint, auth, method="GET", payload="", max_retries=2):
        import json

        path = endpoint.rsplit("/", 1)[-1]
        self.calls.append((path, json.loads(payload)))
        return self.answers[path]

    def paths(self):
        return [path for path, _ in self.calls]


def oco(**overrides):
    return {
        "symbol": SYMBOL,
        "exchange": "NFO",
        "trigger_type": "OCO",
        "action": "SELL",
        "product": "NRML",
        "pricetype": "LIMIT",
        "quantity": 65,
        "triggerprice_sl": 52.15,
        "stoploss": 49.5,
        "triggerprice_tg": 208.6,
        "target": 208.6,
        **overrides,
    }


def test_an_oco_is_one_native_angel_rule(monkeypatch):
    angel = Angel(monkeypatch, createRule=ok({"id": 10045655}))

    _, body, trigger_id = gtt_api.place_gtt_order(oco(), "auth")

    assert trigger_id == "10045655" and body["status"] is True
    [(path, sent)] = angel.calls
    assert path == "createRule"
    assert sent == {
        "tradingsymbol": SYMBOL,
        "symboltoken": TOKEN,
        "exchange": "NFO",
        "transactiontype": "SELL",
        "producttype": "CARRYFORWARD",
        "gttType": "OCO",
        "price": "208.6",
        "triggerprice": "208.6",
        "stoplossprice": "49.5",
        "stoplosstriggerprice": "52.15",
        "qty": "65",
        "disclosedqty": "0",
        "timeperiod": gtt_data.DEFAULT_TIME_PERIOD_DAYS,
    }


def test_a_refused_oco_leaves_nothing_to_roll_back(monkeypatch):
    refused = {"status": False, "message": "Invalid Price", "errorcode": "AB9008", "data": None}
    angel = Angel(monkeypatch, createRule=refused)

    response, body, trigger_id = gtt_api.place_gtt_order(oco(), "auth")

    assert trigger_id is None and body == {"status": "error", "message": "Invalid Price"}
    assert response.status_code == 400 and angel.paths() == ["createRule"]


@pytest.mark.parametrize(
    "exchange,product,angel_product",
    [
        ("NFO", "NRML", "CARRYFORWARD"),
        ("BFO", "NRML", "CARRYFORWARD"),
        ("MCX", "NRML", "CARRYFORWARD"),
        ("NSE", "NRML", "MARGIN"),
        ("BSE", "NRML", "MARGIN"),
        ("NSE", "CNC", "DELIVERY"),
    ],
)
def test_derivatives_keep_carryforward_and_cash_keeps_its_gtt_products(
    exchange, product, angel_product
):
    assert gtt_data.map_gtt_product_type(product, exchange) == angel_product


def test_a_single_gtt_has_no_oco_fields(monkeypatch):
    angel = Angel(monkeypatch, createRule=ok({"id": 9940546}))
    single = {
        "symbol": "INFY",
        "exchange": "NSE",
        "trigger_type": "SINGLE",
        "action": "BUY",
        "product": "CNC",
        "pricetype": "LIMIT",
        "quantity": 1,
        "trigger_price": 1480,
        "price": 1478.5,
    }

    _, _, trigger_id = gtt_api.place_gtt_order(single, "auth")

    sent = angel.calls[0][1]
    assert trigger_id == "9940546"
    assert sent["triggerprice"] == "1480" and sent["price"] == "1478.5"
    assert sent["producttype"] == "DELIVERY"
    assert not {"gttType", "stoplossprice", "stoplosstriggerprice"} & sent.keys()


def test_modifying_an_oco_sends_both_legs_to_the_same_rule(monkeypatch):
    angel = Angel(monkeypatch, ruleDetails=ok(OCO_RULE), modifyRule=ok({"id": 10045655}))

    body, status = gtt_api.modify_gtt_order(
        oco(trigger_id="10045655", triggerprice_sl=60, stoploss=57), "auth"
    )

    assert (status, body) == (200, {"status": "success", "trigger_id": "10045655"})
    assert angel.paths() == ["ruleDetails", "modifyRule"]
    sent = angel.calls[1][1]
    assert sent["id"] == "10045655" and sent["symboltoken"] == TOKEN and sent["gttType"] == "OCO"
    assert (sent["stoplosstriggerprice"], sent["stoplossprice"]) == ("60", "57")
    assert (sent["triggerprice"], sent["price"]) == ("208.6", "208.6")


@pytest.mark.parametrize("stored,asked", [(OCO_RULE, "SINGLE"), (SINGLE_RULE, "OCO")])
def test_a_rule_is_never_modified_into_the_other_kind(monkeypatch, stored, asked):
    angel = Angel(monkeypatch, ruleDetails=ok(stored))

    body, status = gtt_api.modify_gtt_order(
        oco(trigger_id=str(stored["id"]), trigger_type=asked, trigger_price=60, price=57), "auth"
    )

    assert status == 400 and "cannot convert" in body["message"]
    assert angel.paths() == ["ruleDetails"]


def test_a_legacy_two_rule_oco_is_not_modified(monkeypatch):
    angel = Angel(monkeypatch)

    body, status = gtt_api.modify_gtt_order(oco(trigger_id="1234567-1234568"), "auth")

    assert status == 400 and "legacy two-rule OCO" in body["message"]
    assert angel.calls == []


def test_a_legacy_two_rule_oco_is_still_cancelled_whole(monkeypatch):
    angel = Angel(monkeypatch, ruleDetails=ok(OCO_RULE), cancelRule=ok({"id": 1}))

    body, status = gtt_api.cancel_gtt_order("1234567-1234568", "auth")

    assert status == 200 and body["status"] == "success"
    cancelled = [sent["id"] for path, sent in angel.calls if path == "cancelRule"]
    assert cancelled == ["1234567", "1234568"]


def test_an_oco_is_cancelled_with_one_call(monkeypatch):
    angel = Angel(monkeypatch, ruleDetails=ok(OCO_RULE), cancelRule=ok({"id": 10045655}))

    body, status = gtt_api.cancel_gtt_order("10045655", "auth")

    assert (status, body) == (200, {"status": "success", "trigger_id": "10045655"})
    assert angel.calls[-1] == (
        "cancelRule",
        {"id": "10045655", "symboltoken": TOKEN, "exchange": "NFO"},
    )


def test_the_book_shows_an_oco_as_one_two_leg_trigger():
    [row] = gtt_data.map_gtt_book([OCO_RULE])

    assert row["trigger_id"] == "10045655" and row["trigger_type"] == "two-leg"
    assert row["trigger_prices"] == [52.15, 208.6]
    assert [(leg["action"], leg["price"], leg["product"]) for leg in row["legs"]] == [
        ("SELL", 49.5, "NRML"),
        ("SELL", 208.6, "NRML"),
    ]
    assert row["status"] == "active" and row["expires_at"] == OCO_RULE["expirydate"]


def test_a_buy_ocos_legs_are_listed_by_trigger_too():
    # Angel's own BUY OCO sample: the target leg below, the stop-loss leg above
    buy = {
        **OCO_RULE,
        "transactiontype": "BUY",
        "exchange": "NSE",
        "producttype": "DELIVERY",
        "tradingsymbol": "SBIN-EQ",
        "triggerprice": 753.75,
        "price": 761.30,
        "stoplosstriggerprice": 833.10,
        "stoplossprice": 841.45,
    }

    [row] = gtt_data.map_gtt_book([buy])

    assert row["trigger_prices"] == [753.75, 833.10]
    assert [leg["price"] for leg in row["legs"]] == [761.30, 841.45]


def test_the_book_shows_a_single_rule_as_before():
    [row] = gtt_data.map_gtt_book([SINGLE_RULE])

    assert row["trigger_type"] == "single" and row["trigger_prices"] == [0.1]
    assert [(leg["action"], leg["price"], leg["product"]) for leg in row["legs"]] == [
        ("BUY", 0.1, "NRML")
    ]
