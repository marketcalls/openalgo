"""Kotak market depth payload.

Neo's quote filters are strict subsets: `/depth` returns the order book alone,
with no ltp, ohlc, volume or oi, while `/all` returns the identical book plus
all of them for the same single request. get_depth asked for the narrow one and
so returned 4 of the 12 fields docs/api/market-data/depth.md specifies, the only
broker in the tree that did -- every other one returns all 12.

These pin the filter and the field set, because the filter is a one-word string
that would cost eight fields again if it were ever narrowed back.
"""

from unittest.mock import patch

import pytest

import broker.kotak.api.data as kotak_data

AUTH = "sess:::sid:::https://gw-napi.kotaksecurities.com:::acc"

# The documented OpenAlgo depth contract.
CONTRACT = {
    "open", "high", "low", "ltp", "ltq", "prev_close",
    "volume", "oi", "totalbuyqty", "totalsellqty", "bids", "asks",
}


def _row(**over):
    """A Neo `all` response row. Every value is a string, as Neo sends them."""
    row = {
        "exchange_token": "2885",
        "display_symbol": "RELIANCE-EQ",
        "ltp": "1245.6000",
        "last_traded_quantity": "2",
        "last_volume": "6914844",
        "open_int": "0",
        "total_buy": "639837",
        "total_sell": "757792",
        "ohlc": {
            "open": "1242.0000",
            "high": "1252.8000",
            "low": "1238.9000",
            "close": "1240.4000",
        },
        "depth": {
            "buy": [{"price": f"124{5 - i}.6000", "quantity": "100", "orders": "3"} for i in range(5)],
            "sell": [{"price": f"124{5 + i}.7000", "quantity": "200", "orders": "4"} for i in range(5)],
        },
    }
    row.update(over)
    return row


@pytest.fixture
def broker_data():
    return kotak_data.BrokerData(AUTH)


def _depth(broker_data, row, symbol="RELIANCE", exchange="NSE"):
    """Run get_depth over one canned response, capturing the filter requested."""
    seen = {}

    def fake_request(self, query, filter_name="all"):
        seen["query"] = query
        seen["filter"] = filter_name
        return [row] if row is not None else None

    with (
        patch.object(kotak_data, "get_token", return_value="2885"),
        patch.object(kotak_data, "get_brexchange", return_value="NSE"),
        patch.object(kotak_data.BrokerData, "_make_quotes_request", fake_request),
    ):
        return broker_data.get_depth(symbol, exchange), seen


def test_depth_asks_for_the_all_filter(broker_data):
    # The whole point: the narrow filter drops eight of the twelve fields.
    _, seen = _depth(broker_data, _row())
    assert seen["filter"] == "all"


def test_index_depth_asks_for_the_all_filter(broker_data):
    seen = {}

    def fake_candidates(self, kotak_exchange, candidates, filter_name="all"):
        seen["filter"] = filter_name
        return [_row()], "nse_cm|Nifty 50"

    with patch.object(kotak_data.BrokerData, "_query_index_with_candidates", fake_candidates):
        broker_data.get_depth("NIFTY", "NSE_INDEX")

    assert seen["filter"] == "all"


def test_depth_returns_the_whole_documented_contract(broker_data):
    depth, _ = _depth(broker_data, _row())

    assert CONTRACT <= set(depth), f"missing {sorted(CONTRACT - set(depth))}"
    assert depth["ltp"] == pytest.approx(1245.6)
    assert depth["ltq"] == 2
    assert depth["open"] == pytest.approx(1242.0)
    assert depth["high"] == pytest.approx(1252.8)
    assert depth["low"] == pytest.approx(1238.9)
    # Neo's ohlc.close is the previous close, not the last price.
    assert depth["prev_close"] == pytest.approx(1240.4)
    assert depth["volume"] == 6914844
    assert len(depth["bids"]) == 5 and len(depth["asks"]) == 5


def test_broker_book_total_is_preferred_over_the_visible_levels(broker_data):
    # Cash: Neo reports the whole book (639837), far more than the five visible
    # levels sum to (5 x 100). Reporting the sum would understate the book.
    depth, _ = _depth(broker_data, _row())

    assert depth["totalbuyqty"] == 639837
    assert depth["totalsellqty"] == 757792


def test_unreported_book_total_falls_back_to_the_visible_levels(broker_data):
    # F&O: Neo leaves total_buy/total_sell at 0, so the five levels are all there
    # is. A bare passthrough would report an empty book on every derivative.
    depth, _ = _depth(broker_data, _row(total_buy="0", total_sell="0"))

    assert depth["totalbuyqty"] == 500   # 5 levels x 100
    assert depth["totalsellqty"] == 1000  # 5 levels x 200


def test_decimal_quantity_strings_coerce(broker_data):
    # int("16131960.0000") raises; oi and volume have to survive that shape.
    depth, _ = _depth(broker_data, _row(open_int="16131960.0000", last_volume="1507350.0000"))

    assert depth["oi"] == 16131960
    assert depth["volume"] == 1507350


def test_missing_fields_do_not_raise(broker_data):
    depth, _ = _depth(broker_data, {"depth": {"buy": [], "sell": []}})

    assert CONTRACT <= set(depth)
    assert depth["ltp"] == 0.0
    assert depth["oi"] == 0
    assert len(depth["bids"]) == 5  # padded to five empty levels


def test_error_path_has_the_same_shape_as_success(broker_data):
    # A caller reading depth["ltp"] must not hit KeyError just because the
    # quote could not be fetched.
    depth, _ = _depth(broker_data, None)

    assert set(depth) == set(broker_data._get_default_depth())
    assert CONTRACT <= set(depth)
