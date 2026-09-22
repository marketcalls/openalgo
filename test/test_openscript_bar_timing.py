"""When a run looks for the bar it is about to trade on.

**The defect this file is about.** A run polling on a free running timer finds a
closed bar somewhere inside the next poll interval, so an order decided at the
close of one bar reaches the platform part way through the bar after it. A
strategy's own backtest prices that fill at the next bar's open, so every live
fill is worse than the report by however far the price moved while the run was
asleep.

That is the shape that makes it worth fixing: it is not noise. It is the same
lateness every time, in the same direction, and it grows with the poll interval.
Observed live at about forty five seconds on a one minute bar.
"""

import pytest

from openscript_host.openscript_runner import (
    CATCHUP_SECONDS,
    RETRY_LATER,
    RETRY_SOON,
    RETRY_SOON_WINDOW,
    SETTLE_SECONDS,
    interval_seconds,
    next_wake,
)

# ---------------------------------------------------------------------------
# Reading the interval
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interval,seconds",
    [("1m", 60), ("3m", 180), ("5m", 300), ("15m", 900), ("1h", 3600), ("30s", 30)],
)
def test_an_interval_this_platform_sends_is_read(interval, seconds):
    assert interval_seconds(interval) == seconds


@pytest.mark.parametrize("interval", ["D", "W", "M", "", "daily", "1d", "x", "0m", "-5m", None])
def test_anything_else_answers_zero_rather_than_a_guess(interval):
    """THE SAFE ANSWER, and it is not a fallback.

    Zero means "keep the ordinary cadence". A run must never sleep towards a
    boundary it has guessed: a daily bar's next boundary is hours away, and a
    run that slept to a guessed one would stop looking at the market for the
    afternoon.
    """
    assert interval_seconds(interval) == 0


# ---------------------------------------------------------------------------
# When to look again
# ---------------------------------------------------------------------------

MINUTE = 60
POLL = 15.0


def test_the_wake_lands_just_after_the_bar_closes():
    """THE WHOLE POINT. The order goes out on the bar it was decided on.

    From within a poll interval of the close, so the cadence ceiling is not what
    decides it. `test_repeated_wakes_converge_on_the_boundary` covers arriving
    from further out.
    """
    now = 1_000_000 * MINUTE + (MINUTE - 5)
    sleeping = next_wake(now, MINUTE, POLL, None)

    landed = (now + sleeping) % MINUTE
    assert landed == pytest.approx(SETTLE_SECONDS)


def test_a_wake_just_before_the_settle_point_waits_for_it():
    """THE SLIP THIS ALMOST SHIPPED WITH.

    A wake landing one second after a close, before the settle offset, must aim
    at that settle point and not at the next bar's. Aiming ahead jumps over the
    bar it was waiting for, and with the cadence as a ceiling the run never
    lands on a settle point at all: the alignment silently never happens and
    every order is as late as it was before.
    """
    # Just inside the settle offset, whatever that offset happens to be, so the
    # case is about the rule and not about the number.
    now = float(1_000_000 * MINUTE) + SETTLE_SECONDS / 2

    assert next_wake(now, MINUTE, POLL, None) == pytest.approx(SETTLE_SECONDS / 2)


def test_it_never_sleeps_past_the_ordinary_cadence():
    """The bar still forming has to stay fresh, and a daily boundary is hours off.

    Catches a wake that only ever targets the boundary: a run one second into a
    minute would then not look at the market again for fifty nine seconds, and a
    script reading the moving bar would see it stop moving.
    """
    now = 1_000_000 * MINUTE + 1
    assert next_wake(now, MINUTE, POLL, None) <= POLL


def test_an_interval_it_cannot_read_keeps_the_ordinary_cadence():
    now = 1_000_000 * MINUTE + 13
    assert next_wake(now, 0, POLL, None) == POLL


def test_the_wake_is_never_negative():
    """Catches an arithmetic slip putting a boundary in the past.

    A negative sleep is a spin: the loop would poll the platform as fast as it
    could answer, for the life of the run.
    """
    for offset in range(0, MINUTE):
        assert next_wake(1_000_000 * MINUTE + offset, MINUTE, POLL, None) >= 0


def test_every_bar_gets_a_wake_just_after_it_closes():
    """Walk the loop forward and check no close is missed.

    Not every wake sits on a close, and it must not: the ordinary cadence keeps
    the forming bar fresh in between. What matters is that each close gets one,
    because that is the wake an order rides out on. Catches a calculation that
    is right once and then drifts past a boundary, which is the shape that gives
    back the lateness this exists to remove.
    """
    now = float(1_000_000 * MINUTE + 1)
    landings = []
    for _ in range(40):
        now += next_wake(now, MINUTE, POLL, None)
        landings.append(now)

    settled = [one for one in landings if one % MINUTE == pytest.approx(SETTLE_SECONDS)]
    covered = {int(one // MINUTE) for one in settled}
    minutes = {int(one // MINUTE) for one in landings}

    # Every minute the walk passed through was looked at just after it closed.
    # The first and last are dropped: the walk starts inside one and ends inside
    # another, so neither is a whole minute this loop covered.
    assert covered >= set(sorted(minutes)[1:-1])
    assert len(settled) >= 5, 'the walk never landed on a close at all'


def test_a_late_feed_is_retried_quickly_rather_than_waited_out():
    """Catches a whole interval lost to a bar published a moment late.

    The wake is deliberately soon after the close, so the bar is often not there
    on the first look. Falling back to the ordinary cadence then would give away
    most of what this buys, and every tenth of a second of it is slippage on the
    order about to go out.
    """
    now = float(1_000_000 * MINUTE) + SETTLE_SECONDS
    assert next_wake(now, MINUTE, POLL, waiting_since=now) <= RETRY_SOON


def test_the_retry_slows_down_once_the_bar_is_properly_late():
    """A fetch answering with nothing is one this run pays for and learns
    nothing from, so asking four times a second stops being worth it."""
    began = float(1_000_000 * MINUTE)
    later = began + RETRY_SOON_WINDOW + 1

    assert next_wake(later, MINUTE, POLL, waiting_since=began) == pytest.approx(RETRY_LATER)


def test_the_first_look_is_soon_enough_to_matter():
    """A guard on the number itself.

    Two seconds of price movement on a liquid instrument is a real cost against
    a fill the backtest priced at the bar's open. It cannot be zero either: a
    poll reads the whole history window and the feed does not publish a closed
    bar on the instant, so looking at the exact boundary usually costs a full
    fetch to learn the bar is not there yet.
    """
    assert 0 < SETTLE_SECONDS <= 0.5


def test_the_quick_retry_gives_up_rather_than_spinning():
    """A bar that never comes must not be asked for every two seconds all day.

    A halt, a holiday or an instrument that stopped trading. After the catch-up
    window the run goes back to its ordinary cadence.
    """
    began = float(1_000_000 * MINUTE)
    late = began + CATCHUP_SECONDS + 1

    assert next_wake(late, MINUTE, POLL, waiting_since=began) > RETRY_LATER


def test_the_retry_still_respects_the_cadence_ceiling():
    assert next_wake(1_000_000 * MINUTE, MINUTE, 1.0, waiting_since=1_000_000 * MINUTE) <= 1.0


@pytest.mark.parametrize("bar", [60, 180, 300, 900, 3600])
def test_every_intraday_interval_lands_on_its_own_boundary(bar):
    """Catches a boundary worked out against the wrong unit."""
    now = float(1_000_000 * 3600 + 7)
    now += next_wake(now, bar, float(bar), None)

    assert now % bar == pytest.approx(SETTLE_SECONDS)
