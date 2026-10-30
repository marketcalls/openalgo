"""Fyers MCX and CDS quantity convention: OpenAlgo units in, Fyers lots out.

Fyers counts MCX and CDS order quantity in lots: every row of its MCX and CDS
symbol masters has ``minLotSize`` 1 and the units in a lot as ``qtyMultiplier``,
which the master contract keeps as ``symtoken.lotsize`` (CRUDEOILM 10, USDINR
1000). OpenAlgo's quantity is therefore units, as on every other broker, and
the plugin used to send it on unchanged: a one-lot CRUDEOILM order, quantity
10, reached Fyers as 10 lots, and a one-lot USDINR order as 1000.

Both directions are pinned here, since each half alone looks correct. A missing
outbound divide places 10x or 1000x the order; a missing inbound multiply
understates a position by the same factor, and that number feeds smart-order
sizing. Fyers is faked at its HTTP client and lot sizes at the contract lookup.
"""

import json
from types import SimpleNamespace

import pytest

import broker.fyers.api.order_api as order_api
from broker.fyers.mapping import transform_data
from broker.fyers.mapping.transform_data import LotQuantityError, from_fyers_qty, to_fyers_qty

CRUDEOILM = "CRUDEOILM19NOV26FUT"  # 10 barrels a lot
CRUDEOIL = "CRUDEOIL19NOV26FUT"  # 100 barrels a lot
GOLDPETAL = "GOLDPETAL30NOV26FUT"  # 1 gram a lot
USDINR = "USDINR26NOV26FUT"  # 1000 dollars a lot
NIFTY = "NIFTY24NOV2625000CE"

LOT_SIZES = {
    (CRUDEOILM, "MCX"): 10,
    (CRUDEOIL, "MCX"): 100,
    (GOLDPETAL, "MCX"): 1,
    (USDINR, "CDS"): 1000,
    (NIFTY, "NFO"): 65,
}


@pytest.fixture(autouse=True)
def master_contract(monkeypatch):
    def get_symbol_info(symbol, exchange):
        size = LOT_SIZES.get((symbol, exchange))
        return SimpleNamespace(lotsize=size) if size else None

    monkeypatch.setattr(transform_data, "get_symbol_info", get_symbol_info)


class TestConversion:
    @pytest.mark.parametrize(
        "quantity,symbol,exchange,lots",
        [
            (10, CRUDEOILM, "MCX", 1),
            (30, CRUDEOILM, "MCX", 3),
            (200, CRUDEOIL, "MCX", 2),
            (5, GOLDPETAL, "MCX", 5),
            (1000, USDINR, "CDS", 1),
            (5000, USDINR, "CDS", 5),
        ],
    )
    def test_units_go_out_as_lots(self, quantity, symbol, exchange, lots):
        assert to_fyers_qty(quantity, symbol, exchange) == lots

    @pytest.mark.parametrize(
        "lots,symbol,exchange,units",
        [
            (1, CRUDEOILM, "MCX", 10),
            (-3, CRUDEOILM, "MCX", -30),
            ("2", CRUDEOIL, "MCX", 200),
            (1, USDINR, "CDS", 1000),
            (-2, USDINR, "CDS", -2000),
        ],
    )
    def test_lots_come_back_as_units(self, lots, symbol, exchange, units):
        assert from_fyers_qty(lots, symbol, exchange) == units

    @pytest.mark.parametrize("exchange", ["NFO", "NSE", "BFO", "BSE"])
    def test_other_exchanges_are_units_both_ways(self, exchange):
        assert to_fyers_qty(65, NIFTY, exchange) == 65
        assert from_fyers_qty(65, NIFTY, exchange) == 65

    def test_round_trip_is_the_identity(self):
        for (symbol, exchange), size in LOT_SIZES.items():
            assert from_fyers_qty(to_fyers_qty(3 * size, symbol, exchange), symbol, exchange) == (
                3 * size
            )

    def test_a_part_lot_is_refused_not_rounded(self):
        with pytest.raises(LotQuantityError, match="multiples of lot size 10"):
            to_fyers_qty(15, CRUDEOILM, "MCX")
        with pytest.raises(LotQuantityError, match="multiples of lot size 1000"):
            to_fyers_qty(1, USDINR, "CDS")

    def test_the_field_is_named_in_the_error(self):
        with pytest.raises(LotQuantityError, match="^Disclosed quantity must be"):
            to_fyers_qty(5, CRUDEOILM, "MCX", field="Disclosed quantity")

    def test_an_mcx_contract_with_no_lot_size_is_refused_outbound(self):
        with pytest.raises(LotQuantityError, match="no lot size"):
            to_fyers_qty(10, "UNKNOWN19NOV26FUT", "MCX")

    def test_an_unknown_contract_passes_through_inbound(self):
        """A book row with no lot size shows Fyers' number rather than breaking the book."""
        assert from_fyers_qty(2, "UNKNOWN19NOV26FUT", "MCX") == 2

    def test_an_unmapped_row_keeps_fyers_numeric_exchange_and_passes_through(self):
        assert from_fyers_qty(1, "MCX:CRUDEOILM26NOVFUT", 11) == 1

    def test_zero_needs_no_lot_size(self):
        assert to_fyers_qty(0, "UNKNOWN19NOV26FUT", "MCX") == 0


class _FakeFyers:
    """Records the JSON bodies sent to Fyers and answers every call with ``body``."""

    def __init__(self, body):
        self.body = body
        self.sent = []

    def post(self, url, **kwargs):
        self.sent.append(kwargs.get("json"))
        return SimpleNamespace(status_code=200, json=lambda: self.body)

    def patch(self, url, **kwargs):
        return self.post(url, **kwargs)


def _order(symbol, exchange, quantity, **extra):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "action": "BUY",
        "quantity": str(quantity),
        "pricetype": "LIMIT",
        "price": "9432",
        "product": "NRML",
        **extra,
    }


class TestOrderPayloads:
    @pytest.fixture
    def fyers(self, monkeypatch):
        client = _FakeFyers({"s": "ok", "id": "26102900000001"})
        monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
        monkeypatch.setattr(
            "broker.fyers.mapping.transform_data.get_br_symbol",
            lambda symbol, exchange: f"{exchange}:{symbol}",
        )
        return client

    def test_a_one_lot_crude_mini_order_goes_out_as_one_lot(self, fyers):
        _, _, orderid = order_api.place_order_api(_order(CRUDEOILM, "MCX", 10), "token")

        assert orderid == "26102900000001"
        assert fyers.sent[0]["qty"] == 1

    def test_a_one_lot_usdinr_order_goes_out_as_one_lot(self, fyers):
        order_api.place_order_api(_order(USDINR, "CDS", 1000), "token")

        assert fyers.sent[0]["qty"] == 1

    def test_an_nfo_order_still_goes_out_in_units(self, fyers):
        order_api.place_order_api(_order(NIFTY, "NFO", 65), "token")

        assert fyers.sent[0]["qty"] == 65

    def test_disclosed_quantity_goes_out_in_lots_too(self, fyers):
        order_api.place_order_api(_order(CRUDEOIL, "MCX", 500, disclosed_quantity="100"), "token")

        assert (fyers.sent[0]["qty"], fyers.sent[0]["disclosedQty"]) == (5, 1)

    def test_a_part_lot_order_is_refused_with_a_400_and_never_sent(self, fyers):
        response, body, orderid = order_api.place_order_api(_order(CRUDEOILM, "MCX", 15), "token")

        assert (response.status, orderid, fyers.sent) == (400, None, [])
        assert "multiples of lot size 10" in body["message"]

    def test_a_modify_goes_out_in_lots(self, fyers):
        body, status = order_api.modify_order(
            {**_order(CRUDEOILM, "MCX", 20), "orderid": "26102900000001"}, "token"
        )

        assert status == 200, body
        assert fyers.sent[0]["qty"] == 2

    def test_a_part_lot_modify_is_refused_with_a_400_and_never_sent(self, fyers):
        body, status = order_api.modify_order(
            {**_order(USDINR, "CDS", 1500), "orderid": "26102900000001"}, "token"
        )

        assert (status, fyers.sent) == (400, [])
        assert "multiples of lot size 1000" in body["message"]


class TestWhatComesBack:
    def test_the_order_trade_and_position_books_come_back_in_units(self):
        from broker.fyers.mapping import order_data

        mapped = {"symbol": CRUDEOILM, "exchange": "MCX", "side": 1, "productType": "MARGIN"}
        (order,) = order_data.transform_order_data([{**mapped, "qty": 2, "status": 6, "type": 1}])
        (trade,) = order_data.transform_tradebook_data([{**mapped, "tradedQty": 1}])
        (position,) = order_data.transform_positions_data(
            [{**mapped, "netQty": -1, "netAvg": 9432, "ltp": 9440, "pl": -80}]
        )

        assert (order["quantity"], trade["quantity"], position["quantity"]) == (20, 10, -10)

    def test_a_cds_position_comes_back_in_units(self):
        from broker.fyers.mapping import order_data

        (position,) = order_data.transform_positions_data(
            [{"symbol": USDINR, "exchange": "CDS", "netQty": 3, "productType": "MARGIN"}]
        )

        assert position["quantity"] == 3000

    def test_an_nfo_position_is_unchanged(self):
        from broker.fyers.mapping import order_data

        (position,) = order_data.transform_positions_data(
            [{"symbol": NIFTY, "exchange": "NFO", "netQty": 65, "productType": "MARGIN"}]
        )

        assert position["quantity"] == 65

    def test_the_open_position_a_smart_order_sizes_against_is_in_units(self, monkeypatch):
        monkeypatch.setattr(order_api, "get_br_symbol", lambda symbol, exchange: "MCX:CRUDEOILM")
        monkeypatch.setattr(
            order_api,
            "_get_cached_positions",
            lambda auth: {
                "s": "ok",
                "netPositions": [{"symbol": "MCX:CRUDEOILM", "productType": "MARGIN", "netQty": 2}],
            },
        )

        assert int(order_api.get_open_position(CRUDEOILM, "MCX", "MARGIN", "token")) == 20

    def test_a_smart_order_square_off_sells_the_lots_fyers_holds(self, monkeypatch):
        """Two lots open at Fyers, position_size 0: exactly two lots go back out."""
        client = _FakeFyers({"s": "ok", "id": "26102900000002"})
        monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
        monkeypatch.setattr(order_api, "get_br_symbol", lambda symbol, exchange: "MCX:CRUDEOILM")
        monkeypatch.setattr(
            "broker.fyers.mapping.transform_data.get_br_symbol",
            lambda symbol, exchange: "MCX:CRUDEOILM",
        )
        monkeypatch.setattr(
            order_api,
            "_get_cached_positions",
            lambda auth: {
                "s": "ok",
                "netPositions": [{"symbol": "MCX:CRUDEOILM", "productType": "MARGIN", "netQty": 2}],
            },
        )

        order_api.place_smartorder_api(
            {**_order(CRUDEOILM, "MCX", 0), "action": "SELL", "position_size": "0"}, "token"
        )

        assert [(sent["side"], sent["qty"]) for sent in client.sent] == [(-1, 2)]

    def test_an_order_update_comes_back_in_units(self, monkeypatch):
        from broker.fyers.streaming import fyers_order_adapter

        monkeypatch.setattr(
            fyers_order_adapter, "to_openalgo_symbol", lambda symbol, exchange: CRUDEOILM
        )
        adapter = fyers_order_adapter.FyersOrderUpdateAdapter(
            user_id="u", app_id="a", access_token="t"
        )
        record = {
            "id": "26102900000001",
            "symbol": "MCX:CRUDEOILM26NOVFUT",
            "exchange": 11,
            "segment": 20,
            "org_ord_status": 6,
            "qty": 3,
            "qty_filled": 1,
            "tran_side": 1,
            "ord_type": 1,
        }

        update = adapter.normalize(json.dumps({"orders": record, "s": "ok"}))

        assert (update["quantity"], update["filled_quantity"], update["pending_quantity"]) == (
            30,
            10,
            20,
        )

    def test_a_postback_comes_back_in_units(self, monkeypatch):
        import blueprints.postback as postback

        monkeypatch.setattr(postback, "to_openalgo_symbol", lambda symbol, exchange: USDINR)
        payload = {
            "id": "26102900000001",
            "status": 6,
            "symbol": "NSE:USDINR26NOVFUT",
            "exchange": 10,
            "segment": 12,
            "qty": 3,
            "filledQty": 1,
            "remainingQuantity": 2,
            "side": 1,
            "type": 1,
            "productType": "MARGIN",
        }

        fields = postback._NORMALIZERS["fyers"](payload)

        assert fields["exchange"] == "CDS"
        assert (fields["quantity"], fields["filled_quantity"], fields["pending_quantity"]) == (
            3000,
            1000,
            2000,
        )


class TestMarginAndGtt:
    def test_margin_goes_out_in_lots(self, monkeypatch):
        from broker.fyers.mapping import margin_data

        monkeypatch.setattr(
            margin_data, "get_br_symbol", lambda symbol, exchange: f"{exchange}:{symbol}"
        )

        positions = margin_data.transform_margin_positions(
            [
                _order(CRUDEOILM, "MCX", 30),
                _order(USDINR, "CDS", 2000),
                _order(NIFTY, "NFO", 65),
            ]
        )

        assert [p["qty"] for p in positions] == [3, 2, 65]

    def test_a_basket_with_a_part_lot_leg_is_refused_whole(self, monkeypatch):
        """Not priced without the bad leg and answered as a success."""
        from broker.fyers.api import margin_api
        from broker.fyers.mapping import margin_data

        monkeypatch.setattr(
            margin_data, "get_br_symbol", lambda symbol, exchange: f"{exchange}:{symbol}"
        )
        monkeypatch.setattr(
            margin_api, "get_httpx_client", lambda: pytest.fail("margin must not be requested")
        )

        response, body = margin_api.calculate_margin_api(
            [_order(NIFTY, "NFO", 65), _order(CRUDEOILM, "MCX", 15)], "token"
        )

        assert response.status == 400
        assert "multiples of lot size 10" in body["message"]

    def test_a_gtt_goes_out_in_lots(self, monkeypatch):
        from broker.fyers.mapping import gtt_data

        monkeypatch.setattr(gtt_data, "get_br_symbol", lambda symbol, exchange: f"MCX:{symbol}")

        payload = gtt_data.transform_place_gtt(
            {
                **_order(CRUDEOILM, "MCX", 20),
                "trigger_type": "OCO",
                "triggerprice_sl": 9300,
                "triggerprice_tg": 9600,
                "stoploss": 9290,
                "target": 9610,
            }
        )

        assert (payload["orderInfo"]["leg1"]["qty"], payload["orderInfo"]["leg2"]["qty"]) == (2, 2)

    def test_a_part_lot_gtt_is_refused_with_a_400_and_never_sent(self, monkeypatch):
        from broker.fyers.api import gtt_api

        monkeypatch.setattr(
            "broker.fyers.mapping.gtt_data.get_br_symbol",
            lambda symbol, exchange: f"MCX:{symbol}",
        )
        monkeypatch.setattr(
            gtt_api, "_request", lambda *args, **kwargs: pytest.fail("GTT must not be sent")
        )

        response, body, trigger_id = gtt_api.place_gtt_order(
            {**_order(CRUDEOILM, "MCX", 15), "trigger_type": "SINGLE", "trigger_price": 9400},
            "token",
        )

        assert (response.status, trigger_id) == (400, None)
        assert "multiples of lot size 10" in body["message"]

    def test_the_gtt_book_comes_back_in_units(self, monkeypatch):
        from broker.fyers.mapping import gtt_data

        monkeypatch.setattr(gtt_data, "get_oa_symbol", lambda brsymbol, exchange: CRUDEOILM)

        (gtt,) = gtt_data.map_gtt_book(
            {
                "orderBook": [
                    {
                        "id": "1",
                        "ord_status": 6,
                        "exchange": 11,
                        "segment": 20,
                        "symbol": "MCX:CRUDEOILM26NOVFUT",
                        "tran_side": 1,
                        "product_type": "MARGIN",
                        "gtt_oco_ind": 2,
                        "price_limit": 9610,
                        "price_trigger": 9600,
                        "qty": 2,
                        "price2_limit": 9290,
                        "price2_trigger": 9300,
                        "qty2": 2,
                    }
                ]
            }
        )

        assert [leg["quantity"] for leg in gtt["legs"]] == [20, 20]
