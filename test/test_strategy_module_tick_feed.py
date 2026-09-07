"""Strategy-module tick feed.

What matters here is that the risk engine gets a price whichever source is
alive, that it is told the moment the source changes, and that nothing the feed
allocates outlives the run that asked for it.

The clock is injected and the loops are driven by hand. Every timing assertion
is therefore exact rather than a sleep that is usually long enough, and the
whole file runs in milliseconds.
"""

from __future__ import annotations

from services.strategy_module import tick_feed as tf

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    """A monotonic clock that only moves when the test says so."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class FakeWsClient:
    """Stands in for services.websocket_client.WebSocketClient."""

    def __init__(self) -> None:
        self.connected = True
        self.subscribed: set[tuple[str, str]] = set()
        self.subscribe_calls: list[list[dict]] = []
        self.unsubscribe_calls: list[list[dict]] = []
        self.callbacks: dict[str, list] = {}
        self.subscribe_result = {"status": "success"}

    def subscribe(self, symbols, mode="LTP"):
        self.subscribe_calls.append(symbols)
        if self.subscribe_result.get("status") != "error":
            for item in symbols:
                self.subscribed.add((item["symbol"], item["exchange"]))
        return self.subscribe_result

    def unsubscribe(self, symbols, mode="LTP"):
        self.unsubscribe_calls.append(symbols)
        for item in symbols:
            self.subscribed.discard((item["symbol"], item["exchange"]))
        return {"status": "success"}

    def register_callback(self, event_type, callback):
        self.callbacks.setdefault(event_type, []).append(callback)

    def unregister_callback(self, event_type, callback):
        handlers = self.callbacks.get(event_type, [])
        if callback in handlers:
            handlers.remove(callback)


class FakeQuotes:
    """Stands in for services.quotes_service.get_multiquotes."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.prices: dict[tuple[str, str], float] = {}
        #: Queue of outcomes; each entry is "ok", 429 or an exception instance.
        self.script: list = []

    def __call__(self, symbols, api_key):
        self.calls.append(list(symbols))
        outcome = self.script.pop(0) if self.script else "ok"
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == 429:
            return False, {"status": "error", "message": "Too many requests"}, 429
        results = []
        for item in symbols:
            price = self.prices.get((item["symbol"], item["exchange"]))
            if price is None:
                results.append({**item, "error": "no data"})
            else:
                results.append({**item, "data": {"ltp": price}})
        return True, {"status": "success", "results": results}, 200


def make_feed(clock=None, ws=None, quotes=None, **kwargs):
    """A feed wired to fakes, with its loops NOT started."""
    clock = clock or FakeClock()
    ws = ws if ws is not None else FakeWsClient()
    quotes = quotes or FakeQuotes()
    feed = tf.RiskTickFeed(
        clock=clock,
        ws_provider=lambda _key: ws,
        quote_fetcher=quotes,
        api_key_provider=lambda: "test-key",
        **kwargs,
    )
    # The loops are driven by hand; mark the feed started so add/remove behave
    # exactly as they do in production without spawning threads.
    feed._running = True
    return feed, clock, ws, quotes


def tick(symbol, exchange, ltp):
    """The websocket tick shape the proxy actually sends."""
    return {"type": "market_data", "symbol": symbol, "exchange": exchange, "data": {"ltp": ltp}}


# ---------------------------------------------------------------------------
# Refcounting
# ---------------------------------------------------------------------------


def test_two_runs_sharing_a_symbol_hold_one_subscription():
    feed, _clock, ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("NIFTY28MAY2624000CE", "NFO")])
        feed.add_run_subscriptions(2, [("NIFTY28MAY2624000CE", "NFO")])

        # The second run found the symbol already tracked, so no second
        # subscribe went to the proxy.
        assert len(ws.subscribe_calls) == 1
        assert ws.subscribed == {("NIFTY28MAY2624000CE", "NFO")}
    finally:
        feed.stop()


def test_the_subscription_survives_the_first_run_leaving():
    feed, _clock, ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("NIFTY28MAY2624000CE", "NFO")])
        feed.add_run_subscriptions(2, [("NIFTY28MAY2624000CE", "NFO")])

        dropped = feed.remove_run_subscriptions(1)

        assert dropped == []
        assert ws.unsubscribe_calls == []
        assert ws.subscribed == {("NIFTY28MAY2624000CE", "NFO")}
        # Run 2 can still price its leg.
        feed.on_tick(tick("NIFTY28MAY2624000CE", "NFO", 123.5))
        feed._drain_ticks_once()
        assert feed.get_ltp("NIFTY28MAY2624000CE", "NFO") == 123.5
    finally:
        feed.stop()


def test_the_last_run_out_drops_the_subscription():
    feed, _clock, ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("NIFTY28MAY2624000CE", "NFO")])
        feed.add_run_subscriptions(2, [("NIFTY28MAY2624000CE", "NFO")])

        feed.remove_run_subscriptions(1)
        dropped = feed.remove_run_subscriptions(2)

        assert dropped == ["NFO:NIFTY28MAY2624000CE"]
        assert ws.subscribed == set()
        assert feed.get_ltp("NIFTY28MAY2624000CE", "NFO") is None
    finally:
        feed.stop()


def test_a_run_keeps_the_symbols_the_other_run_does_not_share():
    feed, _clock, ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO"), ("SHARED", "NFO")])
        feed.add_run_subscriptions(2, [("PE", "NFO"), ("SHARED", "NFO")])

        dropped = feed.remove_run_subscriptions(1)

        assert dropped == ["NFO:CE"]
        assert ws.subscribed == {("SHARED", "NFO"), ("PE", "NFO")}
    finally:
        feed.stop()


def test_removing_a_run_twice_is_harmless():
    feed, _clock, _ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(7, [("CE", "NFO")])
        assert feed.remove_run_subscriptions(7) == ["NFO:CE"]
        assert feed.remove_run_subscriptions(7) == []
        assert feed.remove_run_subscriptions(999) == []
    finally:
        feed.stop()


def test_symbols_are_accepted_as_pairs_or_dicts():
    feed, _clock, _ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [{"symbol": "CE", "exchange": "nfo"}, ("PE", "NFO")])
        # The exchange is normalised, so a dict from the API and a tuple from
        # the engine cannot end up as two entries for one contract.
        assert feed.get_source("CE", "NFO") == tf.WS_LIVE
        assert feed.get_source("PE", "NFO") == tf.WS_LIVE
    finally:
        feed.stop()


def test_an_unusable_entry_is_skipped_rather_than_registered():
    feed, _clock, ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("CE", ""), None, {"symbol": "PE"}, ("OK", "NFO")])
        assert ws.subscribed == {("OK", "NFO")}
        assert feed.health()["tracked_symbols"] == 1
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Source state machine
# ---------------------------------------------------------------------------


def test_a_symbol_starts_on_the_websocket():
    feed, _clock, _ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        assert feed.get_source("CE", "NFO") == tf.WS_LIVE
        # No price yet, and the feed says so rather than inventing one.
        assert feed.get_ltp("CE", "NFO") is None
    finally:
        feed.stop()


def test_the_full_ws_polling_ws_round_trip():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, stale_fatal_sec=60.0)
    events = []
    feed.set_notify(events.append)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        quotes.prices[("CE", "NFO")] = 88.0

        # A tick keeps it live.
        clock.advance(1)
        feed.on_tick(tick("CE", "NFO", 100.0))
        feed._drain_ticks_once()
        assert feed.get_ltp("CE", "NFO") == 100.0

        # Nine seconds of silence is not enough.
        clock.advance(9)
        feed._poll_once()
        assert feed.get_source("CE", "NFO") == tf.WS_LIVE
        assert quotes.calls == []

        # The tenth second is.
        clock.advance(1)
        assert feed._poll_once() == 1
        assert feed.get_source("CE", "NFO") == tf.POLLING
        assert feed.get_ltp("CE", "NFO") == 88.0
        assert [(e.previous, e.source) for e in events] == [(tf.WS_LIVE, tf.POLLING)]

        # One tick brings it straight back.
        clock.advance(1)
        feed.on_tick(tick("CE", "NFO", 101.5))
        feed._drain_ticks_once()
        assert feed.get_source("CE", "NFO") == tf.WS_LIVE
        assert feed.get_ltp("CE", "NFO") == 101.5
        assert [(e.previous, e.source) for e in events] == [
            (tf.WS_LIVE, tf.POLLING),
            (tf.POLLING, tf.WS_LIVE),
        ]
    finally:
        feed.stop()


def test_a_tick_while_polling_drops_the_symbol_from_the_next_poll_cycle():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO"), ("PE", "NFO")])
        quotes.prices.update({("CE", "NFO"): 10.0, ("PE", "NFO"): 20.0})

        clock.advance(10)
        feed._poll_once()
        assert len(quotes.calls[0]) == 2

        # CE ticks; PE stays quiet.
        clock.advance(1)
        feed.on_tick(tick("CE", "NFO", 11.0))
        feed._drain_ticks_once()

        clock.advance(1)
        feed._poll_once()
        assert [item["symbol"] for item in quotes.calls[1]] == ["PE"]
    finally:
        feed.stop()


def test_both_sources_failing_marks_the_symbol_stale():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, stale_fatal_sec=60.0)
    events = []
    feed.set_notify(events.append)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        # The quote service answers, but with no price for this contract.
        quotes.prices.clear()

        clock.advance(10)
        feed._poll_once()
        assert feed.get_source("CE", "NFO") == tf.POLLING

        clock.advance(49)
        feed._poll_once()
        assert feed.get_source("CE", "NFO") == tf.POLLING

        clock.advance(1)
        feed._poll_once()
        assert feed.get_source("CE", "NFO") == tf.STALE
        assert feed.is_stale("CE", "NFO") is True
        assert [e.source for e in events] == [tf.POLLING, tf.STALE]
    finally:
        feed.stop()


def test_a_stale_symbol_stops_being_polled_and_does_not_recover_by_itself():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, stale_fatal_sec=60.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        clock.advance(60)
        feed._poll_once()
        assert feed.get_source("CE", "NFO") == tf.STALE
        calls_at_stale = len(quotes.calls)

        # A tick records its price, because a real number beats a missing one,
        # but the source stays STALE: a halted run must not resume silently.
        clock.advance(1)
        feed.on_tick(tick("CE", "NFO", 42.0))
        feed._drain_ticks_once()
        assert feed.get_ltp("CE", "NFO") == 42.0
        assert feed.get_source("CE", "NFO") == tf.STALE

        clock.advance(5)
        feed._poll_once()
        assert len(quotes.calls) == calls_at_stale

        # Recovery is an explicit act.
        assert feed.clear_stale("CE", "NFO") is True
        assert feed.get_source("CE", "NFO") == tf.POLLING
        assert feed.clear_stale("CE", "NFO") is False
    finally:
        feed.stop()


def test_a_refused_subscribe_falls_straight_to_polling():
    ws = FakeWsClient()
    ws.subscribe_result = {"status": "error", "message": "no broker adapter"}
    feed, _clock, _ws, quotes = make_feed(ws=ws)
    try:
        quotes.prices[("CE", "NFO")] = 55.0
        feed.add_run_subscriptions(1, [("CE", "NFO")])

        # No waiting out the stale threshold: REST covers it on the next cycle.
        assert feed.get_source("CE", "NFO") == tf.POLLING
        feed._poll_once()
        assert feed.get_ltp("CE", "NFO") == 55.0
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def test_polling_symbols_are_fetched_in_one_batched_call():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, poll_batch_max=50)
    try:
        pairs = [(f"SYM{i}", "NFO") for i in range(30)]
        feed.add_run_subscriptions(1, pairs)
        quotes.prices.update({p: float(i) + 1 for i, p in enumerate(pairs)})

        clock.advance(10)
        priced = feed._poll_once()

        assert len(quotes.calls) == 1
        assert len(quotes.calls[0]) == 30
        assert priced == 30
        assert feed.get_ltp("SYM0", "NFO") == 1.0
        assert feed.get_ltp("SYM29", "NFO") == 30.0
    finally:
        feed.stop()


def test_the_batch_cap_splits_the_cycle_and_still_covers_everything():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, poll_batch_max=50)
    try:
        pairs = [(f"SYM{i}", "NFO") for i in range(120)]
        feed.add_run_subscriptions(1, pairs)
        quotes.prices.update(dict.fromkeys(pairs, 7.0))

        clock.advance(10)
        feed._poll_once()

        assert [len(call) for call in quotes.calls] == [50, 50, 20]
        fetched = {item["symbol"] for call in quotes.calls for item in call}
        assert fetched == {f"SYM{i}" for i in range(120)}
        assert all(feed.get_ltp(f"SYM{i}", "NFO") == 7.0 for i in range(120))
    finally:
        feed.stop()


def test_nothing_is_fetched_while_every_symbol_is_live():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        clock.advance(5)
        feed.on_tick(tick("CE", "NFO", 12.0))
        feed._drain_ticks_once()
        clock.advance(5)
        assert feed._poll_once() == 0
        assert quotes.calls == []
    finally:
        feed.stop()


def test_a_zero_price_is_refused_rather_than_marked():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        feed.on_tick(tick("CE", "NFO", 100.0))
        feed._drain_ticks_once()

        # Brokers send 0 for "no trade yet". Marking a leg at 0 would fire
        # every stop at once, so the last real price stands.
        clock.advance(1)
        feed.on_tick(tick("CE", "NFO", 0))
        feed._drain_ticks_once()
        assert feed.get_ltp("CE", "NFO") == 100.0

        quotes.prices[("CE", "NFO")] = 0.0
        clock.advance(10)
        feed._poll_once()
        assert feed.get_ltp("CE", "NFO") == 100.0
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_a_429_backs_off_two_five_ten_thirty_and_degrades_the_feed():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, stale_fatal_sec=10_000.0)
    events = []
    feed.set_notify(events.append)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        quotes.prices[("CE", "NFO")] = 5.0

        clock.advance(10)
        quotes.script = [429]
        feed._poll_once()
        assert feed.degraded is True
        assert len(quotes.calls) == 1

        observed = []
        for expected in (2.0, 5.0, 10.0, 30.0, 30.0):
            # Nothing is attempted until the backoff has run out.
            before = len(quotes.calls)
            clock.advance(expected - 0.01)
            feed._poll_once()
            assert len(quotes.calls) == before, f"polled during the {expected}s backoff"

            clock.advance(0.01)
            quotes.script = [429]
            feed._poll_once()
            assert len(quotes.calls) == before + 1
            observed.append(expected)

        assert observed == [2.0, 5.0, 10.0, 30.0, 30.0]

        # It backed off; it never gave up. The next good cycle clears the flag.
        clock.advance(30)
        feed._poll_once()
        assert feed.degraded is False
        assert feed.get_ltp("CE", "NFO") == 5.0

        feed_events = [e for e in events if e.symbol is None]
        assert [e.degraded for e in feed_events] == [True, False]
    finally:
        feed.stop()


def test_a_rate_limit_raised_as_an_exception_is_treated_the_same():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        clock.advance(10)
        quotes.script = [RuntimeError("HTTP 429 Too Many Requests")]
        feed._poll_once()
        assert feed.degraded is True
    finally:
        feed.stop()


def test_a_symbol_still_ages_to_stale_while_the_feed_is_backing_off():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, stale_fatal_sec=60.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        clock.advance(10)
        quotes.script = [429]
        feed._poll_once()
        assert feed.degraded is True

        # The backoff suppresses the fetch, never the evaluation: a run whose
        # prices have stopped must still be halted.
        clock.advance(50)
        feed._poll_once()
        assert feed.get_source("CE", "NFO") == tf.STALE
    finally:
        feed.stop()


def test_an_ordinary_error_neither_degrades_the_feed_nor_stops_it():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        quotes.prices[("CE", "NFO")] = 9.0

        clock.advance(10)
        quotes.script = [RuntimeError("broker timeout")]
        feed._poll_once()
        assert feed.degraded is False
        assert feed.get_ltp("CE", "NFO") is None

        clock.advance(2)
        feed._poll_once()
        assert feed.get_ltp("CE", "NFO") == 9.0
    finally:
        feed.stop()


def test_one_failed_batch_does_not_starve_the_batches_behind_it():
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0, poll_batch_max=50)
    try:
        pairs = [(f"SYM{i:03d}", "NFO") for i in range(120)]
        feed.add_run_subscriptions(1, pairs)
        quotes.prices.update(dict.fromkeys(pairs, 4.0))

        clock.advance(10)
        # The first batch fails every cycle. The batches are independent calls,
        # so breaking on the first would let a permanent failure at the front of
        # the book age every symbol behind it to STALE on a working feed.
        quotes.script = [RuntimeError("broker timeout")]
        priced = feed._poll_once()

        assert len(quotes.calls) == 3
        assert priced == 70
        assert feed.get_ltp("SYM000", "NFO") is None
        assert feed.get_ltp("SYM050", "NFO") == 4.0
        assert feed.get_ltp("SYM119", "NFO") == 4.0
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Ticks for nobody
# ---------------------------------------------------------------------------


def test_a_tick_for_an_unsubscribed_symbol_is_dropped_at_the_producer():
    feed, _clock, _ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])

        feed.on_tick(tick("RELIANCE", "NSE", 2900.0))
        feed.on_tick(tick("CE", "BFO", 10.0))  # right symbol, wrong exchange
        feed.on_tick({"symbol": "CE"})  # no exchange
        feed.on_tick(None)

        # Nothing was queued, so the drain loop has nothing to do and no state
        # was allocated for any of them.
        assert feed._queue.qsize() == 0
        assert feed._drain_ticks_once() == 0
        assert feed.get_ltp("RELIANCE", "NSE") is None
        assert feed.health()["tracked_symbols"] == 1
    finally:
        feed.stop()


def test_a_tick_that_arrives_after_its_run_left_changes_nothing():
    feed, _clock, _ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        feed.on_tick(tick("CE", "NFO", 10.0))
        # The run ends with the tick still queued.
        feed.remove_run_subscriptions(1)

        assert feed._drain_ticks_once() == 0
        assert feed.get_ltp("CE", "NFO") is None
        assert feed.health()["tracked_symbols"] == 0
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Notify hook
# ---------------------------------------------------------------------------


def test_a_notify_handler_that_raises_does_not_take_the_feed_with_it():
    feed, clock, _ws, _quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.set_notify(lambda _event: 1 / 0)
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        clock.advance(10)
        feed._poll_once()
        assert feed.get_source("CE", "NFO") == tf.POLLING
    finally:
        feed.stop()


def test_re_registering_the_hook_replaces_it():
    feed, clock, _ws, _quotes = make_feed(stale_threshold_sec=10.0)
    first, second = [], []
    try:
        feed.set_notify(first.append)
        feed.set_notify(second.append)
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        clock.advance(10)
        feed._poll_once()

        # One hook, not an accumulating list, in a worker that never restarts.
        assert first == []
        assert len(second) == 1
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Resource hygiene
# ---------------------------------------------------------------------------


def test_removal_cleans_up_completely():
    feed, clock, ws, quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO"), ("PE", "NFO")])
        feed.on_tick(tick("CE", "NFO", 10.0))
        feed._drain_ticks_once()
        clock.advance(10)
        feed._poll_once()

        feed.remove_run_subscriptions(1)

        assert feed._symbols == {}
        assert feed._runs == {}
        assert feed._wanted == frozenset()
        assert feed._queue.qsize() == 0
        assert ws.subscribed == set()
        assert feed.health()["tracked_symbols"] == 0
        assert feed.health()["runs"] == 0

        # And nothing keeps working in the background for a run that is gone.
        clock.advance(100)
        calls_before = len(quotes.calls)
        assert feed._poll_once() == 0
        assert len(quotes.calls) == calls_before
    finally:
        feed.stop()


def test_stop_unhooks_the_shared_websocket_client():
    feed, _clock, ws, _quotes = make_feed()
    feed.add_run_subscriptions(1, [("CE", "NFO")])
    assert ws.callbacks["market_data"] == [feed.on_tick]

    feed.stop()

    # The client is a platform-wide singleton: the feed unhooks and
    # unsubscribes, and deliberately does not disconnect it.
    assert ws.callbacks["market_data"] == []
    assert ws.callbacks["auth"] == []
    assert ws.subscribed == set()
    assert feed._symbols == {}


def test_stop_is_idempotent():
    feed, _clock, _ws, _quotes = make_feed()
    feed.add_run_subscriptions(1, [("CE", "NFO")])
    feed.stop()
    feed.stop()
    assert feed._running is False


def test_the_tracked_symbol_ceiling_refuses_rather_than_growing_without_bound():
    feed, _clock, _ws, _quotes = make_feed(max_tracked_symbols=3)
    try:
        feed.add_run_subscriptions(1, [(f"SYM{i}", "NFO") for i in range(10)])
        assert feed.health()["tracked_symbols"] == 3
    finally:
        feed.stop()


def test_the_tick_queue_is_bounded():
    # A producer that never blocks plus an unbounded queue is how a worker that
    # never restarts gets OOM-killed. Shedding the newest is right for market
    # data: the next tick supersedes the one dropped.
    assert tf.TICK_QUEUE_MAX == 10000
    feed, _clock, _ws, _quotes = make_feed()
    try:
        assert feed._queue.maxsize == tf.TICK_QUEUE_MAX
    finally:
        feed.stop()


def test_the_loop_threads_are_shared_not_per_call():
    feed, _clock, _ws, _quotes = make_feed()
    feed._running = False  # undo the manual start so _ensure_started really runs
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        drain, poll = feed._drain_thread, feed._poll_thread
        assert drain is not None and poll is not None
        assert drain.is_alive() and poll.is_alive()

        for run_id in range(2, 12):
            feed.add_run_subscriptions(run_id, [(f"SYM{run_id}", "NFO")])

        # Eleven runs, still exactly two threads.
        assert feed._drain_thread is drain
        assert feed._poll_thread is poll
    finally:
        feed.stop()

    assert not drain.is_alive()
    assert not poll.is_alive()


def test_the_singleton_is_the_only_instance_handed_out():
    assert tf.get_risk_tick_feed() is tf.get_risk_tick_feed()


# ---------------------------------------------------------------------------
# The threading boundary
# ---------------------------------------------------------------------------


def test_the_producer_hands_over_on_a_real_queue_and_takes_no_lock():
    # The point of the whole module. on_tick may run on the asyncio loop's real
    # OS thread; a real thread touching a green lock raises greenlet.error
    # inside the hub and wedges that thread forever. So the queue must be one
    # of the unpatched primitives, and on_tick must not touch self._lock.
    from utils import real_threading

    feed, _clock, _ws, _quotes = make_feed()
    try:
        assert isinstance(feed._queue, real_threading.Queue)

        # Hold the state lock and prove the producer does not want it.
        feed.add_run_subscriptions(1, [("CE", "NFO")])
        with feed._lock:
            feed.on_tick(tick("CE", "NFO", 10.0))
            assert feed._queue.qsize() == 1
    finally:
        feed.stop()


def test_reconnect_resubscribes_every_tracked_symbol():
    feed, _clock, ws, _quotes = make_feed()
    try:
        feed.add_run_subscriptions(1, [("CE", "NFO"), ("PE", "NFO")])
        ws.subscribed.clear()  # the proxy dropped them on the disconnect

        auth_handler = ws.callbacks["auth"][0]
        auth_handler({"status": "success"})

        # Without this the symbols would quietly poll forever after a reconnect.
        assert ws.subscribed == {("CE", "NFO"), ("PE", "NFO")}
        auth_handler({"status": "error"})
        assert len(ws.subscribe_calls) == 2
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# The per-price hook
#
# This is what drives risk evaluation. set_notify reports source transitions,
# which is a display concern; this fires for every usable price.
# ---------------------------------------------------------------------------


def test_a_websocket_tick_reaches_the_price_hook():
    feed, _clock, _ws, _quotes = make_feed()
    feed.add_run_subscriptions(1, [("RELIANCE", "NSE")])
    seen = []
    feed.set_on_price(lambda s, e, p: seen.append((s, e, p)))

    feed.on_tick(tick("RELIANCE", "NSE", 1287.5))
    feed._drain_ticks_once()

    assert seen == [("RELIANCE", "NSE", 1287.5)]


def test_a_polled_price_reaches_the_price_hook_too():
    # The one that matters most. A leg that has fallen back to REST must still
    # be risk evaluated: if only websocket ticks drove the hook, the fallback
    # would keep the price fresh on screen while protecting nothing.
    feed, clock, _ws, quotes = make_feed(stale_threshold_sec=10.0)
    try:
        feed.add_run_subscriptions(1, [("RELIANCE", "NSE")])
        seen = []
        feed.set_on_price(lambda s, e, p: seen.append((s, e, p)))
        quotes.prices[("RELIANCE", "NSE")] = 1290.0

        # Age it past the stale threshold so it falls back to polling.
        clock.advance(10)
        priced = feed._poll_once()

        assert priced == 1
        assert seen == [("RELIANCE", "NSE", 1290.0)]
    finally:
        feed.stop()


def test_a_price_hook_may_call_back_into_the_feed_without_deadlocking():
    # The hook evaluates risk, which reads prices. If it were invoked while the
    # feed held its own lock, this would hang rather than fail.
    feed, _clock, _ws, _quotes = make_feed()
    feed.add_run_subscriptions(1, [("RELIANCE", "NSE")])
    read_back = []
    feed.set_on_price(lambda s, e, _p: read_back.append(feed.get_ltp(s, e)))

    feed.on_tick(tick("RELIANCE", "NSE", 1287.5))
    feed._drain_ticks_once()

    assert read_back == [1287.5]


def test_a_raising_price_hook_does_not_cost_the_rest_of_the_batch():
    feed, _clock, _ws, _quotes = make_feed()
    feed.add_run_subscriptions(1, [("A", "NSE"), ("B", "NSE")])
    seen = []

    def hook(symbol, _exchange, _price):
        if symbol == "A":
            raise RuntimeError("boom")
        seen.append(symbol)

    feed.set_on_price(hook)
    feed.on_tick(tick("A", "NSE", 1.0))
    feed.on_tick(tick("B", "NSE", 2.0))
    feed._drain_ticks_once()

    assert seen == ["B"]


def test_ticks_are_applied_even_with_no_price_hook_registered():
    feed, _clock, _ws, _quotes = make_feed()
    feed.add_run_subscriptions(1, [("RELIANCE", "NSE")])

    feed.on_tick(tick("RELIANCE", "NSE", 1287.5))
    feed._drain_ticks_once()

    assert feed.get_ltp("RELIANCE", "NSE") == 1287.5
