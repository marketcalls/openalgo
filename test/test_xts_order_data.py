"""The Symphony XTS plugins keep order ids exact, show the traded average of a
carried position, and report a position-book error instead of hiding it.

Issue #2462: AppOrderIDs run to 20 digits and float() rounded them, so every
order of a day shared one id in the order book and trade book; and carried
positions showed XTS's BuyAveragePrice / SellAveragePrice, which it fills with
the previous close, instead of the traded ActualBuyAveragePrice /
ActualSellAveragePrice.

Issue #633: an error answer to the position read crashed six XTS plugins
("'list' object has no attribute 'get'") and read as an empty book on Wisdom.

Every case runs each plugin's own mapping functions.
"""

import importlib
import json

import pytest

from utils import xts_order_data

BROKERS = ["compositedge", "fivepaisaxts", "ibulls", "iifl", "jainamxts", "rmoney", "wisdom"]

# Three consecutive Wisdom ids from issue #2462; float() made all three
# 11001263160000030720.
IDS = ["11001263160000030116", "11001263160000030117", "11001263160000030118"]


def _module(broker):
    return importlib.import_module(f"broker.{broker}.mapping.order_data")


def _order(app_order_id):
    return {
        "TradingSymbol": "SBIN",
        "ExchangeSegment": "NSECM",
        "OrderSide": "BUY",
        "OrderQuantity": 1,
        "OrderPrice": 800.0,
        "OrderStopPrice": 0.0,
        "OrderType": "Limit",
        "OrderStatus": "New",
        "ProductType": "MIS",
        "AppOrderID": app_order_id,
        "LastUpdateDateTime": "17-11-2026 10:00:00",
        "OrderAverageTradedPrice": 800.0,
        "OrderGeneratedDateTime": "17-11-2026 10:00:00",
    }


# ------------------------------------------------------------------ order ids


@pytest.mark.parametrize("as_json_number", [True, False], ids=["json number", "string"])
def test_exact_order_id_keeps_every_digit(as_json_number):
    values = [json.loads(i) if as_json_number else i for i in IDS]

    assert [xts_order_data.exact_order_id(v) for v in values] == IDS


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "0"), ("", "0"), (0, "0"), ("1234.0", "1234"), (" 42 ", "42"), ("ABC-1", "ABC-1")],
)
def test_exact_order_id_edges(value, expected):
    assert xts_order_data.exact_order_id(value) == expected


@pytest.mark.parametrize("broker", BROKERS)
def test_the_order_book_keeps_each_orders_own_id(broker):
    od = _module(broker)
    orders = [_order(json.loads(i)) for i in IDS]

    rows = od.transform_order_data(orders)

    assert [row["orderid"] for row in rows] == IDS


@pytest.mark.parametrize("broker", BROKERS)
def test_the_trade_book_keeps_each_trades_own_id(broker):
    od = _module(broker)
    trades = [_order(json.loads(i)) for i in IDS]

    rows = od.transform_tradebook_data(trades)

    assert [row["orderid"] for row in rows] == IDS


# ------------------------------------------------------------- average price


def _position(quantity, **prices):
    return {
        "TradingSymbol": "HAL 23NOV2026 PE 5000",
        "ExchangeSegment": "NSEFO",
        "ExchangeInstrumentId": "41880",
        "ProductType": "NRML",
        "Quantity": str(quantity),
        **prices,
    }


@pytest.fixture
def no_master_contract(monkeypatch):
    for broker in BROKERS:
        monkeypatch.setattr(_module(broker), "get_symbol", lambda token, exchange: None)


@pytest.mark.parametrize("broker", BROKERS)
@pytest.mark.parametrize(
    ("position", "average"),
    [
        # A long carried overnight (issue #2462's HAL row): the traded average,
        # not the previous close XTS marked it to.
        (_position(75, BuyAveragePrice="244", ActualBuyAveragePrice=154.65), "154.65"),
        # A short carried overnight.
        (_position(-300, SellAveragePrice="120.5", ActualSellAveragePrice=116.075), "116.08"),
        # A deployment that does not send the Actual fields keeps the documented one.
        (_position(75, BuyAveragePrice="79.7"), "79.70"),
        # An Actual field of zero is not a price.
        (_position(75, BuyAveragePrice="79.7", ActualBuyAveragePrice=0), "79.70"),
        # A flat position has no average.
        (_position(0, BuyAveragePrice="18.34", ActualBuyAveragePrice=18.34), "0.00"),
    ],
    ids=["carried long", "carried short", "no actual field", "actual zero", "flat"],
)
def test_a_position_shows_its_traded_average(no_master_contract, broker, position, average):
    od = _module(broker)

    [row] = od.transform_positions_data(od.map_position_data(_answer([position])))

    assert row["average_price"] == average


# ------------------------------------------------------------ position errors


def _answer(rows):
    return {
        "type": "success",
        "code": "s-portfolio-0009",
        "description": "Success get position",
        "result": {"positionList": rows},
    }


ERROR = {"type": "error", "code": "e-session-0007", "description": "Invalid Token", "result": {}}


@pytest.mark.parametrize("broker", BROKERS)
def test_a_position_error_is_reported_not_read_as_an_empty_book(broker):
    od = _module(broker)

    with pytest.raises(ValueError) as refused:
        od.transform_positions_data(od.map_position_data(ERROR))

    assert "did not return your positions" in str(refused.value)
    assert "Invalid Token" in str(refused.value)


@pytest.mark.parametrize("broker", BROKERS)
def test_an_empty_book_is_still_empty(no_master_contract, broker):
    od = _module(broker)

    assert od.transform_positions_data(od.map_position_data(_answer([]))) == []


@pytest.mark.parametrize("broker", BROKERS)
def test_the_position_book_service_shows_the_error(monkeypatch, broker):
    import services.positionbook_service as service

    api = importlib.import_module(f"broker.{broker}.api.order_api")
    monkeypatch.setattr(api, "get_positions", lambda auth: dict(ERROR))
    monkeypatch.setattr("database.settings_db.get_analyze_mode", lambda: False)

    ok, body, status = service.get_positionbook_with_auth("token", broker)

    assert (ok, status) == (False, 500)
    assert "did not return your positions" in body["message"]
    assert "Invalid Token" in body["message"]


def test_the_issue_633_answer_reads_its_positions(no_master_contract):
    """The live Wisdom NetWise answer quoted on issue #633, one row."""
    answer = _answer(
        [
            {
                "TradingSymbol": "NIFTY 16DEC2025 CE 25950",
                "ExchangeSegment": "NSEFO",
                "ExchangeInstrumentId": "48222",
                "ProductType": "NRML",
                "BuyAveragePrice": "0",
                "SellAveragePrice": "116.075",
                "Quantity": "-300",
                "ActualSellAveragePrice": 116.075,
                "ActualBuyAveragePrice": 0,
            }
        ]
    )
    od = _module("wisdom")

    [row] = od.transform_positions_data(od.map_position_data(answer))

    assert (row["symbol"], row["exchange"], row["quantity"]) == (
        "NIFTY 16DEC2025 CE 25950",
        "NFO",
        "-300",
    )
    assert row["average_price"] == "116.08"
