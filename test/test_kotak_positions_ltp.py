"""Kotak position LTP backfill.

Kotak's /quick/user/positions payload carries no live price field at all, so
get_positions() batch-fetches one and stamps it on for transform_positions_data
to read (issue #1972). These cover the two edges that are easy to regress: the
batch must not carry the same instrument twice, and a payload Kotak did not
shape as an object must not turn a positions read into an exception.
"""

import copy

import pytest

import broker.kotak.api.data as kotak_data
import broker.kotak.api.order_api as order_api
import broker.kotak.mapping.order_data as order_mapping

AUTH = "sess:::sid:::https://gw-napi.kotaksecurities.com:::acc"

_EQUITY = {
    "trdSym": "YESBANK-EQ",
    "exSeg": "nse_cm",
    "tok": "11915",
    "flBuyQty": "100",
    "flSellQty": "0",
    "cfBuyQty": "0",
    "cfSellQty": "0",
    "buyAmt": "2100",
    "sellAmt": "0",
    "avgnetprice": 0.0,
}
_OPTION = {
    "trdSym": "SENSEX2690376900CE",
    "exSeg": "bse_fo",
    "tok": "845001",
    "prod": "MIS",
    "flBuyQty": "20",
    "flSellQty": "20",
    "cfBuyQty": "0",
    "cfSellQty": "0",
    "buyAmt": "1400",
    "sellAmt": "1500",
    "avgnetprice": 0.0,
}

# The same instrument under two products, which is how a book grows duplicates.
RAW_POSITIONS = {
    "stat": "Ok",
    "data": [dict(_EQUITY, prod="MIS"), dict(_EQUITY, prod="NRML"), _OPTION],
}

TOKEN_TO_SYMBOL = {
    ("11915", "NSE"): "YESBANK",
    ("845001", "BFO"): "SENSEX03SEP2676900CE",
}
LTPS = {("YESBANK", "NSE"): 21.35, ("SENSEX03SEP2676900CE", "BFO"): 60.6}


@pytest.fixture
def quote_batches(monkeypatch):
    """Stub the two external edges; symbol resolution runs for real."""
    batches = []

    class FakeBrokerData:
        def __init__(self, auth_token):
            pass

        def get_multiquotes(self, symbols):
            batches.append([(s["symbol"], s["exchange"]) for s in symbols])
            return [
                {
                    "symbol": s["symbol"],
                    "exchange": s["exchange"],
                    "data": {"ltp": LTPS[(s["symbol"], s["exchange"])]},
                }
                for s in symbols
            ]

    monkeypatch.setattr(kotak_data, "BrokerData", FakeBrokerData)
    monkeypatch.setattr(order_api, "get_api_response", lambda *a, **k: copy.deepcopy(RAW_POSITIONS))
    monkeypatch.setattr(
        order_mapping,
        "get_symbol",
        lambda token, exchange: TOKEN_TO_SYMBOL.get((str(token), exchange)),
    )
    monkeypatch.setattr(order_mapping, "get_oa_symbol", lambda symbol, exchange: None)
    return batches


def _positionbook():
    raw = order_api.get_positions(AUTH)
    return order_mapping.transform_positions_data(order_mapping.map_position_data(raw))


def test_duplicate_instruments_are_quoted_once(quote_batches):
    positions = _positionbook()

    assert len(quote_batches) == 1, "the whole book must go out in one batched call"
    batch = quote_batches[0]
    assert batch == list(dict.fromkeys(batch)), f"same instrument sent twice: {batch}"
    assert len(batch) == 2 and len(positions) == 3


def test_both_product_rows_of_a_duplicate_still_get_a_price(quote_batches):
    positions = _positionbook()

    assert [p["ltp"] for p in positions] == [21.35, 21.35, 60.6]
    assert [p["product"] for p in positions] == ["MIS", "NRML", "MIS"]


@pytest.mark.parametrize("payload", [["error"], "gateway timeout", None, 0])
def test_a_payload_that_is_not_an_object_is_rejected_by_name(monkeypatch, payload):
    """Loudly, and before the mapping layer turns it into a puzzle.

    Not normalized to an empty book on purpose: close_all_positions reads a
    response with no positions in it as a successful square-off, so standing in
    for a failed read would report closed positions the broker still holds.
    """
    monkeypatch.setattr(order_api, "get_api_response", lambda *a, **k: copy.deepcopy(payload))

    with pytest.raises(Exception, match="not an object"):
        order_api.get_positions(AUTH)


@pytest.mark.parametrize("payload", [["error"], "gateway timeout", None, 0])
def test_the_backfill_itself_never_raises(monkeypatch, payload):
    """The rejection above is get_positions'. _backfill_ltp stays best-effort."""
    order_api._backfill_ltp(payload, AUTH)


def test_a_quotes_outage_leaves_prices_at_zero(monkeypatch, quote_batches):
    class BoomBrokerData:
        def __init__(self, auth_token):
            raise Exception("simulated quotes outage")

    monkeypatch.setattr(kotak_data, "BrokerData", BoomBrokerData)

    assert [p["ltp"] for p in _positionbook()] == [0.0, 0.0, 0.0]
