"""Motilal's pooled feed resubscribes everything, whatever requests do meanwhile.

One MotilalWebSocket per auth token serves every quote and depth request. On a
(re)connect the reader thread resubscribes the scrips it knew about, and it
iterated ``subscribed_scrips`` live while request threads registered and
unregistered scrips on the same socket. The first concurrent change raised
"dictionary changed size during iteration" inside on_message, which swallowed
it, so every scrip after that point was never resubscribed and those requests
waited out their timeouts with no data.

The interleaving is forced: the resubscribe pauses inside its first
registration while a request registers a new scrip, then carries on.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from broker.motilal.api.motilal_websocket import MotilalWebSocket


def _client():
    ws = MotilalWebSocket("C1", "tok", "key")
    ws.is_connected = True
    ws.ws = MagicMock()
    for code in (101, 102, 103):
        ws.subscribed_scrips[f"NSE|CASH|{code}"] = {
            "exchange": "NSE",
            "exchange_type": "CASH",
            "scrip_code": code,
            "symbol": f"S{code}",
        }
    ws.subscribed_indices.add("NSE")
    return ws


def test_a_registration_during_resubscribe_does_not_stop_it():
    ws = _client()
    real_register = ws.register_scrip
    started = threading.Event()
    mutated = threading.Event()
    resubscribed: list[int] = []

    def paused_register(exchange, exchange_type, scrip_code, symbol=None):
        if not started.is_set():
            started.set()
            assert mutated.wait(5), "the request thread never registered"
        resubscribed.append(scrip_code)
        return real_register(exchange, exchange_type, scrip_code, symbol)

    ws.register_scrip = paused_register
    errors: list[BaseException] = []

    def reader():
        try:
            ws._resubscribe()
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    assert started.wait(5)
    real_register("NSE", "CASH", 104, "S104")  # a request thread, meanwhile
    mutated.set()
    thread.join(5)

    assert errors == [], errors
    assert sorted(resubscribed) == [101, 102, 103], "every known scrip is resubscribed"
    assert "NSE|CASH|104" in ws.subscribed_scrips
    assert "NSE" in ws.subscribed_indices


def test_an_unregistration_during_resubscribe_does_not_stop_it():
    ws = _client()
    real_register = ws.register_scrip
    started = threading.Event()
    mutated = threading.Event()
    resubscribed: list[int] = []

    def paused_register(exchange, exchange_type, scrip_code, symbol=None):
        if not started.is_set():
            started.set()
            assert mutated.wait(5)
        resubscribed.append(scrip_code)
        return real_register(exchange, exchange_type, scrip_code, symbol)

    ws.register_scrip = paused_register
    errors: list[BaseException] = []

    def reader():
        try:
            ws._resubscribe()
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    assert started.wait(5)
    ws.unregister_scrip("NSE", "CASH", 103)
    mutated.set()
    thread.join(5)

    assert errors == [], errors
    assert len(resubscribed) == 3
