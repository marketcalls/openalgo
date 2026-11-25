"""5paisa XTS reads XTS answers the way the XTS v2 docs describe them.

https://symphonyfintech.com/xts-trading-front-end-api-v2/ and
https://symphonyfintech.com/xts-market-data-front-end-api-v2/

- A smart order finds the open position (it read "status"/"data" keys XTS
  never sends, so every position read as 0).
- Each trade-book row is one fill (LastTradedQuantity / LastTradedPrice).
- Replaced, PartiallyFilled and the Pending order states are open, and cancel
  all cancels them.
- Cancel and modify read XTS's {"type": ...} answer.
- Funds use the ALL|ALL|ALL balance entry.
- Futures master rows have 21 fields, options 23; spreads are not contracts.
- Streaming reads Touchline whatever the message code.
"""

import csv
import logging

import pytest

from broker.fivepaisaxts.api import funds as fp_funds
from broker.fivepaisaxts.api import order_api as fp_orders
from broker.fivepaisaxts.database import master_contract_db as fp_master
from broker.fivepaisaxts.mapping import order_data as fp_mapping


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def _answer(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _Response(self.payload, self.status_code)

    def get(self, url, **kwargs):
        return self._answer("GET", url, **kwargs)

    def put(self, url, **kwargs):
        return self._answer("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._answer("DELETE", url, **kwargs)


# ------------------------------------------------------------- open position


def _positions(*rows):
    return {"type": "success", "result": {"positionList": list(rows)}}


def _position(**overrides):
    row = {
        "TradingSymbol": "NIFTY 27OCT2026 CE 22400",
        "ExchangeSegment": "NSEFO",
        "ExchangeInstrumentId": "48225",
        "ProductType": "NRML",
        "Quantity": "-75",
    }
    row.update(overrides)
    return row


@pytest.fixture
def open_position(monkeypatch):
    def run(book, token="48225", exchange="NFO", product="NRML"):
        monkeypatch.setattr(fp_orders, "_get_cached_positions", lambda auth: book)
        monkeypatch.setattr(fp_orders, "get_token", lambda symbol, exch: token)
        monkeypatch.setattr(fp_orders, "get_br_symbol", lambda symbol, exch: "NIFTY26OCT22400CE")
        return fp_orders.get_open_position("NIFTY27OCT2622400CE", exchange, product, "auth")

    return run


def test_open_position_matches_the_instrument_not_the_name(open_position):
    assert open_position(_positions(_position())) == "-75"


def test_open_position_accepts_the_docs_spelling_of_the_instrument_id(open_position):
    row = _position()
    row["ExchangeInstrumentID"] = row.pop("ExchangeInstrumentId")
    assert open_position(_positions(row)) == "-75"


@pytest.mark.parametrize(
    "row",
    [
        _position(ProductType="MIS"),
        _position(ExchangeSegment="BSEFO"),
        _position(ExchangeInstrumentId="99999"),
    ],
    ids=["other product", "other exchange", "other instrument"],
)
def test_open_position_ignores_other_rows(open_position, row):
    assert open_position(_positions(row)) == "0"


def test_open_position_reads_zero_from_an_error_answer(open_position):
    assert open_position({"type": "error", "description": "x"}) == "0"


# -------------------------------------------------------------- trade book


def test_trade_book_row_is_one_fill():
    fill = {
        "TradingSymbol": "SBIN",
        "ExchangeSegment": "NSECM",
        "OrderSide": "BUY",
        "ProductType": "MIS",
        "AppOrderID": "1100126316",
        "OrderQuantity": 100,
        "OrderAverageTradedPrice": 801.0,
        "LastTradedQuantity": 40,
        "LastTradedPrice": 800.5,
        "LastExecutionTransactTime": "17-11-2026 10:00:05",
        "OrderGeneratedDateTime": "17-11-2026 10:00:00",
    }

    [row] = fp_mapping.transform_tradebook_data([fill])

    assert row["quantity"] == 40
    assert row["average_price"] == 800.5
    assert row["trade_value"] == pytest.approx(40 * 800.5)
    assert row["timestamp"] == "17-11-2026 10:00:05"


def test_trade_book_row_without_fill_fields_keeps_order_fields():
    order = {
        "ExchangeSegment": "NSECM",
        "AppOrderID": "1",
        "OrderQuantity": 10,
        "OrderAverageTradedPrice": 5.0,
        "OrderGeneratedDateTime": "t",
    }

    [row] = fp_mapping.transform_tradebook_data([order])

    assert (row["quantity"], row["average_price"], row["timestamp"]) == (10, 5.0, "t")


# ------------------------------------------------------------ order status


@pytest.mark.parametrize(
    "status,expected",
    [
        ("New", "open"),
        ("PartiallyFilled", "open"),
        ("Replaced", "open"),
        ("PendingNew", "open"),
        ("PendingReplace", "open"),
        ("PendingCancel", "open"),
        ("Filled", "complete"),
        ("Rejected", "rejected"),
        ("Cancelled", "cancelled"),
    ],
)
def test_order_status_maps_every_documented_state(status, expected):
    [row] = fp_mapping.transform_order_data([{"OrderStatus": status, "AppOrderID": "1"}])
    assert row["order_status"] == expected


def test_order_statistics_count_part_filled_and_modified_orders_as_open():
    orders = [
        {"OrderSide": "BUY", "OrderStatus": "PartiallyFilled"},
        {"OrderSide": "BUY", "OrderStatus": "Replaced"},
        {"OrderSide": "SELL", "OrderStatus": "Filled"},
    ]
    stats = fp_mapping.calculate_order_statistics(orders)
    assert stats["total_open_orders"] == 2
    assert stats["total_completed_orders"] == 1


def test_cancel_all_cancels_modified_and_part_filled_orders(monkeypatch):
    book = {
        "type": "success",
        "result": [
            {"AppOrderID": 1, "OrderStatus": "New"},
            {"AppOrderID": 2, "OrderStatus": "Replaced"},
            {"AppOrderID": 3, "OrderStatus": "PartiallyFilled"},
            {"AppOrderID": 4, "OrderStatus": "PendingCancel"},
            {"AppOrderID": 5, "OrderStatus": "Filled"},
        ],
    }
    cancelled = []
    monkeypatch.setattr(fp_orders, "get_order_book", lambda auth: book)
    monkeypatch.setattr(
        fp_orders,
        "cancel_order",
        lambda orderid, auth: (cancelled.append(orderid) or {"status": "success"}, 200),
    )
    monkeypatch.setattr(fp_orders.time, "sleep", lambda seconds: None)

    done, failed = fp_orders.cancel_all_orders_api({}, "auth")

    assert done == ["1", "2", "3"] and failed == []


# ------------------------------------------------------- cancel and modify


def test_cancel_reads_the_xts_success_answer(monkeypatch):
    client = _Client({"type": "success", "result": [{"AppOrderID": 7}]})
    monkeypatch.setattr(fp_orders, "get_httpx_client", lambda: client)

    body, status = fp_orders.cancel_order("7", "auth")

    assert (body["status"], status) == ("success", 200)
    method, url, kwargs = client.calls[0]
    assert method == "DELETE" and url.endswith("/interactive/orders")
    assert kwargs["params"] == {"appOrderID": "7"}


def test_cancel_reports_the_xts_reason(monkeypatch):
    client = _Client({"type": "error", "description": "Order is already cancelled"})
    monkeypatch.setattr(fp_orders, "get_httpx_client", lambda: client)

    body, status = fp_orders.cancel_order("7", "auth")

    assert body == {"status": "error", "message": "Order is already cancelled"}
    assert status != 200


def test_modify_reads_the_xts_success_answer(monkeypatch):
    client = _Client({"type": "success", "result": {"AppOrderID": 10001253450000041478}})
    monkeypatch.setattr(fp_orders, "get_httpx_client", lambda: client)
    monkeypatch.setattr(fp_orders, "get_token", lambda symbol, exch: "2885")
    monkeypatch.setattr(fp_orders, "get_br_symbol", lambda symbol, exch: "RELIANCE-EQ")
    monkeypatch.setattr(fp_orders, "transform_modify_order_data", lambda data, token: {})

    body, status = fp_orders.modify_order(
        {"symbol": "RELIANCE", "exchange": "NSE", "orderid": "10001253450000041478"}, "auth"
    )

    assert body == {"status": "success", "orderid": "10001253450000041478"}
    assert status == 200


# ------------------------------------------------------------------- funds


def test_funds_use_the_consolidated_balance_entry(monkeypatch):
    def entry(header, cash):
        return {
            "limitHeader": header,
            "limitObject": {
                "RMSSubLimits": {
                    "netMarginAvailable": cash,
                    "collateral": 0,
                    "UnrealizedMTM": 0,
                    "RealizedMTM": 0,
                    "marginUtilized": 0,
                }
            },
        }

    answer = {
        "type": "success",
        "result": {"BalanceList": [entry("CASH|NSE|MTF", 0), entry("ALL|ALL|ALL", 12500.5)]},
    }
    monkeypatch.setattr(fp_funds, "get_httpx_client", lambda: _Client(answer))

    assert fp_funds.get_margin_data("auth")["availablecash"] == "12500.50"


# ---------------------------------------------------------- master contract

# The three example rows of the docs (option, future) plus a spread row.
_OPTION = "NSEFO|48225|2|NIFTY|NIFTY2621725700PE|OPTIDX|NIFTY-OPTIDX|2604800048225|588|114.5|1801|0.05|65|1|-1|Nifty 50|2026-02-17T14:30:00|25700|4|NIFTY 17FEB2026 PE 25700|1|1|NIFTY2621725700PE"
_FUTURE = "NSEFO|49229|1|NIFTY|NIFTY26JANFUT|FUTIDX|NIFTY-FUTIDX|2602700049229|28369.8|23211.8|1801|0.1|65|1|-1|Nifty 50|2026-01-27T14:30:00|NIFTY 27JAN2026|2|1|NIFTY26JANFUT"
_SPREAD = "NSEFO|60000|4|NIFTY|NIFTYSPD|FUTIDX|NIFTY-FUTIDX|1|1|1|1|0.1|65|1|-1|Nifty 50|2026-01-27T14:30:00|NIFTY SPD|1|1|NIFTYSPD"
_FO_HEADER = "ExchangeSegment,ExchangeInstrumentID,InstrumentType,Name,Description,Series,NameWithSeries,InstrumentID,PriceBand.High,PriceBand.Low,FreezeQty,TickSize,LotSize,Multiplier,UnderlyingInstrumentId,UnderlyingIndexName,ContractExpiration,StrikePrice,OptionType,DisplayName, PriceNumerator,PriceDenominator,DetailedDescription"


def test_futures_rows_are_read_in_their_own_layout(tmp_path):
    rows = [fp_master._fo_row_in_options_layout(r.split("|")) for r in (_OPTION, _FUTURE, _SPREAD)]
    with open(tmp_path / "NSEFO.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FO_HEADER.split(","))
        writer.writerows(rows)

    df = fp_master.process_compositedge_nfo_csv(str(tmp_path))
    by_token = {str(t): r for t, r in zip(df["token"], df.to_dict("records"), strict=True)}

    assert set(by_token) == {"48225", "49229"}  # the spread is not a contract
    future = by_token["49229"]
    # PriceNumerator 2 sat where the options header puts OptionType, which
    # made this future a put with strike 1 before.
    assert (future["symbol"], future["instrumenttype"], future["strike"]) == (
        "NIFTY27JAN26FUT",
        "FUT",
        0.0,
    )
    assert future["lotsize"] == 65
    option = by_token["48225"]
    assert (option["symbol"], option["instrumenttype"], option["strike"]) == (
        "NIFTY17FEB2625700PE",
        "PE",
        25700.0,
    )


# --------------------------------------------------------------- streaming


def test_streaming_quote_reads_touchline_for_1501():
    import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)
    from broker.fivepaisaxts.streaming.fivepaisaxts_adapter import FivepaisaXTSWebSocketAdapter

    adapter = FivepaisaXTSWebSocketAdapter.__new__(FivepaisaXTSWebSocketAdapter)
    adapter.logger = logging.getLogger("test_fivepaisaxts_streaming")
    message = {
        "MessageCode": 1501,
        "Touchline": {"LastTradedPrice": 1723.0, "Open": 1696.8, "TotalTradedQuantity": 189238},
    }

    quote = adapter._normalize_market_data(message, 2)

    assert (quote["ltp"], quote["open"], quote["volume"]) == (1723.0, 1696.8, 189238)
