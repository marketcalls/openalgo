"""Unbounded-growth guards for the AliceBlue plugin.

Two module/instance structures grew without limit in a worker that never
restarts:

* order_api._symbol_locks - a plain dict keyed symbol:exchange:product, one
  threading.Lock per symbol ever smart-ordered, never removed.
* AliceBlueWebSocket.last_quotes / last_depth - keyed "exchange:token" while
  unsubscribe only cleared self.subscriptions, keyed "exchange|token". Every
  option-chain sweep left roughly 80 quote entries behind for good, and now
  that the connection is pooled and long-lived they accumulated all session.
"""

import gc
import os
import sys
import threading
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

order_api = pytest.importorskip("broker.aliceblue.api.order_api")
ws_mod = pytest.importorskip("broker.aliceblue.api.alicebluewebsocket")


# --- _symbol_locks ----------------------------------------------------------


def test_idle_symbol_locks_do_not_accumulate():
    """A lock per symbol ever ordered is a leak; per symbol in flight is not."""
    for i in range(500):
        lock = order_api._get_symbol_lock(f"SYM{i}", "NSE", "MIS")
        with lock:
            pass
        del lock

    gc.collect()

    leaked = [k for k in order_api._symbol_locks if k.startswith("SYM")]
    assert not leaked, f"{len(leaked)} idle symbol locks retained"


def test_a_held_symbol_lock_is_shared_not_duplicated():
    """The property a size-capped registry would silently break.

    Two callers must get the SAME lock, or both run the same symbol's smart
    order concurrently against a stale position book and size the position
    twice.
    """
    held = order_api._get_symbol_lock("RELIANCE", "NSE", "MIS")
    held.acquire()
    try:
        again = order_api._get_symbol_lock("RELIANCE", "NSE", "MIS")
        assert again is held, "a concurrent caller got a different lock"
        assert again.locked(), "the serialization guard would not have fired"
    finally:
        held.release()


def test_a_held_symbol_lock_survives_collection():
    held = order_api._get_symbol_lock("INFY", "NSE", "NRML")
    held.acquire()
    try:
        gc.collect()
        assert order_api._get_symbol_lock("INFY", "NSE", "NRML") is held
    finally:
        held.release()


def test_distinct_products_get_distinct_locks():
    """MIS and NRML on the same symbol are independent positions."""
    a = order_api._get_symbol_lock("SBIN", "NSE", "MIS")
    b = order_api._get_symbol_lock("SBIN", "NSE", "NRML")
    try:
        assert a is not b
    finally:
        del a, b


# --- last_quotes / last_depth ----------------------------------------------


def _socket():
    ws = ws_mod.AliceBlueWebSocket.__new__(ws_mod.AliceBlueWebSocket)
    ws.subscriptions = {}
    ws.subscribed_tokens = set()
    ws.last_quotes = {}
    ws.last_depth = {}
    ws.ws = MagicMock()
    ws.lock = threading.Lock()
    ws.is_connected = True  # unsubscribe short-circuits on a dead socket
    return ws


def _instrument(exchange, token):
    return MagicMock(exchange=exchange, token=token)


def test_unsubscribe_clears_the_cached_quote_and_depth():
    ws = _socket()
    instruments = [_instrument("NSE", str(t)) for t in range(2885, 2965)]  # 80, an option chain

    for inst in instruments:
        ws.subscriptions[f"{inst.exchange}|{inst.token}"] = inst
        ws.subscribed_tokens.add(f"{inst.exchange}|{inst.token}")
        ws.last_quotes[f"{inst.exchange}:{inst.token}"] = {"ltp": 1.0}
        ws.last_depth[f"{inst.exchange}:{inst.token}"] = {"buy": []}

    ws.unsubscribe(instruments)

    assert ws.subscriptions == {}
    assert ws.last_quotes == {}, f"{len(ws.last_quotes)} quote entries leaked after unsubscribe"
    assert ws.last_depth == {}, f"{len(ws.last_depth)} depth entries leaked after unsubscribe"


def test_repeated_sweeps_do_not_accumulate():
    """An option chain re-fetched all session must not grow the cache."""
    ws = _socket()
    for _ in range(50):
        instruments = [_instrument("NFO", str(t)) for t in range(35000, 35080)]
        for inst in instruments:
            ws.subscriptions[f"{inst.exchange}|{inst.token}"] = inst
            ws.last_quotes[f"{inst.exchange}:{inst.token}"] = {"ltp": 1.0}
        ws.unsubscribe(instruments)

    assert len(ws.last_quotes) == 0, (
        f"cache grew to {len(ws.last_quotes)} entries over 50 option-chain sweeps"
    )


def test_unsubscribe_leaves_other_instruments_cached():
    """Pruning must be surgical - a live subscription keeps its quote."""
    ws = _socket()
    keep, drop = _instrument("NSE", "1594"), _instrument("NSE", "2885")
    for inst in (keep, drop):
        ws.subscriptions[f"{inst.exchange}|{inst.token}"] = inst
        ws.last_quotes[f"{inst.exchange}:{inst.token}"] = {"ltp": 1.0}

    ws.unsubscribe([drop])

    assert "NSE:1594" in ws.last_quotes
    assert "NSE:2885" not in ws.last_quotes
