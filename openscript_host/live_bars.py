"""Bars built from the live feed, the way the chart builds the candle in front.

**Why a run cannot wait for history.** A broker's history endpoint does not
carry a bar the moment it closes. On this platform a closed one minute bar was
measured arriving about thirty five seconds after its close, and a broker that
publishes only on the candle's close can be later still. A run that learns a bar
has closed by asking for history therefore acts most of a bar late, and on a one
minute strategy most of a bar is most of the move. It is not noise: it is the
same lateness every time, in the same direction, so it comes off every fill.

**The chart has never had that problem.** It draws history for the settled past
and builds the bar in front of it from the live feed, so the moment a bar closes
its own numbers are already complete. This is that arrangement for a run:
history is what a run is replayed on and what it is reconciled against, and the
feed is what closes a bar.

**A bucket this did not watch from its start is never handed over, and that is
the whole safety.** A subscription begins part way through a bar, so that
bucket's open is whatever price happened to arrive next and its volume has no
baseline to be counted from. Handing it over would put a bar into the engine
that no exchange ever traded. Only a bucket whose own boundary this watched pass
is a bar, which means a run acts on the feed from the second boundary after it
subscribed, and on history until then.

**Nothing here decides anything.** It buckets ticks and answers which buckets
have ended. Whether a run acts on them is the runner's, and a run whose feed
never connects or never publishes is the run this platform had before, driven by
history at its own cadence.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

#: How long after a bucket ends to treat it as closed.
#:
#: A tick carrying the last trade of a bar can be delivered a moment after the
#: boundary, and a bar handed over without it is a bar missing its own close.
#: Small enough not to be the lateness this module exists to remove: a fifth of
#: a second, against the thirty five seconds history was measured at.
SETTLE_SECONDS = 0.2

#: How many closed buckets to keep if nothing collects them. A run collects
#: every one it is woken for, so this only fills when a run is stopped or stuck,
#: and it is here so that a feed publishing into a run that has gone away cannot
#: grow without limit.
KEEP_CLOSED = 64

#: One bar as this hands it over: open instant in milliseconds, then the four
#: prices and the volume. A plain tuple, so this module does not have to know
#: the runner's own bar type and the runner does not have to import this one.
Bar = tuple


class Bucket:
    """One bar being built from ticks, and what it was built from."""

    __slots__ = ("time", "open", "high", "low", "close", "baseline", "volume_now", "whole", "ticks")

    def __init__(self, time_ms: int, price: float, volume: float | None, baseline: float | None, whole: bool) -> None:
        self.time = time_ms
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        #: The cumulative volume the feed had reported when the bar before this
        #: one ended. A feed counts the whole day, so a bar's own volume is the
        #: difference between its last reading and this. None until the feed has
        #: reported one, which makes the volume nothing rather than wrong.
        self.baseline = baseline
        self.volume_now = volume
        #: Whether this bucket's own opening boundary was watched. A bucket that
        #: began part way through a bar is not a bar.
        self.whole = whole
        self.ticks = 1

    def add(self, price: float, volume: float | None) -> None:
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close = price
        if volume is not None:
            self.volume_now = volume
        self.ticks += 1

    def traded(self) -> float:
        """This bar's own volume, or zero where the feed has not said."""
        if self.volume_now is None or self.baseline is None:
            return 0.0
        return max(0.0, self.volume_now - self.baseline)

    def bar(self) -> Bar:
        return (self.time, self.open, self.high, self.low, self.close, self.traded())


class LiveBars:
    """The feed for one instrument, as bars.

    Built and stopped by the runner. ``start`` says whether there is a feed to
    be had at all, and a run whose answer is False is driven by history exactly
    as it was before this existed.
    """

    def __init__(
        self,
        client: Any,
        symbol: str,
        exchange: str,
        bar_seconds: int,
        say: Callable[[str], None],
    ) -> None:
        self.client = client
        self.symbol = symbol
        self.exchange = exchange
        self.bar_seconds = bar_seconds
        self.say = say

        # The feed publishes on its own thread, so everything below is read and
        # written under this. A real lock, because this process is not the
        # cooperatively scheduled worker: it is a plain subprocess with plain
        # threads.
        self._lock = threading.Lock()
        self._forming: Bucket | None = None
        self._closed: list[Bucket] = []
        #: The cumulative volume at the end of the most recently closed bucket,
        #: which is the baseline the next bar's volume is counted from.
        self._volume_mark: float | None = None
        #: Whether a bucket boundary has been watched pass. Until one has, the
        #: bucket in hand began part way through a bar and is not one.
        self._seen_boundary = False
        self._connected = False
        self._subscribed = False
        self._ticks = 0

    # -- the feed -----------------------------------------------------------

    def start(self) -> bool:
        """Connect and subscribe. False when this run stays on history.

        Nothing here raises. A feed that cannot be reached is a run that is
        slower, and a run that will not start at all because of it is a run that
        does not trade.
        """
        if self.bar_seconds <= 0:
            # A daily bar has no boundary worth watching this way, and an
            # interval this runner does not recognise has none at all.
            return False

        try:
            if not self.client.connect():
                self.say(
                    "The live feed did not connect, so this run reads each closed bar from "
                    "history instead. It will act on a bar later than it could."
                )
                return False
            self._connected = True
        except Exception as unreachable:  # noqa: BLE001 - a feed is optional
            self.say(
                "The live feed could not be reached, so this run reads each closed bar from "
                f"history instead. It will act on a bar later than it could. ({unreachable})"
            )
            return False

        try:
            self._subscribed = bool(
                self.client.subscribe_quote(
                    [{"exchange": self.exchange, "symbol": self.symbol}],
                    on_data_received=self._on_message,
                )
            )
        except Exception as refused:  # noqa: BLE001 - a feed is optional
            self.say(
                "The live feed would not carry this instrument, so this run reads each closed "
                f"bar from history instead. ({refused})"
            )
            self._subscribed = False

        if not self._subscribed:
            # Refused rather than raised, which reads at a glance like a
            # connection that worked. A run told nothing here is a run acting a
            # bar late with no line in its log saying why.
            self.say(
                f"The live feed would not carry {self.symbol}, so this run reads each closed bar "
                "from history instead. It will act on a bar later than it could."
            )
            return False

        self.say(
            f"Watching {self.symbol} on the live feed, so a bar closes here rather than when "
            "history catches up. The bar this joins part way through is read from history, "
            "because a subscription does not begin at a bar's open."
        )
        return True

    def stop(self) -> None:
        """Unsubscribe and disconnect. Never raises: this runs on the way out."""
        try:
            if self._subscribed:
                self.client.unsubscribe_quote([{"exchange": self.exchange, "symbol": self.symbol}])
        except Exception:  # noqa: BLE001 - the process is leaving
            pass
        try:
            if self._connected:
                self.client.disconnect()
        except Exception:  # noqa: BLE001 - the process is leaving
            pass
        self._subscribed = False
        self._connected = False

    def _on_message(self, message: Any) -> None:
        """One publication from the feed. Runs on the feed's own thread.

        Nothing raises out of here. It is called by somebody else's thread, and
        an exception crossing that boundary either kills the feed or surfaces
        somewhere nobody will read it.
        """
        try:
            self._accept(message)
        except Exception:  # noqa: BLE001 - never fault the feed's thread
            return

    def _accept(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        # One connection carries every instrument this process subscribed to, so
        # a publication for another one is not this run's bar.
        if message.get("symbol") and message.get("symbol") != self.symbol:
            return
        if message.get("exchange") and message.get("exchange") != self.exchange:
            return

        data = message.get("data")
        if not isinstance(data, dict):
            return

        price = _number(data.get("ltp"))
        if price is None or price <= 0:
            # A publication with no traded price says nothing about a bar. The
            # day's open, high and low are in the same message and are the day's
            # rather than this bar's, so none of them stands in for it.
            return

        stamp = _instant(data.get("timestamp"))
        if stamp is None:
            return

        volume = _number(data.get("volume"))
        span = self.bar_seconds * 1000
        opened = (stamp // span) * span

        with self._lock:
            self._ticks += 1
            forming = self._forming

            if forming is not None and opened == forming.time:
                forming.add(price, volume)
                return

            if forming is not None and opened < forming.time:
                # A tick older than the bucket in hand: out of order, or a feed
                # republishing. It cannot reopen a bucket, because a bar the
                # engine has already acted on must not change behind it.
                return

            if forming is not None:
                self._retire(forming)
            self._forming = Bucket(opened, price, volume, self._volume_mark, self._seen_boundary)

    def _retire(self, bucket: Bucket) -> None:
        """Finish a bucket. Called holding the lock.

        A bucket that was not watched from its own start is dropped rather than
        handed over, but its last reading is still kept: it is the baseline the
        next bar's volume is counted from, which is the one useful thing a
        partial bucket has.
        """
        if bucket.whole:
            self._closed.append(bucket)
            del self._closed[:-KEEP_CLOSED]
        if bucket.volume_now is not None:
            self._volume_mark = bucket.volume_now
        self._seen_boundary = True

    # -- what a run reads ---------------------------------------------------

    def closed(self, now_ms: int) -> list[Bar]:
        """Every bucket that has ended, oldest first, each answered once.

        A bucket ends when the clock has passed its boundary by the settle
        offset, whether or not a tick has arrived since: a bar with no trade in
        the minute after it still closed.
        """
        with self._lock:
            forming = self._forming
            if forming is not None and now_ms >= _ends(forming, self.bar_seconds):
                self._retire(forming)
                self._forming = None

            taken, self._closed = self._closed, []
            return [bucket.bar() for bucket in taken]

    def forming(self, now_ms: int) -> Bar | None:
        """The bar still being built, or nothing.

        Only ever a whole one, and only while it is still inside its own span. A
        bucket past its boundary belongs to ``closed``, which has not been asked
        yet; answering it here as well would hand the same bar over twice, once
        as the moving bar and once as a closed one.
        """
        with self._lock:
            forming = self._forming
            if forming is None or not forming.whole:
                return None
            if now_ms >= _ends(forming, self.bar_seconds):
                return None
            return forming.bar()

    @property
    def live(self) -> bool:
        """Whether this is subscribed and has been told anything at all.

        A subscription that has published nothing is not a feed a run can close
        a bar on, so the run keeps history's cadence until the first tick.
        """
        with self._lock:
            return self._subscribed and self._ticks > 0


def _ends(bucket: Bucket, bar_seconds: int) -> int:
    """The instant this bucket counts as closed, in milliseconds."""
    return bucket.time + bar_seconds * 1000 + int(SETTLE_SECONDS * 1000)


def _number(value: Any) -> float | None:
    """A field as a number, or nothing. A feed may send a string or a null."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _instant(value: Any) -> int | None:
    """A feed timestamp as whole milliseconds since the epoch, UTC.

    A feed may count in seconds or in milliseconds. They are told apart by size
    rather than by configuration: seconds since the epoch is a ten digit number
    for the next two centuries and milliseconds is thirteen, so anything below
    the threshold is seconds. Getting this wrong puts every bar in 1970 or fifty
    thousand years out, which is not a subtle failure.
    """
    number = _number(value)
    if number is None or number <= 0:
        return None
    return int(number * 1000) if number < 100_000_000_000 else int(number)
