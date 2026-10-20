"""The smart-order position book cache never keeps a book from before a fill.

Every brokers_a plugin caches its position book for a second so a burst of
smart orders does not fetch it once per order, and drops the entry after each
order so the next one sees the fill. The copies each broker carried stored
whatever their fetch returned, even when an order was placed, and the cache
invalidated, while that fetch was still in flight. The next smart order on the
same symbol within the second then sized itself against the position from
before the fill: a repeated TradingView alert sent the same delta again, or an
exit found "Position size matches" and was skipped.

The window exists under eventlet too (the fetch yields), so the fix applies in
every mode; gthread only makes it wider. Each case below drives the exact
interleaving deterministically: the fetch blocks on an Event while the
invalidation runs, which is the window a concurrent order's fill lands in.
"""

from __future__ import annotations

import importlib
import os
import threading

import pytest

from utils.position_read import PositionReadError

os.environ.setdefault("BROKER_API_KEY", "client:::key:::secret")

BROKERS = [
    "aliceblue",
    "angel",
    "arrow",
    "compositedge",
    "definedge",
    "deltaexchange",
    "dhan",
    "dhan_sandbox",
    "firstock",
    "fivepaisa",
    "fivepaisaxts",
    "flattrade",
    "fyers",
    "groww",
    "hdfcsecurities",
    "hdfcsky",
    "ibulls",
    "iifl",
]


def _order_api(broker):
    return importlib.import_module(f"broker.{broker}.api.order_api")


def _serve(monkeypatch, module, fetch):
    """Answer the module's position read with ``fetch``.

    5 Paisa reads the smart order's book through _request_positions, so that
    goes to ``fetch`` too.
    """
    monkeypatch.setattr(module, "get_positions", fetch)
    if hasattr(module, "_request_positions"):
        monkeypatch.setattr(module, "_request_positions", fetch)


@pytest.fixture(params=BROKERS)
def order_api(request, monkeypatch):
    module = _order_api(request.param)
    # These fakes answer with placeholder books. Each plugin's check of a real
    # reply (utils/position_read.py) is pinned in test_position_read_failure.py;
    # here it is told to accept anything, so only the cache is under test.
    monkeypatch.setattr(module, "_position_book_ok", lambda _data: True)
    # Every test starts from an empty book for its token.
    module._invalidate_position_cache("tok")
    yield module
    module._invalidate_position_cache("tok")


def test_a_fetch_overlapping_an_invalidation_is_not_cached(order_api, monkeypatch):
    """The interleaving that repeated or skipped an order."""
    release = threading.Event()
    entered = threading.Event()
    calls = []

    def fake_get_positions(auth, *args, **kwargs):
        calls.append(auth)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10), "the test never released the first fetch"
            return "OLD"
        return "NEW"

    _serve(monkeypatch, order_api, fake_get_positions)

    first = {}
    reader = threading.Thread(
        target=lambda: first.setdefault("value", order_api._get_cached_positions("tok"))
    )
    reader.start()
    assert entered.wait(10), "the first fetch never started"

    # Another smart order's fill lands while the first fetch is in flight.
    order_api._invalidate_position_cache("tok")
    release.set()
    reader.join(10)
    assert not reader.is_alive()

    # The overlapping fetch still answers its own caller...
    assert first["value"] == "OLD"
    # ...but the next smart order must see the book after the fill.
    assert order_api._get_cached_positions("tok") == "NEW"
    assert len(calls) == 2


def test_a_quiet_fetch_is_reused_within_the_second(order_api, monkeypatch):
    """The non-racing path is unchanged: one fetch serves the burst."""
    calls = []

    def fake_get_positions(auth, *args, **kwargs):
        calls.append(auth)
        return {"book": len(calls)}

    _serve(monkeypatch, order_api, fake_get_positions)

    first = order_api._get_cached_positions("tok")
    second = order_api._get_cached_positions("tok")
    assert first == second == {"book": 1}
    assert len(calls) == 1

    order_api._invalidate_position_cache("tok")
    assert order_api._get_cached_positions("tok") == {"book": 2}


def test_a_failed_fetch_is_not_cached(order_api, monkeypatch):
    """A fetch that raised is refused to the caller and leaves nothing behind.

    The read guard turns the exception into PositionReadError, which the smart
    order answers as a refusal; the next read goes to the broker again.
    """
    outcomes = [RuntimeError("network down"), {"book": "fresh"}]

    def fake_get_positions(auth, *args, **kwargs):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    _serve(monkeypatch, order_api, fake_get_positions)

    with pytest.raises(PositionReadError):
        order_api._get_cached_positions("tok")
    assert order_api._get_cached_positions("tok") == {"book": "fresh"}


def test_invalidating_an_absent_entry_is_harmless(order_api):
    order_api._invalidate_position_cache("never-cached")
