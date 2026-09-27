# services/tf_momentum_setup_math.py
"""
Pure-math port of the "Momentum Setup: Vijay Thakare Option Buying Scalping
Setup" chart indicator (strategies/indicators/oa-momentum-setup---vijay-
thakare-option-buying-scalping-setup.js), so the same buy/sell signal that
draws a triangle on a chart a trader has open can be computed server-side for
every symbol on the TradeFinder Intraday Boost list, whether or not anyone
has that symbol's chart open.

No I/O here -- services/tf_momentum_setup_service.py owns fetching history
and caching per symbol. This module is one thing: given an ordered list of 5m
bars, decide whether the setup fires long or short on each bar, matching the
chart's own math bar-for-bar.

Every primitive below (sma_seeded_ema, sma, stoch, atr, supertrend) is
transcribed from the openalgo-charts@2.5.1 bundle
(frontend/node_modules/openalgo-charts/dist/*.mjs), not reimplemented from a
textbook formula or delegated to a generic library (pandas .ewm(),
openalgo.ta.*) -- their NaN handling, seeding and warmup edge cases were
checked against the actual chart runtime and diverge from the "usual"
formula in ways that matter for matching what is drawn on screen:

- sma_seeded_ema's seed is the *unfiltered* mean of the first `period` raw
  values -- one NaN in the seed window poisons every value forever, unlike a
  typical from-scratch EMA that would skip NaNs.
- sma is NaN-safe by counting non-finite entries in the rolling window, not
  by skipping them in the running sum.
- stoch returns NaN (not 0 or 50) on an exactly-zero range.
- atr is Wilder's RMA (seed = plain SMA of the first `period` true ranges,
  then a (prev*(n-1)+tr)/n recurrence), not a plain rolling SMA of true
  range.
- supertrend's trend-flip test infers the previous trend from whether the
  previous bar's *chosen value* equalled the previous final-upper-band,
  rather than a stored boolean -- replicated exactly rather than simplified
  to a close-crosses-band check, because the two are not equivalent on every
  bar.

ema_from_first_finite is not an openalgo-charts export at all -- it is
defined inline in the indicator file itself, only for the MACD signal line,
which needs its own seed to start at the first finite value of macdLine
(itself NaN through its own EMA warmup) rather than at index 0.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from utils.logging import get_logger

logger = get_logger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

NAN = float("nan")

DEFAULTS = {
    "st_atr_period": 10,
    "st_factor": 3,
    "macd_fast": 3,
    "macd_slow": 9,
    "macd_signal": 15,
    "stoc_k_len": 5,
    "stoc_k_smooth": 3,
    "stoc_d_smooth": 3,
    "stoc_overbought": 60,
    "stoc_oversold": 40,
}


def sma_seeded_ema(values: list[float], period: int) -> list[float]:
    """EMA seeded from the plain mean of the first `period` raw values (Pine's
    ta.ema seeding). The seed is not NaN-filtered: one NaN in the seed window
    poisons the seed, and the recurrence carries that poison forward forever."""
    n = len(values)
    out = [NAN] * n
    if period <= 0 or n < period:
        return out
    seed = sum(values[0:period]) / period
    out[period - 1] = seed
    alpha = 2 / (period + 1)
    prev = seed
    for i in range(period, n):
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def ema_from_first_finite(values: list[float], period: int) -> list[float]:
    """sma_seeded_ema, but seeded from the first *finite* value of `values`
    rather than index 0 -- used only for the MACD signal line, whose input
    (the MACD line itself) starts with NaNs from its own EMA warmups."""
    n = len(values)
    out = [NAN] * n
    first = 0
    while first < n and not math.isfinite(values[first]):
        first += 1
    if first >= n:
        return out
    tail = sma_seeded_ema(values[first:], period)
    for i, v in enumerate(tail):
        out[first + i] = v
    return out


def sma(values: list[float], period: int) -> list[float]:
    """NaN-safe rolling mean: a window with any non-finite entry outputs NaN
    for that bar (tracked by counting, not by summing NaN and poisoning
    forever the way sma_seeded_ema deliberately does)."""
    n = len(values)
    out = [NAN] * n
    if period <= 0 or n < period:
        return out
    total = 0.0
    nan_count = 0
    for i in range(n):
        v = values[i]
        if math.isfinite(v):
            total += v
        else:
            nan_count += 1
        if i >= period:
            dropped = values[i - period]
            if math.isfinite(dropped):
                total -= dropped
            else:
                nan_count -= 1
        if i >= period - 1:
            out[i] = total / period if nan_count == 0 else NAN
    return out


def _rolling_extreme(values: list[float], length: int, pick) -> list[float]:
    n = len(values)
    out = [NAN] * n
    for i in range(length - 1, n):
        window = values[i - length + 1 : i + 1]
        if any(not math.isfinite(v) for v in window):
            continue
        out[i] = pick(window)
    return out


def stoch(close: list[float], high: list[float], low: list[float], length: int) -> list[float]:
    """Raw %K = 100*(close-lowestLow)/(highestHigh-lowestLow) over `length`
    bars. An exactly-zero range (a flat window) is NaN, not 0 or 50."""
    n = len(close)
    highest = _rolling_extreme(high, length, max)
    lowest = _rolling_extreme(low, length, min)
    out = [NAN] * n
    for i in range(n):
        hh, ll = highest[i], lowest[i]
        if not (math.isfinite(hh) and math.isfinite(ll)):
            continue
        rng = hh - ll
        out[i] = NAN if rng == 0 else 100 * (close[i] - ll) / rng
    return out


def true_range(high: list[float], low: list[float], close: list[float]) -> list[float]:
    n = len(high)
    tr = [0.0] * n
    if n == 0:
        return tr
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    return tr


def atr(high: list[float], low: list[float], close: list[float], period: int = 14) -> list[float]:
    """Wilder's RMA: seed = plain SMA of the first `period` true ranges at
    index period-1, then atr[i] = (atr[i-1]*(period-1) + tr[i]) / period."""
    n = len(high)
    out = [NAN] * n
    if n < period or period <= 0:
        return out
    tr = true_range(high, low, close)
    seed = sum(tr[0:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def supertrend(bars: list[dict], atr_period: int = 10, factor: float = 3) -> list[dict]:
    """Returns one {"value": float, "direction": -1|1} per bar. -1 means the
    bar is in an uptrend, tracked off the ratcheting-up lower band; +1 means a
    downtrend tracked off the ratcheting-down upper band. Bars before ATR
    warms up get {"value": nan, "direction": 1} (the array's own initial
    fill in the source, never overwritten for those bars)."""
    n = len(bars)
    high = [b["high"] for b in bars]
    low = [b["low"] for b in bars]
    close = [b["close"] for b in bars]
    atr_vals = atr(high, low, close, atr_period)

    out: list[dict] = [{"value": NAN, "direction": 1} for _ in range(n)]
    prev_upper = NAN
    prev_lower = NAN
    prev_value = NAN
    started = False

    for i in range(n):
        if not math.isfinite(atr_vals[i]):
            continue
        hl2 = (high[i] + low[i]) / 2
        basic_upper = hl2 + factor * atr_vals[i]
        basic_lower = hl2 - factor * atr_vals[i]

        if started:
            final_upper = (
                basic_upper
                if (basic_upper < prev_upper or close[i - 1] > prev_upper)
                else prev_upper
            )
            final_lower = (
                basic_lower
                if (basic_lower > prev_lower or close[i - 1] < prev_lower)
                else prev_lower
            )
        else:
            final_upper = basic_upper
            final_lower = basic_lower

        if started and prev_value != prev_upper:
            # Previous bar tracked the lower band (uptrend).
            if close[i] >= final_lower:
                value, direction = final_lower, -1
            else:
                value, direction = final_upper, 1
        else:
            # Previous bar tracked the upper band (downtrend), or this is the
            # first bar the state machine has ever seen.
            if close[i] <= final_upper:
                value, direction = final_upper, 1
            else:
                value, direction = final_lower, -1

        out[i] = {"value": value, "direction": direction}
        prev_upper, prev_lower, prev_value, started = final_upper, final_lower, value, True

    return out


def hlc3(bars: list[dict]) -> list[float]:
    return [(b["high"] + b["low"] + b["close"]) / 3 for b in bars]


def ohlc4(bars: list[dict]) -> list[float]:
    return [(b["open"] + b["high"] + b["low"] + b["close"]) / 4 for b in bars]


def _ist_date(epoch_seconds: float) -> date:
    return datetime.fromtimestamp(epoch_seconds, tz=IST).date()


def daily_vwap(bars: list[dict]) -> list[float]:
    """VWAP anchored to the IST calendar day (the indicator's default '1D'
    anchor). A missing volume is NaN, which -- left unfiltered, exactly as
    the source does -- poisons the running sums for the rest of that day."""
    n = len(bars)
    out = [NAN] * n
    h3 = hlc3(bars)
    sum_pv = 0.0
    sum_v = 0.0
    prev_day: date | None = None
    for i, b in enumerate(bars):
        day = _ist_date(b["time"])
        if prev_day is None or day != prev_day:
            sum_pv = 0.0
            sum_v = 0.0
        vol = b.get("volume")
        vol = vol if (vol is not None and math.isfinite(vol)) else NAN
        sum_pv += h3[i] * vol
        sum_v += vol
        out[i] = sum_pv / sum_v if sum_v > 0 else NAN
        prev_day = day
    return out


def _continuous_trigger(cond1: list[bool], cond2: list[bool]) -> list[int]:
    """The Continuous-mode two-step arm/fire state machine shared by both the
    long and short sides: cond1 arms, cond2 (while armed) fires, firing
    re-arms on the next bar. Run forward once over the whole array -- this is
    the entire mechanism that carries a setup "arming" near yesterday's close
    into today's early bars: the state has no notion of a day boundary, only
    of array position, so feeding it one continuous multi-day bar list is
    the whole answer."""
    state = 0
    out = [0] * len(cond1)
    for i in range(len(cond1)):
        if state == 2:
            state = 0
        if cond1[i] and state == 0:
            state = 1
        if cond2[i] and state == 1:
            state = 2
        out[i] = 1 if state == 2 else 0
    return out


def momentum_setup_signals(bars: list[dict], settings: dict | None = None) -> dict:
    """Orchestrates the indicator's calc(): Supertrend, daily VWAP, MACD
    3/9/15 and Stochastic 5/3/3 (the indicator's own defaults -- the ones the
    user actually applied to the chart) feed the entry conditions, and the
    Continuous-mode state machine decides whether long/short fires on each
    bar. EMAs 20/50/100/200 are display-only in the source and are not
    computed here. Every "Additional Filter" (ATR/body/body-size/volume/
    relative-volume/time) is off by default and stays off -- only Continuous
    mode is ported, not Flip.

    bars: ordered list of {"time": epoch_seconds, "open", "high", "low",
    "close", "volume"} dicts, oldest first. Feed a multi-day continuous
    series (not "just today") so the arm/fire state has already settled past
    warmup noise and can carry an in-progress setup across the day boundary.

    Returns per-bar arrays; `long_trigger[-1]`/`short_trigger[-1]` on the
    most recently closed bar is what the caller treats as "signaling right
    now"."""
    s = {**DEFAULTS, **(settings or {})}
    n = len(bars)
    out = {
        "long_trigger": [0] * n,
        "short_trigger": [0] * n,
        "macd": [NAN] * n,
        "signal": [NAN] * n,
        "hist": [NAN] * n,
        "stoc_k": [NAN] * n,
        "stoc_d": [NAN] * n,
        "supertrend_value": [NAN] * n,
        "supertrend_direction": [1] * n,
        "vwap": [NAN] * n,
    }
    if n == 0:
        return out

    close = [b["close"] for b in bars]
    high = [b["high"] for b in bars]
    low = [b["low"] for b in bars]

    macd_fast = sma_seeded_ema(close, s["macd_fast"])
    macd_slow = sma_seeded_ema(close, s["macd_slow"])
    macd_line = [
        macd_fast[i] - macd_slow[i]
        if math.isfinite(macd_fast[i]) and math.isfinite(macd_slow[i])
        else NAN
        for i in range(n)
    ]
    signal_line = ema_from_first_finite(macd_line, s["macd_signal"])
    hist_line = [
        macd_line[i] - signal_line[i]
        if math.isfinite(macd_line[i]) and math.isfinite(signal_line[i])
        else NAN
        for i in range(n)
    ]

    stoc_k_raw = stoch(close, high, low, s["stoc_k_len"])
    stoc_k = sma(stoc_k_raw, s["stoc_k_smooth"])
    stoc_d = sma(stoc_k, s["stoc_d_smooth"])

    st = supertrend(bars, s["st_atr_period"], s["st_factor"])
    st_value = [p["value"] for p in st]

    vwap = daily_vwap(bars)

    short_cond1 = [False] * n
    short_cond2 = [False] * n
    long_cond1 = [False] * n
    long_cond2 = [False] * n

    for i in range(n):
        macd, sig, hist = macd_line[i], signal_line[i], hist_line[i]
        k, d = stoc_k[i], stoc_d[i]
        stv, anchor, c = st_value[i], vwap[i], close[i]

        core_finite = all(math.isfinite(x) for x in (macd, sig, hist, k, d, stv, anchor, c))

        short_cond1[i] = core_finite and macd > 0
        long_cond1[i] = core_finite and macd < 0

        short_cond2[i] = (
            core_finite
            and c < stv
            and c < anchor
            and k < s["stoc_overbought"]
            and k < d
            and macd < 0
            and macd < sig
            and macd < hist
        )
        long_cond2[i] = (
            core_finite
            and c > stv
            and c > anchor
            and k > s["stoc_oversold"]
            and k > d
            and macd > 0
            and macd > sig
            and macd > hist
        )

        out["macd"][i] = macd
        out["signal"][i] = sig
        out["hist"][i] = hist
        out["stoc_k"][i] = k
        out["stoc_d"][i] = d
        out["supertrend_value"][i] = stv
        out["supertrend_direction"][i] = st[i]["direction"]
        out["vwap"][i] = anchor

    out["short_trigger"] = _continuous_trigger(short_cond1, short_cond2)
    out["long_trigger"] = _continuous_trigger(long_cond1, long_cond2)
    return out


def _demo() -> None:
    """Self-check, no I/O. Each primitive against a hand-computed expected
    value, plus the two behaviors the whole feature depends on: the
    zero-range-is-NaN guard (not 0/50) and the arm/fire state carrying an
    "armed near yesterday's close" setup across an arbitrary array boundary
    -- which is what carrying it across a day boundary actually reduces to,
    since the state machine has no day concept at all."""

    # sma_seeded_ema: seed = mean(1,2,3)=2 @ idx2, alpha=2/4=0.5.
    out = sma_seeded_ema([1, 2, 3, 4, 5], 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert math.isclose(out[2], 2.0)
    assert math.isclose(out[3], 3.0)  # 4*0.5 + 2*0.5
    assert math.isclose(out[4], 4.0)  # 5*0.5 + 3*0.5

    # A NaN in the seed window poisons every value forever.
    out = sma_seeded_ema([1, float("nan"), 3, 4, 5], 3)
    assert all(math.isnan(v) for v in out[2:])

    # ema_from_first_finite: seeds from the first finite value, not index 0.
    out = ema_from_first_finite([float("nan"), float("nan"), 1, 2, 3, 4, 5], 3)
    assert math.isnan(out[3])
    assert math.isclose(out[4], 2.0)
    assert math.isclose(out[5], 3.0)
    assert math.isclose(out[6], 4.0)

    # sma: NaN-safe by counting, not summing -- one gap blanks every window
    # it falls inside, not just the bar it's on.
    out = sma([1, 2, float("nan"), 4, 5], 3)
    assert all(math.isnan(v) for v in out[2:])
    out = sma([1, 2, 3, 4, 5], 3)
    assert math.isclose(out[2], 2.0)
    assert math.isclose(out[3], 3.0)
    assert math.isclose(out[4], 4.0)

    # stoch: a flat window is NaN, not 0 or 50.
    out = stoch([5, 5, 5, 5], [5, 5, 5, 5], [5, 5, 5, 5], 3)
    assert math.isnan(out[2]) and math.isnan(out[3])
    close = [10, 12, 11, 15, 14]
    out = stoch(close, close, close, 3)
    assert math.isclose(out[2], 50.0)  # (11-10)/(12-10)*100
    assert math.isclose(out[3], 100.0)  # (15-11)/(15-11)*100
    assert math.isclose(out[4], 75.0)  # (14-11)/(15-11)*100

    # atr: Wilder seed then RMA recurrence.
    high = [10, 11, 12, 13, 14, 15]
    low = [8, 9, 9, 10, 11, 12]
    close = [9, 10, 11, 12, 13, 14]
    out = atr(high, low, close, 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert math.isclose(out[2], 7 / 3)
    assert math.isclose(out[3], (7 / 3 * 2 + 3) / 3)
    assert math.isclose(out[4], ((7 / 3 * 2 + 3) / 3 * 2 + 3) / 3)

    # supertrend: strong sustained uptrend ends tracked off the lower band
    # (direction -1); a violent reversal through it flips to +1.
    up_bars = [
        {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i} for i in range(15)
    ]
    st = supertrend(up_bars, atr_period=3, factor=1)
    assert st[-1]["direction"] == -1
    assert math.isfinite(st[-1]["value"])
    crash_bars = up_bars + [{"open": 114, "high": 114, "low": 60, "close": 61}]
    st2 = supertrend(crash_bars, atr_period=3, factor=1)
    assert st2[-1]["direction"] == 1

    # hlc3 / ohlc4.
    bars = [{"open": 1, "high": 3, "low": 1, "close": 2, "volume": 10}]
    assert math.isclose(hlc3(bars)[0], 2.0)
    assert math.isclose(ohlc4(bars)[0], 1.75)

    # daily_vwap: resets across an IST day boundary rather than accumulating
    # through it.
    day1_open = int(datetime(2026, 9, 22, 9, 15, tzinfo=IST).timestamp())
    day2_open = int(datetime(2026, 9, 23, 9, 15, tzinfo=IST).timestamp())
    vwap_bars = [
        {"time": day1_open, "high": 100, "low": 100, "close": 100, "volume": 10},
        {"time": day1_open + 300, "high": 200, "low": 200, "close": 200, "volume": 10},
        {"time": day2_open, "high": 50, "low": 50, "close": 50, "volume": 5},
    ]
    v = daily_vwap(vwap_bars)
    assert math.isclose(v[0], 100.0)
    assert math.isclose(v[1], 150.0)  # (100*10+200*10)/20
    assert math.isclose(v[2], 50.0)  # reset, not (100*10+200*10+50*5)/25

    # The arm/fire state machine: arms on cond1, fires on cond2 while armed,
    # then re-arms. And the case that stands in for day-boundary continuity:
    # arming on the last bar of one segment fires on the very first bar of
    # the next, because the loop never resets between them.
    trig = _continuous_trigger(
        cond1=[False, True, False, False, False, False],
        cond2=[False, False, True, False, False, False],
    )
    assert trig == [0, 0, 1, 0, 0, 0]

    yesterday_close = [False] * 10 + [True] + [False] * 5  # arms at index 10
    today_open = [False] * 11 + [True] + [False] * 4  # fires at index 11
    trig = _continuous_trigger(yesterday_close, today_open)
    assert trig[11] == 1, (
        "a setup armed on the last bar before a boundary must fire on the first bar after it"
    )

    logger.info("tf_momentum_setup_math self-check passed")


if __name__ == "__main__":
    _demo()
