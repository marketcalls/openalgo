"""Regression contracts for GitHub issue #1806 (Flattrade).

Verified live against log/openalgo_2026-09-01.log on 2026-09-01, and reconciled
against the official portal (https://pi.flattrade.in/docs, Version 2.0) the same
day.

FIXED here, entirely inside broker/flattrade:

  1. The order-update adapter opened a SECOND PiConnect session with the same
     uid/accesstoken as the market-data adapter. PiConnect permits one session
     per credential pair, so each socket evicted the other with close code 1000
     and both reconnect loops kept the churn alive (13 evictions, 19 order-WS
     connects and 26 market-data reconnects in 5m56s of uptime).
  2. websocket-client surfaces a peer-initiated close through on_error as a raw
     ABNF frame and then calls on_close with (None, None), so an orderly
     eviction was logged as "WebSocket error" with the status code discarded.
  3. Only broker/flattrade/api/data.py paced its requests; order_api.py,
     funds.py and margin_api.py issued unpaced calls against the same account,
     and no retry path lowered the cap when Flattrade named a lower one.
  4. Protocol drift against the docs: the heartbeat acknowledgement is t="hk",
     not t="h", and the connect ack's "s" was compared case-sensitively.

NOT fixed here (the code is in shared layers that are out of scope for this
change): the frontend releases a subscription without naming its mode, the
proxy defaults the missing mode to Quote, and a release that owns nothing
returns success without calling adapter.unsubscribe() -- so an LTP or Depth
subscription stays live at the broker while the client is told it was dropped.
The proxy half of that contract is pinned below so the constraint is explicit.

These tests are self-contained: no socket, port, thread or broker call.
"""

from __future__ import annotations

import importlib
import json
import logging
from collections import defaultdict

import pytest
import websocket

# websocket_proxy must load before any broker.*.streaming module — the two
# packages import each other and the cycle only resolves in that order.
importlib.import_module("websocket_proxy")

from broker.flattrade.api import rate_limit as rl  # noqa: E402
from broker.flattrade.streaming.flattrade_websocket import FlattradeWebSocket  # noqa: E402
from websocket_proxy.server import WebSocketProxy  # noqa: E402


def _close_frame(payload: bytes) -> websocket.ABNF:
    return websocket.ABNF(fin=1, opcode=websocket.ABNF.OPCODE_CLOSE, data=payload)


# --------------------------------------------------------------------------
# 1. The duplicate PiConnect session is gone
# --------------------------------------------------------------------------


def test_flattrade_order_updates_do_not_open_a_second_piconnect_session(monkeypatch) -> None:
    """The dedicated order socket is what evicted the market-data feed.

    The Flattrade factory must hand back the REST-polling adapter. The decision
    lives in the broker plugin, not in the shared registry, so nothing outside
    broker/flattrade has to know about PiConnect's single-session rule.
    """
    from broker.flattrade.streaming import flattrade_order_adapter as foa
    from websocket_proxy.order_adapter import PollingOrderUpdateAdapter

    monkeypatch.delenv("FLATTRADE_ORDER_WS", raising=False)
    adapter = foa.create_flattrade_order_adapter("someuser")

    assert isinstance(adapter, PollingOrderUpdateAdapter)
    assert adapter.broker_name == "flattrade"
    # No WebSocket surface at all — nothing can open a second session.
    assert not hasattr(adapter, "get_ws_url")


def test_the_polling_adapter_satisfies_the_lifecycle_the_service_expects() -> None:
    """order_update_service calls connect()/disconnect() on whatever the factory
    returns, so the substitute has to carry the same surface."""
    from broker.flattrade.streaming import flattrade_order_adapter as foa

    adapter = foa.create_flattrade_order_adapter("someuser")
    for attr in ("connect", "disconnect", "connected"):
        assert hasattr(adapter, attr), attr


def test_the_dedicated_socket_remains_reachable_behind_an_explicit_opt_in(monkeypatch) -> None:
    """Kept reachable for whoever implements the multiplexed fix — but only on
    an explicit request, never by default."""
    from broker.flattrade.streaming import flattrade_order_adapter as foa

    monkeypatch.setenv("FLATTRADE_ORDER_WS", "TRUE")
    monkeypatch.setenv("BROKER_API_KEY", "FZ06120:::secret")
    monkeypatch.setattr(foa, "get_auth_token", lambda *a, **k: "tok")

    adapter = foa.create_flattrade_order_adapter("someuser")
    assert isinstance(adapter, foa.FlattradeOrderUpdateAdapter)
    assert adapter.get_ws_url() == "wss://piconnect.flattrade.in/PiConnectWSAPI/"
    assert adapter.flattrade_uid == "FZ06120"


@pytest.mark.parametrize("value", ["FALSE", "false", "0", "", "yes", "1"])
def test_only_the_exact_opt_in_value_enables_the_socket(monkeypatch, value) -> None:
    """Anything other than TRUE keeps the safe default."""
    from broker.flattrade.streaming import flattrade_order_adapter as foa
    from websocket_proxy.order_adapter import PollingOrderUpdateAdapter

    monkeypatch.setenv("FLATTRADE_ORDER_WS", value)
    assert isinstance(
        foa.create_flattrade_order_adapter("someuser"), PollingOrderUpdateAdapter
    )


def test_the_shared_order_update_registry_is_untouched() -> None:
    """The fix must not require editing the cross-broker service: flattrade is
    NOT in _POLLING_BROKERS, it still routes through its own factory."""
    from services import order_update_service as svc

    assert "flattrade" not in svc._POLLING_BROKERS
    assert svc._BROKER_FACTORIES["flattrade"] == (
        "broker.flattrade.streaming.flattrade_order_adapter",
        "create_flattrade_order_adapter",
    )


def test_flattrade_order_adapter_class_is_still_usable_for_normalization() -> None:
    """Retiring the socket must not retire normalize() — a multiplexed
    implementation would reuse it verbatim."""
    from broker.flattrade.streaming.flattrade_order_adapter import (
        FlattradeOrderUpdateAdapter,
    )

    adapter = FlattradeOrderUpdateAdapter(
        user_id="u", flattrade_uid="FT123", accesstoken="tok"
    )
    fields = adapter.normalize(
        '{"t":"om","norenordno":"25090100000001","tsym":"SBIN-EQ","exch":"NSE",'
        '"trantype":"B","qty":"10","fillshares":"4","prc":"1044.6","prctyp":"LMT",'
        '"pcode":"I","status":"OPEN","avgprc":"1044.5"}'
    )
    assert fields["orderid"] == "25090100000001"
    assert fields["action"] == "BUY"
    assert fields["order_status"] == "open"
    assert fields["filled_quantity"] == 4
    assert fields["pending_quantity"] == 6
    # Flattrade names the product "pcode" where the rest of Noren uses "prd".
    assert fields["product"] == "MIS"


# --------------------------------------------------------------------------
# 2. A close frame is decoded, not reported as a fault
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\x03\xe8", 1000),  # the eviction seen in the live log
        (b"\x03\xf3", 1011),
        (b"\x03\xe8going away", 1000),
        (b"", None),  # RFC 6455 allows a bodiless close
        (b"\x01", None),  # truncated status code
    ],
)
def test_close_frame_status_is_decoded(payload: bytes, expected: int | None) -> None:
    assert FlattradeWebSocket._close_frame_status(_close_frame(payload)) == expected


@pytest.mark.parametrize(
    "not_a_close",
    [None, Exception("boom"), websocket.ABNF(fin=1, opcode=1, data=b"hi")],
)
def test_non_close_errors_are_left_alone(not_a_close) -> None:
    """A genuine fault must keep taking the error path."""
    assert FlattradeWebSocket._close_frame_status(not_a_close) is None


def _client() -> FlattradeWebSocket:
    return FlattradeWebSocket(user_id="u", actid="u", accesstoken="tok")


def test_eviction_is_reported_as_a_close_not_an_error(caplog) -> None:
    client = _client()
    seen: list[tuple] = []
    client.on_error = lambda *a: seen.append(("error", a))

    with caplog.at_level(logging.DEBUG, logger="flattrade_websocket"):
        client._on_error(None, _close_frame(b"\x03\xe8"))

    # The external error callback must NOT fire: this is a handshake, and
    # firing it is what made the adapter schedule a reconnect from the error
    # path as well as the close path.
    assert seen == []
    text = caplog.text
    assert "code 1000" in text
    assert "one session per uid/accesstoken" in text
    # No ERROR record for an orderly close.
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_decoded_close_code_reaches_on_close_exactly_once() -> None:
    """websocket-client calls on_close with (None, None) after a peer close;
    the stashed code must fill that in, and must not be reused."""
    client = _client()
    closes: list[tuple] = []
    client.on_close = lambda ws, code, msg: closes.append((code, msg))

    client._on_error(None, _close_frame(b"\x03\xe8bye"))
    assert closes == []  # _on_error must not tear down itself

    client._on_close(None, None, None)
    assert closes == [(1000, "bye")]
    assert client.connected is False

    # A later, unrelated close must not inherit the consumed code.
    client._on_close(None, None, None)
    assert closes[-1] == (None, None)


def test_an_explicit_close_code_is_never_overwritten_by_the_stash() -> None:
    client = _client()
    closes: list[tuple] = []
    client.on_close = lambda ws, code, msg: closes.append((code, msg))

    client._on_error(None, _close_frame(b"\x03\xe8"))
    client._on_close(None, 1006, "abnormal")
    assert closes == [(1006, "abnormal")]


def test_a_real_error_still_sets_auth_failure_state() -> None:
    client = _client()
    client._on_error(None, Exception("401 Unauthorized"))
    assert client.auth_failed is True
    assert "401" in client.auth_failure_message


# --------------------------------------------------------------------------
# 3. Rate limiting is shared and adaptive
# --------------------------------------------------------------------------


def test_every_flattrade_http_entry_point_shares_the_data_window() -> None:
    """data.py used to be the only paced module, so the window it maintained
    was never the whole picture."""
    from broker.flattrade.api import data, funds, margin_api, order_api

    assert data.DATA_LIMITER is rl.DATA_LIMITER
    assert order_api.DATA_LIMITER is rl.DATA_LIMITER
    assert funds.DATA_LIMITER is rl.DATA_LIMITER
    assert margin_api.DATA_LIMITER is rl.DATA_LIMITER
    # Orders are paced on their own, four-times-tighter ceiling.
    assert order_api.ORDER_LIMITER is rl.ORDER_LIMITER
    assert rl.ORDER_LIMITER is not rl.DATA_LIMITER
    # Both default to 9/sec now — the order budget is the tighter of the two
    # on the per-minute window (40 published, vs 120 observed for data).
    assert rl.ORDER_LIMITER.max_per_minute < rl.DATA_LIMITER.max_per_minute


def test_sliding_window_bursts_to_the_cap_then_defers() -> None:
    limiter = rl.SlidingWindowLimiter("t", max_per_second=3, max_per_minute=100)
    # The first N reservations are immediate...
    assert [round(limiter.reserve(), 3) for _ in range(3)] == [0.0, 0.0, 0.0]
    # ...the next must wait out the rolling second.
    assert limiter.reserve() == pytest.approx(1.0, abs=0.05)
    assert limiter.reserve() == pytest.approx(1.0, abs=0.05)


def test_per_minute_window_is_enforced_independently() -> None:
    limiter = rl.SlidingWindowLimiter("t", max_per_second=100, max_per_minute=2)
    limiter.reserve()
    limiter.reserve()
    assert limiter.reserve() == pytest.approx(60.0, abs=0.05)


@pytest.mark.parametrize(
    ("emsg", "expected_second", "expected_minute"),
    [
        # The exact text Flattrade returned in the issue report.
        (
            "Invalid Input : Order Recieved 11 in a current second exceeds Limit 10 for user",
            10,
            None,
        ),
        ("Order Recieved 101 in a current minute exceeds Limit 100 for user", None, 100),
        # No window named — assume per-second, the one a burst trips first.
        ("exceeds Limit 5", 5, None),
    ],
)
def test_rejection_text_clamps_the_named_window(emsg, expected_second, expected_minute) -> None:
    limiter = rl.SlidingWindowLimiter("t", max_per_second=38, max_per_minute=190)
    rl.note_rate_limit_rejection({"stat": "Not_Ok", "emsg": emsg}, limiter)
    if expected_second is not None:
        assert limiter.max_per_second == expected_second
        assert limiter.max_per_minute == 190
    else:
        assert limiter.max_per_minute == expected_minute
        assert limiter.max_per_second == 38


def test_clamp_only_ever_ratchets_downward() -> None:
    limiter = rl.SlidingWindowLimiter("t", max_per_second=38, max_per_minute=190)
    assert limiter.clamp_per_second(10) is True
    assert limiter.max_per_second == 10
    # A later, looser report must not undo a tighter one.
    assert limiter.clamp_per_second(30) is False
    assert limiter.max_per_second == 10
    assert limiter.clamp_per_second(0) is False
    assert limiter.max_per_second == 10


def test_unparseable_rejection_leaves_the_caps_alone() -> None:
    limiter = rl.SlidingWindowLimiter("t", max_per_second=38, max_per_minute=190)
    for junk in ("Session expired", "", "exceeds Limit for user", None):
        rl.note_rate_limit_rejection({"stat": "Not_Ok", "emsg": junk}, limiter)
    rl.note_rate_limit_rejection("not a dict", limiter)
    assert (limiter.max_per_second, limiter.max_per_minute) == (38, 190)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"stat": "Not_Ok", "emsg": "... exceeds Limit 10 for user"}, True),
        ({"stat": "Not_Ok", "emsg": "... exceeds limit 10 for user"}, True),
        ({"stat": "Not_Ok", "emsg": "Session Expired"}, False),
        ({"stat": "Ok"}, False),
        ("not a dict", False),
    ],
)
def test_rate_limit_error_detection(response, expected) -> None:
    assert rl.is_rate_limit_error(response) is expected


# --------------------------------------------------------------------------
# 4. A mode-mismatched unsubscribe is no longer silent
# --------------------------------------------------------------------------


class _Adapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def unsubscribe(self, symbol: str, exchange: str, mode: int) -> dict:
        self.calls.append((symbol, exchange, mode))
        return {"status": "success"}


def _proxy(*owned: tuple[str, str, str, int]) -> WebSocketProxy:
    """Build a proxy owning the given (client_id, symbol, exchange, mode) rows.

    __new__ rather than __init__: the constructor binds the ZMQ SUB port, and
    these contracts need no bus. Stored subscriptions are JSON rows, matching
    the shape _matching_client_subscriptions parses.
    """
    proxy = WebSocketProxy.__new__(WebSocketProxy)
    proxy.subscriptions = defaultdict(set)
    proxy.subscription_index = defaultdict(set)
    for client_id, symbol, exchange, mode in owned:
        proxy.subscriptions[client_id].add(
            json.dumps(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": mode,
                    "depth_level": 5,
                    "broker": "flattrade",
                }
            )
        )
        proxy.subscription_index[(symbol, exchange, mode)].add(client_id)
    return proxy


def test_a_mode_mismatched_release_never_reaches_the_broker() -> None:
    """The ghost, stated as a contract on the proxy side.

    server.py resolves an unsubscribe against the exact (symbol, exchange, mode)
    key it stored at subscribe time. A release naming the wrong mode owns
    nothing, so it returns success WITHOUT calling adapter.unsubscribe() and the
    real subscription stays live at the broker.

    This proxy behaviour is deliberate and unchanged — it is the client's job to
    name the mode it subscribed with. The fix for #1806 is therefore entirely in
    MarketDataManager.sendUnsubscribe, and this test pins the constraint that
    makes that fix necessary: were the proxy ever to start guessing here, the
    guess would be the bug.
    """
    proxy = _proxy(("c1", "NIFTY29SEP26FUT", "NFO", 3))
    adapter = _Adapter()

    # Depth (3) released as Quote (2) — what the frontend used to send.
    ok, err = proxy._unsubscribe_owned_subscription(
        "c1", adapter, "NIFTY29SEP26FUT", "NFO", 2
    )

    assert (ok, err) == (True, None)  # the client is told it succeeded...
    assert adapter.calls == []  # ...but the broker was never asked...
    # ...and the Depth feed is still running.
    assert proxy.subscription_index[("NIFTY29SEP26FUT", "NFO", 3)] == {"c1"}


def test_naming_the_subscribed_mode_releases_the_broker_feed() -> None:
    """With the mode carried through, the release lands. This is the state the
    frontend fix puts every unsubscribe into."""
    proxy = _proxy(("c1", "NIFTY29SEP26FUT", "NFO", 3))
    adapter = _Adapter()

    ok, err = proxy._unsubscribe_owned_subscription(
        "c1", adapter, "NIFTY29SEP26FUT", "NFO", 3
    )

    assert (ok, err) == (True, None)
    assert adapter.calls == [("NIFTY29SEP26FUT", "NFO", 3)]
    assert ("NIFTY29SEP26FUT", "NFO", 3) not in proxy.subscription_index


@pytest.mark.parametrize("mode", [1, 2, 3])
def test_every_mode_round_trips_through_the_exact_key(mode: int) -> None:
    """Quote (2) used to work by accident, because 2 was the proxy's fallback.
    All three modes must release on their own terms."""
    proxy = _proxy(("c1", "SBIN", "BSE", mode))
    adapter = _Adapter()

    ok, _ = proxy._unsubscribe_owned_subscription("c1", adapter, "SBIN", "BSE", mode)

    assert ok is True
    assert adapter.calls == [("SBIN", "BSE", mode)]


def test_holding_one_symbol_in_two_modes_releases_them_independently() -> None:
    """The frontend's old symbolStillNeeded check suppressed the unsubscribe
    entirely while any other mode held the symbol. Each mode is a separate
    broker subscription and has to be released on its own."""
    proxy = _proxy(("c1", "SBIN", "BSE", 1), ("c1", "SBIN", "BSE", 3))
    adapter = _Adapter()

    proxy._unsubscribe_owned_subscription("c1", adapter, "SBIN", "BSE", 1)
    assert adapter.calls == [("SBIN", "BSE", 1)]
    assert proxy.subscription_index[("SBIN", "BSE", 3)] == {"c1"}

    proxy._unsubscribe_owned_subscription("c1", adapter, "SBIN", "BSE", 3)
    assert adapter.calls == [("SBIN", "BSE", 1), ("SBIN", "BSE", 3)]


# --------------------------------------------------------------------------
# 5. Protocol conformance against broker-api-docs/flattrade-api-docs
#    (reconciled with the live portal, Version 2.0, on 2026-09-01)
# --------------------------------------------------------------------------


def test_heartbeat_acknowledgement_is_consumed_by_the_client() -> None:
    """The doc's heartbeat ack is t="hk". Matching only "h" let every ack fall
    through to the market-data handler to be parsed as a tick."""
    client = _client()
    forwarded: list = []
    client.on_message = lambda ws, msg: forwarded.append(msg)

    assert client._handle_internal_message('{"t":"hk","hk":"1788236880"}') is True
    # ...and the request spelling stays accepted, since some Noren deployments
    # echo it back instead.
    assert client._handle_internal_message('{"t":"h"}') is True

    client._on_message(None, '{"t":"hk","hk":"1788236880"}')
    assert forwarded == []


def test_market_data_frames_are_still_forwarded() -> None:
    client = _client()
    forwarded: list = []
    client.on_message = lambda ws, msg: forwarded.append(msg)

    client._on_message(None, '{"t":"df","tk":"500112","lp":"1044.60"}')
    assert len(forwarded) == 1


@pytest.mark.parametrize("ok_value", ["OK", "Ok", "ok", " Ok "])
def test_connect_ack_accepts_either_documented_or_live_casing(ok_value) -> None:
    """The portal writes "Ok"; the live gateway sends "OK". An exact match
    against one spelling fails the handshake outright if the broker ever
    normalises to the other."""
    client = _client()
    assert client._handle_internal_message(json.dumps({"t": "ak", "s": ok_value})) is True
    assert client.auth_failed is False


@pytest.mark.parametrize("bad", ["Not_Ok", "NOT_OK", ""])
def test_a_rejected_connect_ack_is_still_a_failure(bad) -> None:
    client = _client()
    client._handle_internal_message(
        json.dumps({"t": "ak", "s": bad, "emsg": "Invalid Session"})
    )
    assert client.auth_failed is True


def test_documented_message_types_match_the_client_constants() -> None:
    """Guards the constants against a doc revision going unnoticed."""
    assert FlattradeWebSocket.WS_URL == "wss://piconnect.flattrade.in/PiConnectWSAPI/"
    assert FlattradeWebSocket.MSG_TYPE_CONNECT == "a"
    assert FlattradeWebSocket.MSG_TYPE_AUTH_ACK == "ak"
    assert FlattradeWebSocket.MSG_TYPE_TOUCHLINE_SUB == "t"
    assert FlattradeWebSocket.MSG_TYPE_TOUCHLINE_UNSUB == "u"
    assert FlattradeWebSocket.MSG_TYPE_DEPTH_SUB == "d"
    assert FlattradeWebSocket.MSG_TYPE_DEPTH_UNSUB == "ud"
    assert FlattradeWebSocket.MSG_TYPE_HEARTBEAT == "h"
    assert FlattradeWebSocket.MSG_TYPE_HEARTBEAT_ACK == "hk"


def test_defaults_match_observed_enforcement_not_the_published_table(monkeypatch) -> None:
    """The published table (40/sec, 200/min non-order) is a higher provisioning
    tier. A live account was rejected at 10/sec and 120/min on 2026-09-01 -
    the same figures TradeSmart publishes for the same Noren backend.

    Asserts on _env_int with the environment cleared rather than on the
    module-level singletons: those are bound at import time from
    FLATTRADE_MAX_PER_SECOND / FLATTRADE_MAX_PER_MINUTE, which this same change
    tells higher-tier accounts to set. Reading the singletons would make the
    test fail on a correctly-configured machine even though the defaults are
    right.
    """
    for name in (
        "FLATTRADE_MAX_PER_SECOND",
        "FLATTRADE_MAX_PER_MINUTE",
        "FLATTRADE_ORDER_MAX_PER_SECOND",
        "FLATTRADE_ORDER_MAX_PER_MINUTE",
    ):
        monkeypatch.delenv(name, raising=False)

    assert rl._env_int("FLATTRADE_MAX_PER_SECOND", 9, ceiling=40) == 9
    assert rl._env_int("FLATTRADE_MAX_PER_MINUTE", 110, ceiling=200) == 110
    assert rl._env_int("FLATTRADE_ORDER_MAX_PER_SECOND", 9, ceiling=10) == 9
    assert rl._env_int("FLATTRADE_ORDER_MAX_PER_MINUTE", 38, ceiling=40) == 38


def test_whatever_the_environment_says_the_caps_stay_within_the_published_table() -> None:
    """Environment-independent invariant: however the singletons were
    configured, they can never exceed what Flattrade publishes."""
    assert rl.DATA_LIMITER.max_per_second <= 40
    assert rl.DATA_LIMITER.max_per_minute <= 200
    assert rl.ORDER_LIMITER.max_per_second <= 10
    assert rl.ORDER_LIMITER.max_per_minute <= 40


@pytest.mark.parametrize(
    ("value", "ceiling", "expected"),
    [("3800", 40, 40), ("41", 40, 40), ("38", 40, 38), ("2000", 200, 200)],
)
def test_an_override_above_the_published_ceiling_is_clamped(
    monkeypatch, value, ceiling, expected
) -> None:
    """A stray zero in FLATTRADE_MAX_PER_SECOND would otherwise disable the
    pacing this module exists to provide."""
    monkeypatch.setenv("FLATTRADE_MAX_PER_SECOND", value)
    assert rl._env_int("FLATTRADE_MAX_PER_SECOND", 9, ceiling=ceiling) == expected


def test_a_higher_tier_account_can_raise_the_caps(monkeypatch) -> None:
    """Accounts provisioned above the default tier must not be pinned to it.

    Exercises the env reader directly rather than reloading the module: the
    limiters are module-level singletons that every Flattrade caller imports by
    identity, and reloading would hand this test a different object than the one
    the rest of the process is pacing against.
    """
    monkeypatch.setenv("FLATTRADE_MAX_PER_SECOND", "38")
    monkeypatch.setenv("FLATTRADE_MAX_PER_MINUTE", "190")
    assert rl._env_int("FLATTRADE_MAX_PER_SECOND", 9, ceiling=40) == 38
    assert rl._env_int("FLATTRADE_MAX_PER_MINUTE", 110, ceiling=200) == 190

    # ...and the clamp still protects a raised cap.
    raised = rl.SlidingWindowLimiter("t", max_per_second=38, max_per_minute=190)
    rl.note_rate_limit_rejection(
        {"stat": "Not_Ok", "emsg": "Recieved 11 in a current second exceeds Limit 10 for user"},
        raised,
    )
    assert raised.max_per_second == 10


@pytest.mark.parametrize("junk", ["0", "-5", "abc", "  ", ""])
def test_a_nonsense_env_override_falls_back_to_the_default(monkeypatch, junk) -> None:
    monkeypatch.setenv("FLATTRADE_MAX_PER_SECOND", junk)
    assert rl._env_int("FLATTRADE_MAX_PER_SECOND", 9, ceiling=40) == 9


def test_an_absent_env_override_uses_the_default(monkeypatch) -> None:
    monkeypatch.delenv("FLATTRADE_MAX_PER_SECOND", raising=False)
    assert rl._env_int("FLATTRADE_MAX_PER_SECOND", 9, ceiling=40) == 9


def test_multiquote_batching_imposes_no_delay_of_its_own(monkeypatch) -> None:
    """Chunking must not sleep. Pacing belongs to DATA_LIMITER.

    The old code slept a fixed 1.1s between chunks. Being per-invocation it
    could not see the concurrent option-chain fetches the live log shows (three
    42-symbol fetches starting at 11:16:41, :44 and :49 before any finished),
    while the limiter's rolling window bounds them together. All the sleep
    bought was ~4.4s of latency per call, which pushed each response out far
    enough for the next refresh to land on top of it.

    Asserts that sleep is never called rather than timing the call: a wall-clock
    threshold would flake under CI load, and would also pass on a sleep short
    enough to hide under it. Recording the calls catches a reintroduced sleep of
    any duration, and reports how long it would have been.
    """
    from broker.flattrade.api import data

    slept: list[float] = []
    monkeypatch.setattr(data.time, "sleep", lambda seconds: slept.append(seconds))

    batches: list[list] = []
    monkeypatch.setattr(
        data.BrokerData, "_process_quotes_batch", lambda self, b: batches.append(b) or []
    )

    symbols = [{"symbol": f"S{i}", "exchange": "NFO"} for i in range(42)]
    data.BrokerData("tok").get_multiquotes(symbols)

    assert slept == [], f"batching slept {sum(slept)}s across {len(slept)} calls"
    # Still chunked, and every symbol still dispatched exactly once.
    assert sum(len(b) for b in batches) == len(symbols)
    assert len(batches) == (len(symbols) + 9) // 10
    assert max(len(b) for b in batches) <= 10


def test_a_single_batch_needs_no_chunking_and_still_never_sleeps(monkeypatch) -> None:
    """The <= BATCH_SIZE path is a separate branch; it must not sleep either."""
    from broker.flattrade.api import data

    slept: list[float] = []
    monkeypatch.setattr(data.time, "sleep", lambda seconds: slept.append(seconds))
    batches: list[list] = []
    monkeypatch.setattr(
        data.BrokerData, "_process_quotes_batch", lambda self, b: batches.append(b) or []
    )

    data.BrokerData("tok").get_multiquotes(
        [{"symbol": "SBIN", "exchange": "NSE"}, {"symbol": "INFY", "exchange": "NSE"}]
    )

    assert slept == []
    assert len(batches) == 1


# --------------------------------------------------------------------------
# 6. Review follow-ups (cubic, 2026-09-01)
# --------------------------------------------------------------------------


_REJECTION = {
    "stat": "Not_Ok",
    "emsg": "Invalid Input :  Order Recieved 11 in a current second exceeds Limit 10 for user",
}
_OK = {"stat": "Ok", "values": []}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)
        self.status_code = 200

    def json(self):
        return self._payload


class _FakeClient:
    """Replays a queued list of payloads and counts the calls made."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def _next(self):
        self.calls += 1
        return _FakeResponse(
            self.payloads.pop(0) if self.payloads else _OK
        )

    def request(self, *a, **k):
        return self._next()

    def post(self, *a, **k):
        return self._next()


@pytest.fixture
def fresh_limiters(monkeypatch):
    """Swap the module singletons for throwaway limiters.

    The real ones are process-wide and ratchet down permanently, so clamping
    them in a test would silently tighten every later test in the session.
    """
    data_lim = rl.SlidingWindowLimiter("data", max_per_second=38, max_per_minute=190)
    order_lim = rl.SlidingWindowLimiter("order", max_per_second=9, max_per_minute=38)

    from broker.flattrade.api import data, funds, margin_api, order_api

    for mod in (data, order_api, funds, margin_api):
        if hasattr(mod, "DATA_LIMITER"):
            monkeypatch.setattr(mod, "DATA_LIMITER", data_lim)
        if hasattr(mod, "ORDER_LIMITER"):
            monkeypatch.setattr(mod, "ORDER_LIMITER", order_lim)
    monkeypatch.setattr(rl.time, "sleep", lambda _s: None)  # no real backoff waits
    return data_lim, order_lim


def test_a_read_endpoint_clamps_and_retries(monkeypatch, fresh_limiters) -> None:
    """Behavioural: a rejection must lower the cap AND be retried, or the first
    one surfaces to the UI as empty data."""
    data_lim, _ = fresh_limiters
    from broker.flattrade.api import order_api

    client = _FakeClient([_REJECTION, _OK])
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api.time, "sleep", lambda _s: None)
    monkeypatch.setenv("BROKER_API_KEY", "FZ06120:::secret")

    result = order_api.get_api_response("/PiConnectAPI/OrderBook", "tok", method="POST")

    assert data_lim.max_per_second == 10  # learned from the rejection
    assert client.calls == 2  # and retried
    assert result == _OK  # caller sees the good response, not the rejection


def test_a_read_endpoint_gives_up_after_the_retry_budget(monkeypatch, fresh_limiters) -> None:
    """It must not retry forever; the caller gets the rejection to handle."""
    from broker.flattrade.api import order_api

    client = _FakeClient([_REJECTION] * 10)
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api.time, "sleep", lambda _s: None)
    monkeypatch.setenv("BROKER_API_KEY", "FZ06120:::secret")

    result = order_api.get_api_response("/PiConnectAPI/OrderBook", "tok", method="POST")

    assert client.calls == rl.MAX_RATE_LIMIT_RETRIES + 1
    assert result["stat"] == "Not_Ok"


def test_a_successful_read_is_not_retried(monkeypatch, fresh_limiters) -> None:
    data_lim, _ = fresh_limiters
    from broker.flattrade.api import order_api

    client = _FakeClient([_OK])
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setenv("BROKER_API_KEY", "FZ06120:::secret")

    order_api.get_api_response("/PiConnectAPI/OrderBook", "tok", method="POST")

    assert client.calls == 1
    assert data_lim.max_per_second == 38  # untouched


def test_cancel_order_clamps_but_is_never_retried(monkeypatch, fresh_limiters) -> None:
    """An order rejected for rate cannot be told apart from one accepted with a
    lost response, so a retry risks a duplicate. Clamp, then surface it."""
    _, order_lim = fresh_limiters
    from broker.flattrade.api import order_api

    # Names a limit genuinely below the order default of 9 — the clamp only
    # ratchets downward, so a rejection quoting 10 would correctly be a no-op
    # here and would not prove the wiring.
    tight = {
        "stat": "Not_Ok",
        "emsg": "Recieved 6 in a current second exceeds Limit 5 for user",
    }
    client = _FakeClient([tight, _OK])
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setenv("BROKER_API_KEY", "FZ06120:::secret")

    response, _status = order_api.cancel_order("2509010000001", "tok")

    assert order_lim.max_per_second == 5  # learned
    assert client.calls == 1  # exactly one order request, never two
    assert response["status"] == "error"  # surfaced, not silently retried


def test_funds_clamps_and_retries(monkeypatch, fresh_limiters) -> None:
    """A funds rejection used to read as empty funds and zero PnL while the cap
    stayed too high for every later call."""
    data_lim, _ = fresh_limiters
    from broker.flattrade.api import funds

    client = _FakeClient([_REJECTION, {"stat": "Ok", "cash": "100"}])
    monkeypatch.setattr(funds.time, "sleep", lambda _s: None)

    result = funds.fetch_data("/PiConnectAPI/Limits", "payload", {}, client)

    assert data_lim.max_per_second == 10
    assert client.calls == 2
    assert result["cash"] == "100"


def test_the_retry_helper_is_the_single_place_backoff_is_decided() -> None:
    """Behavioural contract for the helper the four entry points share."""
    lim = rl.SlidingWindowLimiter("t", max_per_second=38, max_per_minute=190)

    # Not a rejection -> no retry, no clamp.
    assert rl.rate_limit_retry_delay(_OK, lim, 0) is None
    assert lim.max_per_second == 38

    # A rejection -> clamp, and an exponential backoff curve.
    assert rl.rate_limit_retry_delay(_REJECTION, lim, 0) == 2.0
    assert lim.max_per_second == 10
    assert rl.rate_limit_retry_delay(_REJECTION, lim, 1) == 4.0
    assert rl.rate_limit_retry_delay(_REJECTION, lim, 2) == 8.0

    # Budget spent -> stop retrying, but the clamp still applied.
    assert rl.rate_limit_retry_delay(_REJECTION, lim, rl.MAX_RATE_LIMIT_RETRIES) is None


# -- partial fills over the polling path ----------------------------------


def _orderbook_row(qty: str, fillshares: str | None, status: str = "OPEN") -> dict:
    row = {
        "norenordno": "2509010000001",
        "tsym": "SBIN-EQ",
        "exch": "NSE",
        "trantype": "B",
        "qty": qty,
        "prc": "1044.60",
        "prctyp": "LMT",
        "prd": "I",
        "status": status,
        "norentm": "11:22:33 01-09-2026",
        "avgprc": "1044.50",
    }
    if fillshares is not None:
        row["fillshares"] = fillshares
    return row


def test_orderbook_mapping_exposes_fill_state() -> None:
    """PollingOrderUpdateAdapter diffs (order_status, filled_quantity). With
    filled_quantity missing it read 0 forever, so a partial fill on an order
    that stayed OPEN published no update at all."""
    from broker.flattrade.mapping.order_data import transform_order_data

    [row] = transform_order_data([_orderbook_row(qty="100", fillshares="40")])
    assert row["filled_quantity"] == 40
    assert row["pending_quantity"] == 60
    assert row["average_price"] == 1044.50
    assert row["order_status"] == "open"


def test_a_partial_fill_changes_the_polled_snapshot() -> None:
    """The exact tuple the poller diffs on must move when a fill lands."""
    from broker.flattrade.mapping.order_data import transform_order_data

    def snapshot(fillshares):
        [row] = transform_order_data([_orderbook_row("100", fillshares)])
        return (row["order_status"], int(row["filled_quantity"] or 0))

    assert snapshot(None) == ("open", 0)
    assert snapshot("40") != snapshot(None)  # partial fill is now visible
    assert snapshot("40") != snapshot("70")  # and each further fill too


@pytest.mark.parametrize(
    ("qty", "fillshares", "filled", "pending"),
    [
        ("100", None, 0, 100),  # never traded — Noren omits the field
        ("100", "", 0, 100),
        ("100", "0", 0, 100),
        ("100", "100", 100, 0),  # fully filled
        ("100", "120", 120, 0),  # never negative
        ("bad", "40", 40, 0),  # unparseable qty must not raise
    ],
)
def test_fill_coercion_is_total(qty, fillshares, filled, pending) -> None:
    """Noren sends these as strings and omits them on an untraded order."""
    from broker.flattrade.mapping.order_data import transform_order_data

    [row] = transform_order_data([_orderbook_row(qty, fillshares)])
    assert row["filled_quantity"] == filled
    assert row["pending_quantity"] == pending


# -- close frames ---------------------------------------------------------


def test_a_close_frame_without_a_status_code_is_still_a_close() -> None:
    """RFC 6455 allows a bodiless close. Branching on the decoded code sent it
    down the error path instead of reporting it as a close."""
    client = _client()
    errors: list = []
    closes: list = []
    client.on_error = lambda *a: errors.append(a)
    client.on_close = lambda ws, code, msg: closes.append((code, msg))

    client._on_error(None, _close_frame(b""))
    assert errors == []  # not a fault

    client._on_close(None, None, None)
    assert closes == [(None, None)]  # reported as a close, code genuinely unknown


def test_an_auth_failure_in_the_close_reason_arms_the_bounded_retry() -> None:
    """Flattrade can reject a session via the close reason. Returning early
    skipped _is_fatal_auth_error and left the adapter on the generic reconnect
    loop, retrying a token that will never work."""
    client = _client()
    client._on_error(None, _close_frame(b"\x03\xe8Invalid Session"))
    assert client.auth_failed is True
    assert "Invalid Session" in client.auth_failure_message


@pytest.mark.parametrize("reason", [b"", b"going away", b"server restart"])
def test_an_ordinary_close_reason_does_not_claim_an_auth_failure(reason) -> None:
    client = _client()
    client._on_error(None, _close_frame(b"\x03\xe8" + reason))
    assert client.auth_failed is False


def test_is_close_frame_discriminates() -> None:
    assert FlattradeWebSocket._is_close_frame(_close_frame(b"")) is True
    assert FlattradeWebSocket._is_close_frame(_close_frame(b"\x03\xe8")) is True
    assert FlattradeWebSocket._is_close_frame(Exception("boom")) is False
    assert (
        FlattradeWebSocket._is_close_frame(websocket.ABNF(fin=1, opcode=1, data=b"hi"))
        is False
    )
