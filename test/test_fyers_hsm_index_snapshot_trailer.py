"""An index snapshot must not swallow the snapshots after it in the same frame.

The HSM feed packs several snapshots into one data frame when symbols are
subscribed together (the adapter batches subscribes that arrive within
HSM_BATCH_DELAY_SEC). Every snapshot - scrip, depth and index - ends with the
same trailer: 2 bytes, multiplier (>H), precision (B), then exchange,
exchange_token and symbol as length-prefixed strings (see the official SDK,
fyers-apiv3 FyersWebsocket/data_ws.py). The index parser stopped after the
price fields, so the next snapshot was read from inside the trailer, logged as
"Unknown data type: 0" and dropped. That symbol's topic_id was never
registered, so all of its later updates were ignored: an option subscribed
together with NIFTY showed a frozen price until the feed reconnected.
"""

import struct

from broker.fyers.streaming.fyers_hsm_websocket import FyersHSMWebSocket


def _str(s):
    b = s.encode()
    return struct.pack("B", len(b)) + b


def _snapshot(topic_id, topic_name, values, multiplier, precision, exch, token, sym):
    body = struct.pack("B", 83) + struct.pack("H", topic_id) + _str(topic_name)
    body += struct.pack("B", len(values)) + b"".join(struct.pack(">i", v) for v in values)
    body += b"\x00\x00" + struct.pack(">H", multiplier) + struct.pack("B", precision)
    return body + _str(exch) + _str(token) + _str(sym)


def _frame(*snapshots):
    # 7 header bytes (type 6 at [2], message number), then the scrip count.
    header = b"\x00\x00\x06" + b"\x00\x00\x00\x01" + struct.pack("!H", len(snapshots))
    return bytearray(header + b"".join(snapshots))


def _ws():
    ws = FyersHSMWebSocket.__new__(FyersHSMWebSocket)
    ws.logger = __import__("logging").getLogger("test")
    ws.subscriptions, ws.scrips_data, ws.index_data, ws.depth_data = {}, {}, {}, {}
    ws.symbol_mappings = {}
    ws.received = []
    ws.on_message_callback = ws.received.append
    ws.disconnect = lambda: None   # built without __init__: nothing to tear down in __del__
    return ws


def test_option_after_index_in_same_frame_is_parsed():
    ws = _ws()
    index = _snapshot(1, "if|nse_cm|Nifty 50", [2245000, 2265000, 0, 2250000, 2270000, 2240000],
                      1, 2, "NSE", "26000", "NSE:NIFTY50-INDEX")
    option = _snapshot(2, "sf|nse_fo|51326", [19200] + [0] * 20,
                       1, 2, "NSE", "51326", "NSE:NIFTY26OCT22400CE")
    ws._parse_data_feed(_frame(index, option))

    assert ws.subscriptions == {1: "if|nse_cm|Nifty 50", 2: "sf|nse_fo|51326"}
    assert 2 in ws.scrips_data, "option snapshot after the index was dropped"
    assert ws.scrips_data[2]["ltp"] == 19200
    assert [d["type"] for d in ws.received] == ["if", "sf"]


def test_index_snapshot_reads_its_trailer():
    ws = _ws()
    ws._parse_data_feed(_frame(_snapshot(1, "if|nse_cm|Nifty 50", [2245000, 2265000], 1, 2,
                                         "NSE", "26000", "NSE:NIFTY50-INDEX")))
    d = ws.index_data[1]
    assert d["ltp"] == 2245000
    assert (d["multiplier"], d["precision"]) == (1, 2)
    assert d["exchange_token"] == "26000"


def test_several_indices_and_options_in_one_frame():
    ws = _ws()
    snaps = [
        _snapshot(1, "if|nse_cm|Nifty 50", [2245000], 1, 2, "NSE", "26000", "NSE:NIFTY50-INDEX"),
        _snapshot(2, "sf|nse_fo|1", [100] * 21, 1, 2, "NSE", "1", "NSE:A"),
        _snapshot(3, "if|nse_cm|Nifty Bank", [5000000], 1, 2,
                  "NSE", "26009", "NSE:NIFTYBANK-INDEX"),
        _snapshot(4, "sf|nse_fo|2", [200] * 21, 1, 2, "NSE", "2", "NSE:B"),
    ]
    ws._parse_data_feed(_frame(*snaps))
    assert set(ws.index_data) == {1, 3}
    assert set(ws.scrips_data) == {2, 4}
