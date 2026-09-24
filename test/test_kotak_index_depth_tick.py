"""Kotak index ticks reaching a Depth subscriber.

An index has no order book, so it satisfied neither the live-depth nor the
cached-depth branch of the mode-3 publish and fell through to `continue`: a
Depth subscription to NIFTY received nothing at all, ever. The option chain
subscribes its underlying in Depth mode alongside the strikes, so the spot
never got a tick and the page kept the zero it starts with -- NIFTY Spot
rendered from the REST poll and then read 0.00, while the same chain on
Zerodha showed a price because its adapter routes indices through a dedicated
index transform that publishes in full/Depth mode with no book.
"""

import threading
from unittest.mock import patch

import pytest


@pytest.fixture
def adapter():
    """A bare adapter with just the state the publish path touches.

    Constructed without __init__ so the test needs no broker session, no ZMQ
    socket and no websocket.
    """
    # Taken from websocket_proxy, which re-exports it, rather than from
    # broker.kotak.streaming.kotak_adapter directly: that package's __init__
    # imports the adapter while the adapter imports its base_adapter, so
    # reaching the module first deadlocks the cycle. One import, no ordering to
    # preserve and nothing for the import sorter to undo.
    from websocket_proxy import KotakWebSocketAdapter

    ad = KotakWebSocketAdapter.__new__(KotakWebSocketAdapter)
    ad.lock = threading.RLock()
    ad._lock = threading.RLock()
    ad._symbol_state = {}
    ad._ltp_cache = {}
    ad._depth_cache = {}
    ad._quote_cache = {}
    return ad


def _wire(adapter, exchange, symbol, token, modes):
    adapter._kotak_to_openalgo = {("nse_cm", token): (exchange, symbol)}
    adapter._symbol_modes = {("nse_cm", token): set(modes)}
    published = []
    adapter.publish_market_data = lambda topic, data: published.append((topic, data))
    return published


def test_an_index_reaches_a_depth_subscriber(adapter):
    published = _wire(adapter, "NSE_INDEX", "NIFTY", "26000", {3})

    adapter._on_data_received(
        {
            "tk": "26000",
            "e": "nse_cm",
            "ts": "Nifty 50",
            "ltp": 23446.8,
            "open": 23352.15,
            "high": 23466.9,
            "low": 23349.55,
            "prev_close": 23329.0,
        }
    )

    assert published, "a Depth subscriber received no tick for the index"
    topic, data = published[-1]
    assert topic == "NSE_INDEX_NIFTY_DEPTH"
    # The price is the whole point: a zero here is what put 0.00 on the page.
    assert data["ltp"] == pytest.approx(23446.8)
    # The ladder is genuinely empty -- an index has no book to report.
    assert data["depth"]["buy"] == []
    assert data["depth"]["sell"] == []
    assert data["totalbuyqty"] == 0
    assert data["totalsellqty"] == 0


def test_an_index_without_a_price_publishes_nothing(adapter):
    # Better no tick than a tick asserting a price of zero.
    published = _wire(adapter, "NSE_INDEX", "NIFTY", "26000", {3})

    adapter._on_data_received(
        {"tk": "26000", "e": "nse_cm", "ts": "Nifty 50", "ltp": 0, "prev_close": 23329.0}
    )

    assert published == []


def test_the_zero_book_snapshot_for_an_index_is_not_published(adapter):
    """The live shape, captured off the running proxy outside market hours.

    Subscribing NSE_INDEX:NIFTY in Depth mode returns a snapshot of five zero
    levels -- a real depth packet, so it satisfies has_depth_data -- while the
    index's price rides a separate packet that only arrives while the index is
    ticking. Published, the pair reads `ltp 0.0` over an empty ladder and
    overwrites the spot the option chain rendered from REST.
    """
    published = _wire(adapter, "NSE_INDEX", "NIFTY", "26000", {3})

    zero_level = {"price": 0.0, "quantity": 0, "orders": 0}
    adapter._on_data_received(
        {
            "tk": "26000",
            "e": "nse_cm",
            "ts": "Nifty 50",
            "bids": [dict(zero_level) for _ in range(5)],
            "asks": [dict(zero_level) for _ in range(5)],
            "totalbuyqty": 0,
            "totalsellqty": 0,
        }
    )

    assert published == [], "a zero-priced, empty-book index frame must not be sent"


def test_a_known_index_price_still_publishes_with_a_zero_book(adapter):
    # Once the index has ticked, the cached price makes the frame meaningful
    # again even though the book stays empty.
    published = _wire(adapter, "NSE_INDEX", "NIFTY", "26000", {3})
    adapter._on_data_received({"tk": "26000", "e": "nse_cm", "ts": "Nifty 50", "ltp": 23446.8})
    published.clear()

    zero_level = {"price": 0.0, "quantity": 0, "orders": 0}
    adapter._on_data_received(
        {
            "tk": "26000",
            "e": "nse_cm",
            "ts": "Nifty 50",
            "bids": [dict(zero_level) for _ in range(5)],
            "asks": [dict(zero_level) for _ in range(5)],
        }
    )

    assert published, "a cached index price should still reach the subscriber"
    assert published[-1][1]["ltp"] == pytest.approx(23446.8)


def test_an_index_tick_resolves_by_name_when_its_token_is_unknown(adapter):
    """The live shape, captured off Kotak: the packet names itself.

    Subscribing "nse_cm|Nifty 50" answers with tk 4247863880, a token of
    Kotak's own choosing rather than the master-contract 26000 the subscription
    was registered under. Keyed on the token alone the tick matches no
    subscription and is dropped, which is indistinguishable from the feed never
    sending one.
    """
    published = _wire(adapter, "NSE_INDEX", "NIFTY", "26000", {3})
    # Registered under the name as well, as the subscribe path does.
    adapter._kotak_to_openalgo[("nse_cm", "Nifty 50")] = ("NSE_INDEX", "NIFTY")
    adapter._symbol_modes[("nse_cm", "Nifty 50")] = adapter._symbol_modes[("nse_cm", "26000")]

    adapter._on_data_received(
        {
            "tk": "4247863880",
            "e": "nse_cm",
            "ts": "Nifty 50",
            "ltp": 23230.45,
            "open": 23221.8,
            "prev_close": 23446.8,
        }
    )

    assert published, "an index tick carrying an unknown token must still resolve"
    topic, data = published[-1]
    assert topic == "NSE_INDEX_NIFTY_DEPTH"
    assert data["ltp"] == pytest.approx(23230.45)


def test_a_tradeable_symbol_still_needs_a_real_book(adapter):
    # The new branch is gated on the index exchanges, so an equity with no depth
    # must still be skipped rather than publishing an empty ladder.
    published = _wire(adapter, "NSE", "RELIANCE", "2885", {3})

    adapter._on_data_received(
        {"tk": "2885", "e": "nse_cm", "ts": "RELIANCE-EQ", "ltp": 1245.6}
    )

    assert published == []


def test_a_tradeable_symbol_with_a_book_is_unaffected(adapter):
    published = _wire(adapter, "NSE", "RELIANCE", "2885", {3})

    adapter._on_data_received(
        {
            "tk": "2885",
            "e": "nse_cm",
            "ts": "RELIANCE-EQ",
            "ltp": 1245.6,
            "bids": [{"price": 1245.5, "quantity": 100}],
            "asks": [{"price": 1245.7, "quantity": 200}],
            "totalbuyqty": 500,
            "totalsellqty": 600,
        }
    )

    assert published, "an equity with a real book must still publish"
    _, data = published[-1]
    assert data["ltp"] == pytest.approx(1245.6)
    assert data["depth"]["buy"][0]["price"] == pytest.approx(1245.5)
