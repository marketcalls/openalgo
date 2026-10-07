"""Kotak index symbols must be subscribed to the index feed.

SFeed carries three independent subscriptions -- subscribeScrips, subscribeDepth
and subscribeIndices -- and an index is only delivered by the third, as message
7207. `12-neo-websocket.md` documents it as its own subscription taking a name
rather than a master-contract token: `nse_cm|Nifty 50`, not `nse_cm|26000`.

The adapter declared "ifs" in _SCRIP_OPS and never sent it, subscribing indices
as ordinary scrips instead. Kotak accepts that and then never ticks, so the
option chain's spot rendered from the REST poll and never updated, while the
depth feed answered with five zero levels and an ltp of 0.0.
"""

import threading
from unittest.mock import patch

import pytest


@pytest.fixture
def adapter():
    """A bare adapter with only the state the subscribe path touches."""
    from websocket_proxy import KotakWebSocketAdapter

    ad = KotakWebSocketAdapter.__new__(KotakWebSocketAdapter)
    ad.lock = threading.RLock()
    ad._lock = threading.RLock()
    ad._kotak_to_openalgo = {}
    ad._symbol_modes = {}
    ad._ws_client = object()          # merely non-None; nothing is sent here
    ad.subscriptions = {}
    ad.connected = True
    ad._enqueued = []
    ad._enqueue_subscription = lambda ex, tok, sub_type, channelnum="1": ad._enqueued.append(
        (ex, tok, sub_type)
    )
    return ad


def _subscribe(adapter, method, exchange, symbol, token, mode):
    with (
        patch("database.token_db.get_token", return_value=token),
        patch(
            "broker.kotak.streaming.kotak_mapping.get_kotak_exchange",
            return_value="nse_cm",
        ),
    ):
        getattr(adapter, method)(exchange, symbol, mode)
    return adapter._enqueued


@pytest.mark.parametrize("method,mode", [("subscribe_quote", 2), ("subscribe_depth", 3)])
def test_an_index_goes_to_the_index_feed_by_name(adapter, method, mode):
    sent = _subscribe(adapter, method, "NSE_INDEX", "NIFTY", "26000", mode)

    assert sent == [("nse_cm", "Nifty 50", "ifs")], (
        "an index must be subscribed with subscribeIndices, by Kotak's name for it"
    )


@pytest.mark.parametrize("method,mode", [("subscribe_quote", 2), ("subscribe_depth", 3)])
def test_a_tradeable_symbol_is_unchanged(adapter, method, mode):
    sent = _subscribe(adapter, method, "NSE", "RELIANCE", "2885", mode)

    expected = "mws" if method == "subscribe_quote" else "dps"
    assert sent == [("nse_cm", "2885", expected)]


def test_a_tick_arriving_under_either_identity_resolves(adapter):
    # An index packet carries both a name and a token of Kotak's choosing, and
    # a tick that matches no subscription is indistinguishable from no tick.
    _subscribe(adapter, "subscribe_quote", "NSE_INDEX", "NIFTY", "26000", 2)

    assert adapter._kotak_to_openalgo[("nse_cm", "Nifty 50")] == ("NSE_INDEX", "NIFTY")
    assert adapter._kotak_to_openalgo[("nse_cm", "26000")] == ("NSE_INDEX", "NIFTY")


def test_every_alias_shares_one_mode_set(adapter):
    # Otherwise a tick arriving under the name publishes in whichever modes the
    # token happened to hold, which is none of them.
    _subscribe(adapter, "subscribe_quote", "NSE_INDEX", "NIFTY", "26000", 2)
    _subscribe(adapter, "subscribe_depth", "NSE_INDEX", "NIFTY", "26000", 3)

    by_name = adapter._symbol_modes[("nse_cm", "Nifty 50")]
    by_token = adapter._symbol_modes[("nse_cm", "26000")]
    assert by_name is by_token
    assert by_name == {2, 3}


def test_only_one_spelling_is_sent_for_a_multi_candidate_index(adapter):
    # MIDCPNIFTY has four known spellings. Kotak answers a subscribe frame as a
    # whole, so sending the speculative ones would risk the indices batched
    # alongside it; the rest are registered inbound instead.
    sent = _subscribe(adapter, "subscribe_quote", "NSE_INDEX", "MIDCPNIFTY", "26074", 2)

    assert len(sent) == 1
    assert sent[0][2] == "ifs"
    from broker.kotak.streaming.kotak_adapter import index_name_candidates

    for name in index_name_candidates("MIDCPNIFTY"):
        assert adapter._kotak_to_openalgo[("nse_cm", name)] == ("NSE_INDEX", "MIDCPNIFTY")


def test_the_rest_map_and_the_feed_map_have_not_drifted():
    """The two copies of Kotak's index names must stay identical.

    The quotes endpoint and the index feed address an index by the same names,
    and the streaming module keeps its own copy because it cannot import
    broker.kotak.api.data -- that module pulls in httpx, the token database and
    the master contract. Nothing but this test holds them together.

    A drift is silent and reads as a broker fault: the REST spot resolves and
    renders while the feed subscribes a name Kotak does not know, so the price
    appears once on load and then never ticks.
    """
    from broker.kotak.api.data import BrokerData
    from broker.kotak.streaming.kotak_adapter import _INDEX_NAMES, index_name_candidates

    rest = BrokerData.__new__(BrokerData)

    # Every key the feed knows resolves identically through the REST client...
    for symbol in _INDEX_NAMES:
        assert rest._get_index_symbol_candidates(symbol) == index_name_candidates(symbol), (
            f"{symbol} resolves differently in the two copies"
        )

    # ...and the REST client knows no index the feed is missing, which would
    # leave that index quoting but never streaming.
    for symbol in ("NIFTY", "NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                   "NIFTYNXT50", "INDIAVIX", "SENSEX", "BANKEX"):
        assert symbol in _INDEX_NAMES, f"{symbol} is quoted by REST but unknown to the feed"

    # An unknown symbol falls back to itself in both.
    assert rest._get_index_symbol_candidates("NOTANINDEX") == index_name_candidates("NOTANINDEX")
