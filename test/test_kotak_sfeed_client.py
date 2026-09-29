"""Kotak SFeed client bookkeeping and normalization.

The two growth paths here were found by an FD/memory audit of this file, not by
a failure: OpenAlgo runs as a single Gunicorn worker that never restarts, so
anything that only ever grows accumulates until the host runs out of memory.
Both were measured before and after the fix, and both are pinned below.

The normalization tests exist because the SFeed client is a drop-in for the
legacy HSM one - kotak_adapter.py and everything past it were not changed, so
this client has to emit the same dict shape HSM did, under HSM's field names.
"""

import pytest

# websocket_proxy first: its __init__ imports every broker adapter, and
# kotak_adapter imports back into it. Reaching the Kotak streaming package from
# a cold interpreter hits that pre-existing cycle.
import websocket_proxy  # noqa: F401
from broker.kotak.streaming.sfeed_websocket import MAX_PENDING_FRAMES, KotakSFeedWebSocket


@pytest.fixture
def client():
    return KotakSFeedWebSocket({"sid": "sid"}, ws_url="wss://sfeed.example/apifeed", ucc="UCC1")


def ack(client, **symbols):
    client._handle_subscribe_ack({"trading_symbols": symbols})


# --- bookkeeping that must not grow forever -----------------------------------


def test_unsubscribing_releases_the_trading_symbol_too(client):
    """This map exists only because SFeed omits the symbol from the tick.

    Measured before the fix: 1000 subscribes then 1000 unsubscribes left all
    1000 entries behind, while _subscriptions correctly emptied. The key space
    is every instrument subscribed for the life of the process.
    """
    for i in range(1000):
        client.subscribe_batch([("nse_cm", str(i))], sub_type="mws")
        ack(client, **{f"nse_cm|{i}": f"SYM{i}"})
    assert len(client._symbols) == 1000

    client.unsubscribe_batch([("nse_cm", str(i)) for i in range(1000)], sub_type="mwu")

    assert client._symbols == {}
    assert client._subscriptions == set()


def test_a_symbol_survives_while_another_intent_still_holds_the_token(client):
    """Quote and depth subscribe separately and share one symbol entry.

    Dropping the symbol on the first unsubscribe would blank ts on the feed
    that is still running - which is why the release checks whether anything
    still holds the token rather than just deleting it.
    """
    client.subscribe_batch([("nse_cm", "11536")], sub_type="mws")
    client.subscribe_batch([("nse_cm", "11536")], sub_type="dps")
    ack(client, **{"nse_cm|11536": "RELIANCE"})

    client.unsubscribe_batch([("nse_cm", "11536")], sub_type="mwu")
    assert client._symbols == {"nse_cm|11536": "RELIANCE"}, "depth still needs it"

    client.unsubscribe_batch([("nse_cm", "11536")], sub_type="dpu")
    assert client._symbols == {}


def test_a_dropped_connection_discards_the_frames_queued_against_it(client):
    """During an outage the adapter replays its subscriptions on every
    reconnect attempt. Measured before the fix: 50 attempts left 50 queued
    frames, growing without bound for as long as the broker stayed down.

    Discarding is also the correct behaviour, not only the bounded one - the
    adapter resubscribes from its own record, so a flush after a later auth
    would re-send subscriptions that were already sent again.
    """
    for _ in range(50):
        client._handle_close(None, 1006, "outage")
        client.subscribe_batch([("nse_cm", "11536")], sub_type="mws")

    assert len(client._pending_frames) == 1


def test_the_pending_queue_is_capped_even_with_no_disconnect(client):
    """Backstop for a socket that never opens at all, so no close ever clears
    the queue. Oldest is dropped; the adapter's replay makes that recoverable."""
    for i in range(MAX_PENDING_FRAMES + 500):
        client.subscribe_batch([("nse_cm", str(i))], sub_type="mws")

    assert len(client._pending_frames) == MAX_PENDING_FRAMES


def test_the_subscription_cap_rejects_the_whole_request(client):
    """Kotak rejects an over-cap subscribe server-side and sends nothing, so
    partially applying it locally would leave the two out of step."""
    client.subscribe_batch([("nse_cm", str(i)) for i in range(2999)], sub_type="mws")
    before = len(client._subscriptions)

    client.subscribe_batch([("nse_cm", str(i)) for i in range(5000, 5100)], sub_type="mws")

    assert len(client._subscriptions) == before


# --- normalization: the contract kotak_adapter.py already reads ---------------


def scrip(level, **overrides):
    base = {
        "type": "scrip",
        "exchange_segment": "nse_cm",
        "instrument_token": "11536",
        "level": level,
        "last_traded_price": 2135.0,
        "open_price": 2100.0,
        "high_price": 2150.0,
        "low_price": 2090.0,
        "close_price": 2110.0,
        "volume_traded_today": 1500000,
        "buy": [{"price": 2134.0, "quantity": 100, "orders": 3}],
        "sell": [{"price": 2136.0, "quantity": 150, "orders": 4}],
    }
    base.update(overrides)
    return base


def test_a_touch_line_tick_carries_hsm_field_names(client):
    """The adapter reads tk/e/ts/ltp/open/high/low/prev_close/volume/bid/ask.
    Renaming any of these to SFeed's own names silently breaks it."""
    ack(client, **{"nse_cm|11536": "RELIANCE"})

    quote = client._to_quote(scrip(4))

    assert quote == {
        "bid": 2134.0,
        "ask": 2136.0,
        "open": 2100.0,
        "high": 2150.0,
        "low": 2090.0,
        "ltp": 2135.0,
        "prev_close": 2110.0,
        "volume": 1500000,
        "ts": "RELIANCE",
        "tk": "11536",
        "e": "nse_cm",
    }


def test_depth_is_padded_to_the_five_levels_the_adapter_merges(client):
    """The adapter merges bids/asks level by level over range(5)."""
    depth = client._to_depth(scrip(8))

    assert len(depth["bids"]) == 5
    assert len(depth["asks"]) == 5
    assert depth["bids"][0] == {"price": 2134.0, "quantity": 100, "orders": 3}
    assert depth["bids"][4] == {"price": 0.0, "quantity": 0, "orders": 0}


def test_a_symbol_not_yet_acknowledged_reads_as_empty_not_none(client):
    """The adapter does `if value:` on ts, so "" means "no update" and merges
    the last known name. None would too, but "" matches what HSM sent."""
    assert client._to_quote(scrip(4))["ts"] == ""


def test_a_mini_tick_reports_absent_fields_as_zero(client):
    """Mini touch line has no OHLC or book. Zero is how this contract says
    "unchanged" - the adapter skips zero price fields when merging."""
    lite = client._to_quote_lite(
        {
            "type": "scrip_lite",
            "exchange_segment": "nse_cm",
            "instrument_token": "11536",
            "last_traded_price": 2135.0,
            "close_price": 2110.0,
        }
    )

    assert lite["ltp"] == 2135.0
    assert lite["open"] == 0.0
    assert lite["bid"] == 0.0


def test_depth_ticks_route_to_the_depth_callback_and_touch_line_to_quote(client):
    seen = {"quote": 0, "depth": 0}
    client.set_callbacks(
        on_quote=lambda q: seen.__setitem__("quote", seen["quote"] + 1),
        on_depth=lambda d: seen.__setitem__("depth", seen["depth"] + 1),
    )

    client._dispatch(scrip(4))
    client._dispatch(scrip(8))
    client._dispatch(scrip(16))

    assert seen == {"quote": 1, "depth": 2}


def test_binary_frames_are_dropped_until_the_dividers_arrive(client):
    """Every price is scaled by a divider that only arrives in the auth
    response. Decoding before then would apply the fallback 100 to every
    exchange - right for some, wrong for others. A wrong price beats no price
    for nobody."""
    seen = []
    client.set_callbacks(on_quote=seen.append)

    client._handle_binary(b"\x00" * 200)

    assert seen == []


# --- batching ----------------------------------------------------------------


def test_sfeed_sends_one_frame_where_hsm_needs_ten():
    """The adapter batches subscriptions behind a debounce timer and then
    chunks them by the client's per-frame limit - the same shape Zerodha's
    adapter uses. That limit is a protocol fact, not a policy: HSI caps a
    frame at MAX_SCRIPS, while SFeed takes the whole comma-separated list in
    one frame and Kotak's own client never chunks it.

    Before this was read off the client, SFeed inherited HSM's 100 and sent
    thirty frames for a full subscription set where one would do.
    """
    from broker.kotak.streaming.kotak_websocket import KotakWebSocket

    hsm = KotakWebSocket({"auth_token": "t", "sid": "s"})
    sfeed = KotakSFeedWebSocket({"sid": "s"}, ws_url="wss://x", ucc="U")

    def frames(client, n):
        return -(-n // client.MAX_BATCH_SIZE)

    assert frames(hsm, 1000) == 10
    assert frames(sfeed, 1000) == 1


def test_a_batched_subscribe_puts_every_scrip_in_one_inputtoken(client):
    """One frame, comma-separated, in the exchange|token form SFeed expects."""
    sent = []
    client._send = sent.append

    client.subscribe_batch([("nse_cm", "11536"), ("nse_fo", "12345")], sub_type="mws")

    assert len(sent) == 1
    assert sent[0]["event"] == "subscribeScrips"
    assert sent[0]["inputtoken"] == "nse_cm|11536,nse_fo|12345"
    assert sent[0]["ack_symbol"] is True


def test_an_unsubscribe_frame_carries_no_ack_request(client):
    """ack_symbol asks for the token to symbol map, which an unsubscribe has
    no use for. Kotak's client omits it there too."""
    sent = []
    client._send = sent.append

    client.unsubscribe_batch([("nse_cm", "11536")], sub_type="mwu")

    assert "ack_symbol" not in sent[0]
