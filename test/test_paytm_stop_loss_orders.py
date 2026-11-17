"""Paytm SL and SL-M orders keep their type and trigger price (issue #2389).

Before this fix OpenAlgo's SL and SL-M were missing from the order type map,
so both were sent to Paytm as MKT with the trigger price dropped.
"""

import json
from unittest.mock import patch

import pytest

from broker.paytm.api import order_api
from broker.paytm.mapping import transform_data as td

BASE = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "SELL",
    "quantity": "10",
    "product": "MIS",
    "price": "0",
}


@pytest.fixture(autouse=True)
def token():
    with patch.object(td, "get_token", return_value="3045"):
        yield


def order(**overrides):
    return {**BASE, **overrides}


class TestTransformData:
    @pytest.mark.parametrize(
        "pricetype, expected",
        [("MARKET", "MKT"), ("LIMIT", "LMT"), ("SL", "SL"), ("SL-M", "SLM")],
    )
    def test_order_type_mapping(self, pricetype, expected):
        data = order(pricetype=pricetype, price="601", trigger_price="600")
        assert td.transform_data(data)["order_type"] == expected

    def test_sl_sends_limit_price_and_trigger(self):
        out = td.transform_data(order(pricetype="SL", price="599", trigger_price="600"))
        assert out["order_type"] == "SL"
        assert out["price"] == "599"
        assert out["trigger_price"] == "600"

    def test_slm_sends_trigger_and_zero_price(self):
        out = td.transform_data(order(pricetype="SL-M", price="599", trigger_price="600"))
        assert out["order_type"] == "SLM"
        assert out["price"] == "0"
        assert out["trigger_price"] == "600"

    @pytest.mark.parametrize("pricetype", ["SL", "SL-M"])
    @pytest.mark.parametrize("trigger", [None, "0", 0, "", "abc", "inf", "nan", "-5", 10**400])
    def test_stop_without_trigger_is_refused(self, pricetype, trigger):
        data = order(pricetype=pricetype, price="599")
        if trigger is not None:
            data["trigger_price"] = trigger
        with pytest.raises(td.OrderRejected, match="trigger price is required"):
            td.transform_data(data)

    def test_market_and_limit_send_no_trigger(self):
        assert "trigger_price" not in td.transform_data(order(pricetype="MARKET"))
        assert "trigger_price" not in td.transform_data(order(pricetype="LIMIT", price="600"))

    @pytest.mark.parametrize("pricetype", ["STOPLOSS", "SLM", "", None])
    def test_unknown_price_type_is_refused_not_sent_as_market(self, pricetype):
        with pytest.raises(td.OrderRejected, match="does not accept the price type"):
            td.transform_data(order(pricetype=pricetype))


class TestPlaceOrderApi:
    def test_slm_payload_reaches_paytm(self):
        with patch.object(
            order_api,
            "get_api_response",
            return_value={"status": "success", "data": [{"order_no": "77"}]},
        ) as api:
            res, _, orderid = order_api.place_order_api(
                order(pricetype="SL-M", trigger_price="600"), "auth"
            )
        sent = json.loads(api.call_args.kwargs["payload"])
        assert (res.status, orderid) == (200, "77")
        assert sent["order_type"] == "SLM"
        assert sent["trigger_price"] == "600"

    def test_refused_order_is_never_sent(self):
        with patch.object(order_api, "get_api_response") as api:
            res, body, orderid = order_api.place_order_api(order(pricetype="SL"), "auth")
        api.assert_not_called()
        assert res.status == 400
        assert body["status"] == "error"
        assert "trigger price is required" in body["message"]
        assert orderid is None


class TestModifyOrder:
    BOOK = {
        "status": "success",
        "data": [
            {
                "order_no": "77",
                "status": "OPEN",
                "exchange": "NSE",
                "segment": "E",
                "security_id": "3045",
                "quantity": "10",
                "price": "601",
                "trigger_price": "0",
                "product": "I",
                "order_type": "LMT",
                "txn_type": "S",
                "serial_no": 1,
                "group_id": 1,
            }
        ],
    }

    def modify(self, **data):
        with (
            patch.object(order_api, "get_order_book", return_value=self.BOOK),
            patch.object(
                order_api,
                "get_api_response",
                side_effect=lambda **kw: (
                    self.BOOK
                    if "modify" not in kw["endpoint"]
                    else {"status": "success", "data": [{"order_no": "77"}]}
                ),
            ) as api,
        ):
            result = order_api.modify_order({"orderid": "77", "product": "MIS", **data}, "auth")
        modify_calls = [c for c in api.call_args_list if "modify" in c.kwargs["endpoint"]]
        payload = json.loads(modify_calls[0].kwargs["payload"]) if modify_calls else None
        return result, payload

    def test_limit_to_slm_changes_type_and_trigger(self):
        (body, status), payload = self.modify(pricetype="SL-M", trigger_price="600", price="0")
        assert status == 200, body
        assert payload["order_type"] == "SLM"
        assert payload["price"] == "0"
        assert payload["trigger_price"] == "600"

    @pytest.mark.parametrize("trigger", ["0", "abc", "inf"])
    def test_stop_modify_without_a_valid_trigger_is_refused(self, trigger):
        (body, status), payload = self.modify(pricetype="SL", trigger_price=trigger, price="599")
        assert status == 400
        assert "trigger price is required" in body["message"]
        assert payload is None

    def test_stop_modify_keeps_the_existing_trigger(self):
        book = {**self.BOOK["data"][0], "order_type": "SL", "trigger_price": "600"}
        self.BOOK = {"status": "success", "data": [book]}
        (body, status), payload = self.modify(price="599")
        assert status == 200, body
        assert payload["order_type"] == "SL"
        assert payload["trigger_price"] == "600"

    def test_unknown_price_type_is_refused(self):
        (body, status), payload = self.modify(pricetype="STOPLOSS", price="600")
        assert status == 400
        assert payload is None
