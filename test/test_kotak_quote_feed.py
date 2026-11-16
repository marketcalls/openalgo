"""Kotak quote fields, end to end: SFeed bytes in, OpenAlgo payload out.

A charting client (AmiBroker) read Kotak's quote window as blank or random
while the LTP chart worked. The proxy serves Depth topics to Quote and LTP
subscribers, and the Kotak payloads were thin: the SFeed client decoded
average price, last quantity, last trade time, percent change, book totals and
open interest and then dropped every one of them; ltt was the wall clock; the
depth totals read keys nothing set; a mini touch line zeroed open, high, low
and volume; and a depth packet's empty levels were refilled from the previous
book.

Every test here feeds a synthetic binary frame through the real client's
_handle_binary into the real adapter, with only publish_market_data captured,
so the decode, the normalization and the publish are all exercised together.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

# websocket_proxy first: its __init__ imports every broker adapter, and the
# Kotak streaming package imports back into it.
import websocket_proxy  # noqa: F401
from broker.kotak.streaming import sfeed_protocol as sf
from broker.kotak.streaming.sfeed_websocket import KotakSFeedWebSocket

NSE_CM = 1
TOKEN = 11536
LAST_TRADE_TIME = 1700000001  # Unix seconds on the wire


def _header(length, code, level, exchange_id=NSE_CM):
    return sf._HEADER.pack(length, code, exchange_id, level, 0, 0, 0)


def market_picture(
    level=sf.LEVEL_TOUCH_LINE,
    token=TOKEN,
    ltp=213500,
    open_price=210000,
    high=215000,
    low=209000,
    close=211000,
    volume=1500000,
    last_trade_time=LAST_TRADE_TIME,
    total_buy=900,
    total_sell=800,
    buy_rows=((100, 213400, 3),),
    sell_rows=((150, 213600, 4),),
):
    body = sf._MP_BODY.pack(
        token,
        total_buy,
        total_sell,
        volume,
        last_trade_time,
        last_trade_time,  # last_update_time
        open_price,
        close,
        high,
        low,
        ltp,
        50,  # last_trade_qty
        212000,  # avg_trade_price -> 2120.00
        0,  # indicative_close
        len(buy_rows),
        len(sell_rows),
        0,  # trading_status
        150,  # net_chg_percent -> 1.50
        4200,  # open_interest
        99999.0,  # total_traded_value
        2500,  # net_chg
        230000,
        190000,
        240000,
        180000,
        1,
        2,
        1,
    )
    rows = b"".join(sf._DEPTH_ROW.pack(q, p, o) for q, p, o in (*buy_rows, *sell_rows))
    length = sf.HEADER_SIZE + len(body) + len(rows)
    return _header(length, sf.MSG_MARKET_PICTURE, level) + body + rows


def mini(token=TOKEN, ltp=214000, last_trade_time=LAST_TRADE_TIME + 5):
    body = sf._MINI_BODY.pack(token, last_trade_time, ltp, 25, 211000, 140, 3000, 1, 2, 1)
    return _header(sf.HEADER_SIZE + len(body), 0, sf.LEVEL_MINI_TOUCH_LINE) + body


def index_packet(name=b"Nifty 50", token=4247863880, value=2135000):
    body = sf._INDEX_BODY.pack(
        token, 2100000, 2110000, 2150000, 2090000, value, LAST_TRADE_TIME,
        2400000, 1800000, 150, 0.0, 2, 100, name,
    )  # fmt: skip
    return _header(sf.HEADER_SIZE + len(body), sf.MSG_INDEX, 0) + body


@pytest.fixture
def feed():
    """A real SFeed client wired to a bare adapter whose publishes are captured."""
    from websocket_proxy import KotakWebSocketAdapter

    ad = KotakWebSocketAdapter.__new__(KotakWebSocketAdapter)
    ad.lock = threading.RLock()
    ad._lock = threading.RLock()
    ad._symbol_state = {}
    ad._ltp_cache = {}
    ad._depth_cache = {}
    ad._quote_cache = {}
    ad._depth_poll_state = {}
    ad._kotak_to_openalgo = {}
    ad._symbol_modes = {}
    ad.subscriptions = {}
    ad._enqueued = []
    ad._enqueue_subscription = lambda ex, tok, sub_type, channelnum="1": ad._enqueued.append(
        (ex, tok, sub_type)
    )
    ad.published = []
    ad.publish_market_data = lambda topic, data: ad.published.append((topic, data))

    client = KotakSFeedWebSocket({"sid": "sid"}, ws_url="wss://sfeed.example/apifeed", ucc="U")
    client._dividers = {NSE_CM: 100}
    client._is_authenticated = True
    client._handle_subscribe_ack({"trading_symbols": {f"nse_cm|{TOKEN}": "RELIANCE-EQ"}})
    client.set_callbacks(on_quote=ad._on_data_received, on_depth=ad._on_data_received)
    ad._ws_client = client
    ad.client = client
    return ad


def _map(ad, modes, exchange="NSE", symbol="RELIANCE", token=str(TOKEN)):
    ad._kotak_to_openalgo[("nse_cm", token)] = (exchange, symbol)
    ad._symbol_modes[("nse_cm", token)] = set(modes)


def _last(ad, suffix):
    matching = [data for topic, data in ad.published if topic.endswith(suffix)]
    assert matching, f"nothing published on a {suffix} topic: {ad.published}"
    return matching[-1]


# --- defect 1: decoded quote fields were dropped ------------------------------


def test_a_quote_carries_every_field_the_packet_decoded(feed):
    _map(feed, {2})
    feed.client._handle_binary(market_picture())

    q = _last(feed, "_QUOTE")
    assert q["ltp"] == 2135.0
    assert (q["open"], q["high"], q["low"], q["close"]) == (2100.0, 2150.0, 2090.0, 2110.0)
    assert q["volume"] == 1500000
    assert q["average_price"] == pytest.approx(2120.0)
    assert q["last_quantity"] == 50
    assert q["percent_change"] == pytest.approx(1.5)
    assert q["total_buy_quantity"] == 900
    assert q["total_sell_quantity"] == 800
    assert q["oi"] == 4200


# --- defect 2: ltt was the wall clock -----------------------------------------


@pytest.mark.parametrize("mode,suffix", [(1, "_LTP"), (2, "_QUOTE"), (3, "_DEPTH")])
def test_ltt_is_the_exchange_last_trade_time_in_milliseconds(feed, mode, suffix):
    _map(feed, {mode})
    level = sf.LEVEL_DEPTH if mode == 3 else sf.LEVEL_TOUCH_LINE
    feed.client._handle_binary(market_picture(level=level))

    data = _last(feed, suffix)
    assert data["ltt"] == LAST_TRADE_TIME * 1000


def test_no_trade_yet_publishes_no_trade_time_rather_than_now(feed):
    _map(feed, {1, 2})
    feed.client._handle_binary(market_picture(last_trade_time=0))

    assert "ltt" not in _last(feed, "_LTP")
    quote = _last(feed, "_QUOTE")
    assert "ltt" not in quote
    assert "last_trade_time" not in quote


# --- defect 3: depth totals were always 0 -------------------------------------


def test_depth_publishes_its_book_totals_and_every_quote_field(feed):
    _map(feed, {3})
    feed.client._handle_binary(
        market_picture(level=sf.LEVEL_DEPTH, total_buy=12345, total_sell=6789)
    )

    d = _last(feed, "_DEPTH")
    assert d["totalbuyqty"] == 12345
    assert d["totalsellqty"] == 6789
    assert d["total_buy_quantity"] == 12345
    assert d["total_sell_quantity"] == 6789
    # The proxy hands this frame to Quote subscribers too.
    assert d["open"] == 2100.0
    assert d["close"] == 2110.0
    assert d["volume"] == 1500000
    assert d["average_price"] == pytest.approx(2120.0)
    assert d["last_quantity"] == 50
    assert d["oi"] == 4200
    assert d["depth"]["buy"][0] == {"price": 2134.0, "quantity": 100, "orders": 3}


# --- defect 4: the mini touch line zeroed OHLC and volume ---------------------


def test_a_mini_tick_keeps_the_last_known_ohlc_and_volume(feed):
    _map(feed, {2})
    feed.client._handle_binary(market_picture())
    feed.client._handle_binary(mini(ltp=214000))

    q = _last(feed, "_QUOTE")
    assert q["ltp"] == 2140.0, "the mini tick's own price is published"
    assert (q["open"], q["high"], q["low"]) == (2100.0, 2150.0, 2090.0)
    assert q["volume"] == 1500000
    assert q["last_quantity"] == 25, "a field the mini tick carries replaces the old one"
    assert q["ltt"] == (LAST_TRADE_TIME + 5) * 1000


# --- defect 5: empty depth levels were refilled from the previous book --------


def test_a_depth_packet_replaces_the_whole_book(feed):
    _map(feed, {3})
    feed.client._handle_binary(
        market_picture(
            level=sf.LEVEL_DEPTH,
            buy_rows=((100, 213400, 3), (200, 213300, 5)),
            sell_rows=((150, 213600, 4), (250, 213700, 6)),
        )
    )
    feed.client._handle_binary(
        market_picture(
            level=sf.LEVEL_DEPTH,
            buy_rows=((90, 213500, 2),),
            sell_rows=((80, 213550, 1),),
        )
    )

    d = _last(feed, "_DEPTH")
    assert d["depth"]["buy"][0]["price"] == 2135.0
    assert d["depth"]["buy"][1] == {"price": 0.0, "quantity": 0, "orders": 0}
    assert d["depth"]["sell"][1] == {"price": 0.0, "quantity": 0, "orders": 0}

    polled = feed.get_depth()["NSE"]["RELIANCE"]
    assert polled["buyBook"]["2"] == {"price": "0.0", "qty": "0", "orders": "0"}


# --- defect 6: BCD subscribed under a segment name the feed never sends -------


def test_bcd_maps_to_the_segment_the_feed_reports():
    from broker.kotak.streaming.kotak_mapping import get_kotak_exchange

    assert get_kotak_exchange("BCD") == "bse_cd"
    assert get_kotak_exchange("BCD") in sf.EXCHANGE_NAME_TO_ID


# --- defect 7: an "hs" data centre logged a fallback and then used HSM --------


def test_an_hs_data_centre_really_falls_back_to_sfeed():
    from broker.kotak.streaming import kotak_feed_config as cfg

    response = MagicMock()
    response.json.return_value = {
        "data": {
            "configs": {
                "E99_broadcast_source": "hs",
                "E99_hs_broadcast_endpoint": "mlhsm.kotaksecurities.com",
            }
        }
    }
    http = MagicMock()
    http.get.return_value = response
    with patch.object(cfg, "get_httpx_client", return_value=http):
        result = cfg.fetch_feed_config("E99")

    assert result["source"] != cfg.SOURCE_HSM
    assert result["market_data_url"] == cfg.DEFAULT_SFEED_URL


# --- index aliases shared by two OpenAlgo symbols -----------------------------


def _subscribe_index(ad, symbol, token):
    with (
        patch("database.token_db.get_token", return_value=token),
        patch(
            "broker.kotak.streaming.kotak_mapping.get_kotak_exchange",
            return_value="nse_cm",
        ),
    ):
        ad.subscribe_quote("NSE_INDEX", symbol, 2)


def _unsubscribe_index(ad, symbol, token):
    with (
        patch("database.token_db.get_token", return_value=token),
        patch(
            "broker.kotak.streaming.kotak_mapping.get_kotak_exchange",
            return_value="nse_cm",
        ),
    ):
        ad.unsubscribe_quote("NSE_INDEX", symbol, 2)


def test_two_symbols_on_one_index_name_both_receive_the_tick(feed):
    _subscribe_index(feed, "NIFTY", "26000")
    _subscribe_index(feed, "NIFTY50", "26999")

    feed.client._handle_binary(index_packet())

    topics = {topic for topic, _ in feed.published}
    assert topics == {"NSE_INDEX_NIFTY_QUOTE", "NSE_INDEX_NIFTY50_QUOTE"}
    for _, data in feed.published:
        assert data["ltp"] == 21350.0
        assert data["ltt"] == LAST_TRADE_TIME * 1000


def test_the_index_feed_stays_while_another_symbol_still_uses_its_name(feed):
    _subscribe_index(feed, "NIFTY", "26000")
    _subscribe_index(feed, "NIFTY50", "26999")
    feed._enqueued.clear()

    _unsubscribe_index(feed, "NIFTY", "26000")
    assert feed._enqueued == [], "NIFTY50 still needs the Nifty 50 feed"

    feed.client._handle_binary(index_packet())
    assert {topic for topic, _ in feed.published} == {"NSE_INDEX_NIFTY50_QUOTE"}

    _unsubscribe_index(feed, "NIFTY50", "26999")
    assert feed._enqueued == [("nse_cm", "Nifty 50", "ifu")]


# --- review follow-ups ---------------------------------------------------------


def test_a_first_mini_tick_publishes_no_zero_ohlc_or_volume(feed):
    """A mini touch line with no earlier state carries a price and nothing
    else; the fields it lacks are left out instead of going out as 0."""
    _map(feed, {2, 3})
    feed.client._handle_binary(mini(ltp=214000))

    q = _last(feed, "_QUOTE")
    assert q["ltp"] == 2140.0
    for key in ("open", "high", "low", "volume"):
        assert key not in q, key
    assert not [t for t, d in feed.published if any(d.get(k) == 0 for k in ("open", "volume"))]


def test_disconnect_forgets_the_index_aliases(feed):
    _subscribe_index(feed, "NIFTY", "26000")
    assert feed._alias_registry()

    feed._ws_client = MagicMock()
    feed._reconnect_timer = None
    feed._batch_timer = None
    feed._subscription_queue = []
    feed.cleanup_zmq = lambda: None
    feed.disconnect()
    assert feed._alias_registry() == {}

    # A late index packet no longer reaches the unsubscribed symbol.
    feed.published.clear()
    feed.client._handle_binary(index_packet())
    assert feed.published == []
