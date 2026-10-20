"""
Strike Profile Service

Gamma exposure (GEX) and delta exposure (DEX) per strike, for every selected
expiry at once, so the two can be read as a strike by expiry grid.

Units, chosen so that every cell in the grid is in the same currency and can
be compared across expiries:

    GEX = gamma * OI * spot^2 * 0.01 / 1e7
        Rupees, in crore, that hedgers would trade for a 1% move in the
        underlying. Calls count positive and puts negative, the usual
        convention that the dealer is long the calls and short the puts.

    DEX = (call_delta * call_OI + put_delta * put_OI) * spot / 1e7
        Delta-weighted notional of the open interest, in rupees crore. Put
        delta is already negative, so no sign is imposed.

OI is the broker's open interest in units (quantity), the same figure every
other OI tool divides by the lot size to show lots.

Raw rupee values are not like for like across expiries on their own: a
near-dated strike carries far more gamma than the same strike weeks out, so a
heatmap of raw values only ever shows today's expiry. The payload therefore
carries each expiry's days to expiry and the UI marks each expiry's own peaks,
so a level that matters on a far expiry is visible next to a near one.

Summary levels:

    flip   The underlying price at which total GEX across the selected expiries
           changes sign, found by re-pricing every leg's gamma (Black-76, its
           own IV held fixed) over a grid of hypothetical spot prices. None
           when there is no sign change inside the loaded strike range.
    call_wall / put_wall
           The strike with the most call GEX / put GEX across the selected
           expiries.

Greeks come from the option chain service's single vectorized Black-76 pass
(forward from the chain's own put-call parity), so the only broker calls are
one option chain fetch per expiry.
"""

import math
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from services.broker_busy import is_broker_busy
from services.option_chain_service import get_option_chain
from utils.logging import get_logger

logger = get_logger(__name__)

INDIA_TZ = ZoneInfo("Asia/Kolkata")

# One crore. Exposures are reported in rupees crore.
CRORE = 1e7

# Strikes fetched either side of ATM when no price window is given, and the
# ceiling on any window. 40 a side is 162 symbols per expiry, the same order as
# the largest chain the other tools request.
DEFAULT_STRIKE_COUNT = 20
MAX_STRIKE_COUNT = 40

# Hypothetical spot prices tried when searching for the gamma flip.
FLIP_GRID_POINTS = 241

_SECONDS_PER_YEAR = 365.0 * 86400.0

# Matches calculate_time_to_expiry(): below about an hour Black-76 is unstable.
_MIN_YEARS = 0.0001


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _leg_exposure(leg: dict[str, Any] | None, spot: float, sign: float) -> dict[str, Any]:
    """
    GEX and DEX contributed by one option leg.

    Args:
        leg: Chain leg (ce or pe) with oi and, when computable, gamma and delta
        spot: Underlying price
        sign: +1 for calls, -1 for puts (GEX dealer convention)

    Returns:
        Dict with oi, gex, dex, iv and whether the Greeks were available
    """
    if not leg:
        return {"oi": 0, "gex": 0.0, "dex": 0.0, "iv": 0.0, "priced": False}

    oi = leg.get("oi") or 0
    has_greeks = "gamma" in leg and "delta" in leg
    gamma = leg.get("gamma") or 0.0
    delta = leg.get("delta") or 0.0
    gex = sign * gamma * oi * spot * spot * 0.01 / CRORE
    dex = delta * oi * spot / CRORE
    return {
        "oi": oi,
        "gex": gex,
        "dex": dex,
        "iv": leg.get("implied_volatility") or 0.0,
        "priced": has_greeks,
    }


def _expiry_years(chain_response: dict[str, Any]) -> float:
    """Time to expiry in years from the chain's own expiry and server timestamps."""
    expiry_ts = chain_response.get("expiry_ts")
    server_ts = chain_response.get("server_ts") or datetime.now(UTC).timestamp()
    if not expiry_ts:
        return 0.0
    return max((expiry_ts - server_ts) / _SECONDS_PER_YEAR, 0.0)


def _calendar_dte(expiry_ts: int | None) -> int | None:
    """Whole calendar days from today (IST) to the expiry date."""
    if not expiry_ts:
        return None
    expiry_day = datetime.fromtimestamp(expiry_ts, INDIA_TZ).date()
    today = datetime.now(INDIA_TZ).date()
    return max((expiry_day - today).days, 0)


def find_gamma_flip(
    legs: list[tuple[float, float, float, float, float, float]],
    spot: float,
    low: float,
    high: float,
    points: int = FLIP_GRID_POINTS,
) -> float | None:
    """
    Spot price at which total GEX changes sign.

    Each leg's forward moves in proportion to spot, its IV is held fixed, and
    its gamma is re-priced with Black-76 at every grid point.

    Args:
        legs: (strike, forward, years, iv_decimal, oi, sign) per option leg
        spot: Current underlying price, used to scale each forward
        low: Lowest hypothetical spot to try
        high: Highest hypothetical spot to try
        points: Grid size

    Returns:
        The crossing nearest to spot, linearly interpolated, or None
    """
    if not legs or spot <= 0 or low <= 0 or high <= low:
        return None

    try:
        import numpy as np
        from opengreeks import black76
    except ImportError:
        logger.error("opengreeks not installed; gamma flip unavailable")
        return None

    strikes = np.asarray([leg[0] for leg in legs], dtype=float)
    forwards = np.asarray([leg[1] for leg in legs], dtype=float)
    years = np.asarray([leg[2] for leg in legs], dtype=float)
    sigmas = np.asarray([leg[3] for leg in legs], dtype=float)
    weights = np.asarray([leg[4] * leg[5] for leg in legs], dtype=float)

    grid = np.linspace(low, high, points)
    totals = np.zeros(points)
    for i, price in enumerate(grid):
        try:
            gammas = black76.gamma_array(
                "c", forwards * (price / spot), strikes, years, 0.0, sigmas
            )
        except Exception:
            logger.exception("Gamma re-pricing failed during the flip search")
            return None
        gammas = np.nan_to_num(np.asarray(gammas, dtype=float))
        totals[i] = float(np.dot(gammas, weights)) * price * price

    best = None
    for i in range(points - 1):
        a, b = totals[i], totals[i + 1]
        if a == 0:
            crossing = float(grid[i])
        elif (a < 0) != (b < 0) and b != 0:
            crossing = float(grid[i] + (grid[i + 1] - grid[i]) * (-a) / (b - a))
        else:
            continue
        if best is None or abs(crossing - spot) < abs(best - spot):
            best = crossing
    return best


def _strike_count_for_window(
    chain_response: dict[str, Any], spot: float, range_pct: float | None
) -> int:
    """Strikes a side needed to cover spot +/- range_pct, from a probe chain."""
    if not range_pct:
        return MAX_STRIKE_COUNT
    strikes = sorted({row["strike"] for row in chain_response.get("chain", [])})
    if len(strikes) < 2:
        return DEFAULT_STRIKE_COUNT
    steps = [b - a for a, b in zip(strikes, strikes[1:], strict=False) if b > a]
    step = min(steps) if steps else 0
    if step <= 0:
        return DEFAULT_STRIKE_COUNT
    needed = math.ceil(spot * range_pct / 100.0 / step) + 1
    return max(5, min(needed, MAX_STRIKE_COUNT))


def get_strike_profile(
    underlying: str,
    exchange: str,
    expiry_dates: list[str],
    api_key: str,
    range_pct: float | None = 5.0,
) -> tuple[bool, dict[str, Any], int]:
    """
    GEX and DEX for every strike of every requested expiry.

    Args:
        underlying: Underlying symbol (e.g. NIFTY)
        exchange: Exchange as the other option tools take it (NFO, BFO, ...)
        expiry_dates: Expiries in DDMMMYY format, nearest first
        api_key: OpenAlgo API key
        range_pct: Load strikes within spot +/- this percent; None loads the
            widest window (MAX_STRIKE_COUNT a side)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not expiry_dates:
            return False, {"status": "error", "message": "Select at least one expiry."}, 400

        spot: float | None = None
        expiries_out: list[dict[str, Any]] = []
        rows_by_expiry: list[dict[float, dict[str, Any]]] = []
        flip_legs: list[tuple[float, float, float, float, float, float]] = []
        all_strikes: set[float] = set()
        strike_count = DEFAULT_STRIKE_COUNT
        server_ts = None

        for index, expiry in enumerate(expiry_dates):
            success, chain_response, status_code = get_option_chain(
                underlying=underlying,
                exchange=exchange,
                expiry_date=expiry,
                strike_count=strike_count,
                api_key=api_key,
                with_greeks=True,
            )

            if not success:
                if is_broker_busy(status_code):
                    return False, chain_response, status_code
                if index == 0:
                    return False, chain_response, status_code
                logger.warning(
                    f"Strike profile: skipping {underlying} {expiry}: {chain_response.get('message')}"
                )
                expiries_out.append(
                    {
                        "expiry": expiry,
                        "expiry_ts": None,
                        "dte": None,
                        "available": False,
                        "message": "No option data for this expiry.",
                    }
                )
                rows_by_expiry.append({})
                continue

            if spot is None:
                spot = chain_response.get("underlying_ltp")
                if not spot or spot <= 0:
                    return (
                        False,
                        {"status": "error", "message": "The underlying price is not available."},
                        404,
                    )
                server_ts = chain_response.get("server_ts")
                # The first chain doubles as a probe for the strike step. When
                # the window needs more strikes than it loaded, fetch it again.
                wanted = _strike_count_for_window(chain_response, spot, range_pct)
                if wanted > strike_count:
                    strike_count = wanted
                    success, refetched, status_code = get_option_chain(
                        underlying=underlying,
                        exchange=exchange,
                        expiry_date=expiry,
                        strike_count=strike_count,
                        api_key=api_key,
                        with_greeks=True,
                    )
                    if not success:
                        return False, refetched, status_code
                    chain_response = refetched
                else:
                    strike_count = wanted

            years = _expiry_years(chain_response)
            forward = chain_response.get("forward_price") or spot
            expiry_ts = chain_response.get("expiry_ts")

            rows: dict[float, dict[str, Any]] = {}
            total_gex = 0.0
            total_dex = 0.0
            for row in chain_response.get("chain", []):
                strike = row.get("strike")
                if not isinstance(strike, (int, float)) or strike <= 0:
                    continue
                ce = _leg_exposure(row.get("ce"), spot, 1.0)
                pe = _leg_exposure(row.get("pe"), spot, -1.0)
                gex = ce["gex"] + pe["gex"]
                dex = ce["dex"] + pe["dex"]
                # Open interest with no Greeks to weight it is unknown, not zero.
                unpriced = (ce["oi"] > 0 and not ce["priced"]) or (
                    pe["oi"] > 0 and not pe["priced"]
                )
                rows[float(strike)] = {
                    "ce_oi": ce["oi"],
                    "pe_oi": pe["oi"],
                    "ce_gex": _round(ce["gex"], 4),
                    "pe_gex": _round(pe["gex"], 4),
                    "ce_dex": _round(ce["dex"], 4),
                    "pe_dex": _round(pe["dex"], 4),
                    "gex": _round(gex, 4),
                    "dex": _round(dex, 4),
                    "unpriced": unpriced,
                }
                all_strikes.add(float(strike))
                total_gex += gex
                total_dex += dex

                if years > 0:
                    for leg, sign in ((ce, 1.0), (pe, -1.0)):
                        if leg["oi"] > 0 and leg["priced"] and leg["iv"] > 0:
                            flip_legs.append(
                                (
                                    float(strike),
                                    float(forward),
                                    max(years, _MIN_YEARS),
                                    leg["iv"] / 100.0,
                                    float(leg["oi"]),
                                    sign,
                                )
                            )

            lot_size = None
            for row in chain_response.get("chain", []):
                leg = row.get("ce") or row.get("pe") or {}
                if leg.get("lotsize"):
                    lot_size = leg["lotsize"]
                    break

            expiries_out.append(
                {
                    "expiry": expiry,
                    "expiry_ts": expiry_ts,
                    "dte": _calendar_dte(expiry_ts),
                    "years": _round(years, 6),
                    "forward": _round(forward),
                    "lot_size": lot_size,
                    "available": True,
                    "net_gex": _round(total_gex, 4),
                    "net_dex": _round(total_dex, 4),
                }
            )
            rows_by_expiry.append(rows)

        if spot is None or not all_strikes:
            return False, {"status": "error", "message": "No option data for these expiries."}, 404

        strikes = sorted(all_strikes)

        # Grid aligned to strikes: None where an expiry does not list the strike.
        for meta, rows in zip(expiries_out, rows_by_expiry, strict=True):
            meta["cells"] = [rows.get(strike) for strike in strikes]

        call_gex_by_strike = {
            strike: sum((rows.get(strike) or {}).get("ce_gex", 0.0) for rows in rows_by_expiry)
            for strike in strikes
        }
        put_gex_by_strike = {
            strike: sum(abs((rows.get(strike) or {}).get("pe_gex", 0.0)) for rows in rows_by_expiry)
            for strike in strikes
        }
        call_wall = max(call_gex_by_strike, key=call_gex_by_strike.get)
        put_wall = max(put_gex_by_strike, key=put_gex_by_strike.get)
        if call_gex_by_strike[call_wall] <= 0:
            call_wall = None
        if put_gex_by_strike[put_wall] <= 0:
            put_wall = None

        flip = find_gamma_flip(flip_legs, spot, strikes[0], strikes[-1])

        return (
            True,
            {
                "status": "success",
                "underlying": underlying,
                "exchange": exchange,
                "spot_price": _round(spot),
                "as_of": server_ts or int(datetime.now(UTC).timestamp()),
                "range_pct": range_pct,
                "strikes": strikes,
                "flip": _round(flip) if flip is not None else None,
                "call_wall": call_wall,
                "put_wall": put_wall,
                "expiries": expiries_out,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_strike_profile: {e}")
        return (
            False,
            {
                "status": "error",
                "message": "The strike profile could not be calculated. Try again.",
            },
            500,
        )
