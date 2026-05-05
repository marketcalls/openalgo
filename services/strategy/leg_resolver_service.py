"""Leg resolver — converts a StrategyLeg row into a concrete tradable symbol.

Three branches, one per segment:
  CASH:   symbol_cash is final. Just enrich with tick_size + lot_size.
  FUT:    underlying + expiry_type → '{UND}{EXPIRY}FUT' format.
  OPT:    underlying + expiry_type + strike_criteria + option_type
          → '{UND}{EXPIRY}{STRIKE}{CE|PE}' via the existing
          option_symbol_service which handles ATM/ITM/OTM offsets.

Resolved metadata is cached on the leg row at arm-time:
    resolved_symbol, resolved_exchange, lot_size_cache,
    tick_size_cache, freeze_qty_cache, resolved_at

This means the RMS tick loop never makes a symbol_service / option_chain call
— pure in-memory math. Critical for sub-millisecond per-tick evaluation.

Publishes StrategyLegResolvedEvent on success.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from database.strategy_v2_db import StrategyLeg, db_session
from events.strategy_events import StrategyLegResolvedEvent

# Lazy imports inside the resolver functions: services.expiry_service /
# option_symbol_service / symbol_service pull restx_api at module-load time
# which loops back via the existing package structure. Functions resolve them
# at first call.
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


# Result triple — (success, leg_row_with_resolved_fields, message)
ResolverResult = Tuple[bool, Optional[StrategyLeg], str]


# -----------------------------------------------------------------------------
# Expiry resolution (FUT + OPT shared)
# -----------------------------------------------------------------------------

# Map plain English month → 3-letter uppercase used by the symbol format.
_MONTH_3 = ("", "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
            "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

# Format the expiry section as broker-side stores it: '08-MAY-2026' style → '08MAY26'.
_EXPIRY_DASH = re.compile(r"^(\d{1,2})-([A-Z]{3})-(\d{2,4})$")


def _normalize_expiry(token: str) -> str:
    """Take a broker expiry string ('08-MAY-26' or '08-MAY-2026') and return
    OpenAlgo's compact format '08MAY26'.

    Symbol format is documented in docs/prompt/symbol-format.md.
    """
    token = token.strip().upper()
    m = _EXPIRY_DASH.match(token)
    if not m:
        return token  # already compact, or unrecognised — pass through
    day, month, year = m.groups()
    yy = year[-2:]  # last 2 digits — '2026' → '26'
    return f"{int(day):02d}{month}{yy}"


def _pick_expiry(
    underlying: str,
    nfo_exchange: str,
    expiry_type: str,
    api_key: str,
    instrumenttype: str = "options",
) -> Tuple[bool, str, str]:
    """Resolve expiry_type ∈ {CURRENT_WEEK, NEXT_WEEK, CURRENT_MONTH, NEXT_MONTH}
    into a concrete '08MAY26' expiry string by querying the broker's available
    expiry list via expiry_service.

    Heuristic: weekly expiries are dense (1-2/week); monthly are the last
    expiry of each calendar month. We sort the broker's list and pick by
    rank. WEEKLY → first/second; MONTHLY → first end-of-month / next.
    """
    from services.expiry_service import get_expiry_dates
    success, resp, _ = get_expiry_dates(
        symbol=underlying, exchange=nfo_exchange, instrumenttype=instrumenttype, api_key=api_key
    )
    if not success or not resp.get("data"):
        return False, "", resp.get("message", "no expiries available")

    # Sort ascending — broker typically returns ascending already.
    raw = sorted(resp["data"], key=_expiry_sort_key)
    if not raw:
        return False, "", "expiry list empty"

    monthly = [e for e in raw if _is_month_end(e, raw)]
    weekly = raw  # all of them; first two cover current + next

    if expiry_type == "CURRENT_WEEK":
        chosen = weekly[0]
    elif expiry_type == "NEXT_WEEK":
        chosen = weekly[1] if len(weekly) > 1 else weekly[-1]
    elif expiry_type == "CURRENT_MONTH":
        chosen = monthly[0] if monthly else raw[-1]
    elif expiry_type == "NEXT_MONTH":
        chosen = monthly[1] if len(monthly) > 1 else (monthly[0] if monthly else raw[-1])
    else:
        return False, "", f"unknown expiry_type {expiry_type!r}"

    return True, _normalize_expiry(chosen), ""


def _expiry_sort_key(s: str):
    """Parse '08-MAY-25' / '08-MAY-2025' into a comparable date tuple."""
    s = s.strip().upper()
    m = _EXPIRY_DASH.match(s)
    if not m:
        return (9999, 12, 31)
    day, mon, yr = m.groups()
    yyyy = int(yr) if len(yr) == 4 else 2000 + int(yr)
    try:
        month_idx = _MONTH_3.index(mon)
    except ValueError:
        month_idx = 12
    return (yyyy, month_idx, int(day))


def _is_month_end(expiry: str, all_expiries: list) -> bool:
    """An expiry is a month-end (monthly) if it's the latest expiry within
    its calendar month."""
    target = _expiry_sort_key(expiry)
    same_month = [e for e in all_expiries if _expiry_sort_key(e)[:2] == target[:2]]
    if not same_month:
        return False
    return _expiry_sort_key(expiry) == max(_expiry_sort_key(e) for e in same_month)


# -----------------------------------------------------------------------------
# Branch: CASH
# -----------------------------------------------------------------------------


def _resolve_cash(leg: StrategyLeg, api_key: str) -> ResolverResult:
    if not leg.symbol_cash:
        return False, None, "CASH leg missing symbol_cash"

    # Cash legs default to NSE; future enhancement: per-leg exchange selector.
    exchange = "NSE"
    from services.symbol_service import get_symbol_info
    ok, info, _ = get_symbol_info(symbol=leg.symbol_cash, exchange=exchange, api_key=api_key)
    if not ok:
        return False, None, info.get("message", f"symbol {leg.symbol_cash} not found on NSE")

    data = info.get("data", {})
    leg.resolved_symbol = data.get("symbol", leg.symbol_cash)
    leg.resolved_exchange = data.get("exchange", exchange)
    leg.lot_size_cache = data.get("lotsize") or 1
    leg.tick_size_cache = data.get("tick_size") or 0.05
    leg.freeze_qty_cache = data.get("freeze_qty") or 0
    leg.resolved_at = datetime.now(timezone.utc)
    return True, leg, ""


# -----------------------------------------------------------------------------
# Branch: FUT
# -----------------------------------------------------------------------------


def _resolve_fut(leg: StrategyLeg, underlying: str, api_key: str) -> ResolverResult:
    if not underlying:
        return False, None, "FUT leg missing strategy.underlying"
    if not leg.expiry_type:
        return False, None, "FUT leg missing expiry_type"

    # Pick the F&O exchange — for NIFTY/BANKNIFTY/etc. it's NFO; SENSEX → BFO.
    nfo_exchange = "BFO" if underlying.upper() in ("SENSEX", "BANKEX", "SENSEX50") else "NFO"

    ok, expiry, msg = _pick_expiry(
        underlying=underlying.upper(),
        nfo_exchange=nfo_exchange,
        expiry_type=leg.expiry_type,
        api_key=api_key,
        instrumenttype="futures",
    )
    if not ok:
        return False, None, f"FUT expiry resolution failed: {msg}"

    # OpenAlgo futures format: '<UNDERLYING><EXPIRY>FUT' (see docs/prompt/symbol-format.md)
    fut_symbol = f"{underlying.upper()}{expiry}FUT"

    from services.symbol_service import get_symbol_info
    sym_ok, sym_info, _ = get_symbol_info(
        symbol=fut_symbol, exchange=nfo_exchange, api_key=api_key
    )
    if not sym_ok:
        return False, None, sym_info.get("message", f"FUT symbol {fut_symbol} not found")

    data = sym_info.get("data", {})
    leg.resolved_symbol = data.get("symbol", fut_symbol)
    leg.resolved_exchange = data.get("exchange", nfo_exchange)
    leg.lot_size_cache = data.get("lotsize") or 1
    leg.tick_size_cache = data.get("tick_size") or 0.05
    leg.freeze_qty_cache = data.get("freeze_qty") or 0
    leg.resolved_at = datetime.now(timezone.utc)
    return True, leg, ""


# -----------------------------------------------------------------------------
# Branch: OPT
# -----------------------------------------------------------------------------


def _resolve_opt(leg: StrategyLeg, underlying: str, underlying_exchange: str, api_key: str) -> ResolverResult:
    if not underlying:
        return False, None, "OPT leg missing strategy.underlying"
    if not leg.option_type or leg.option_type not in ("CE", "PE"):
        return False, None, f"OPT leg invalid option_type {leg.option_type!r}"
    if not leg.strike_criteria:
        return False, None, "OPT leg missing strike_criteria"

    # underlying_exchange is the QUOTE side (NSE_INDEX/BSE_INDEX/NSE/BSE);
    # actual options trade on NFO/BFO. option_symbol_service handles the mapping.
    nfo_exchange = "BFO" if (underlying_exchange or "").upper().startswith("BSE") else "NFO"

    ok, expiry, msg = _pick_expiry(
        underlying=underlying.upper(),
        nfo_exchange=nfo_exchange,
        expiry_type=leg.expiry_type,
        api_key=api_key,
        instrumenttype="options",
    )
    if not ok:
        return False, None, f"OPT expiry resolution failed: {msg}"

    # strike_criteria on the leg: 'ATM' | 'STRIKE_OFFSET' | 'PREMIUM' | 'DELTA'
    # For Phase 1 we ship ATM + STRIKE_OFFSET (uses ITM/OTM offsets via existing service).
    offset = _strike_criteria_to_offset(leg)
    if offset is None:
        return False, None, (
            f"unsupported strike_criteria {leg.strike_criteria!r}; "
            "PREMIUM/DELTA criteria deferred to a later phase"
        )

    from services.option_symbol_service import get_option_symbol
    sym_ok, sym_info, _ = get_option_symbol(
        underlying=underlying.upper(),
        exchange=underlying_exchange or ("NSE_INDEX" if nfo_exchange == "NFO" else "BSE_INDEX"),
        expiry_date=expiry,
        strike_int=None,
        offset=offset,
        option_type=leg.option_type,
        api_key=api_key,
    )
    if not sym_ok:
        return False, None, sym_info.get("message", "option symbol resolution failed")

    leg.resolved_symbol = sym_info.get("symbol")
    leg.resolved_exchange = sym_info.get("exchange", nfo_exchange)
    leg.lot_size_cache = sym_info.get("lotsize") or 0
    leg.tick_size_cache = sym_info.get("tick_size") or 0.05
    leg.freeze_qty_cache = sym_info.get("freeze_qty") or 0
    leg.resolved_at = datetime.now(timezone.utc)
    return True, leg, ""


def _strike_criteria_to_offset(leg: StrategyLeg) -> Optional[str]:
    """Translate the leg's strike_criteria + strike_value into the offset
    string accepted by option_symbol_service ('ATM', 'ITM3', 'OTM5', etc.).
    """
    crit = (leg.strike_criteria or "").upper()
    if crit == "ATM":
        return "ATM"
    if crit == "STRIKE_OFFSET":
        try:
            n = int(leg.strike_value or 0)
        except (TypeError, ValueError):
            return None
        if n == 0:
            return "ATM"
        return f"OTM{abs(n)}" if n > 0 else f"ITM{abs(n)}"
    # PREMIUM / DELTA — Phase 1+ enhancement
    return None


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def resolve_leg(
    leg: StrategyLeg,
    *,
    underlying: str,
    underlying_exchange: str,
    api_key: str,
    strategy_id: int,
    run_id: int,
) -> ResolverResult:
    """Resolve a single leg, persist the cache fields, publish the event."""
    if leg.segment == "CASH":
        ok, resolved, msg = _resolve_cash(leg, api_key)
    elif leg.segment == "FUT":
        ok, resolved, msg = _resolve_fut(leg, underlying, api_key)
    elif leg.segment == "OPT":
        ok, resolved, msg = _resolve_opt(leg, underlying, underlying_exchange, api_key)
    else:
        return False, None, f"unknown segment {leg.segment!r}"

    if not ok:
        return False, None, msg

    db_session.commit()

    bus.publish(
        StrategyLegResolvedEvent(
            strategy_id=strategy_id,
            run_id=run_id,
            leg_id=resolved.id,
            resolved_symbol=resolved.resolved_symbol or "",
            resolved_exchange=resolved.resolved_exchange or "",
            tick_size=float(resolved.tick_size_cache or 0),
            lot_size=int(resolved.lot_size_cache or 0),
        )
    )
    return True, resolved, ""


def resolve_all(
    legs: list,
    *,
    underlying: str,
    underlying_exchange: str,
    api_key: str,
    strategy_id: int,
    run_id: int,
) -> Tuple[bool, list, list]:
    """Resolve every leg of a strategy. Returns (all_ok, resolved_legs, errors).
    Stops on the first failure — partial entries are not allowed.
    """
    resolved = []
    errors = []
    for leg in legs:
        ok, leg_row, msg = resolve_leg(
            leg,
            underlying=underlying,
            underlying_exchange=underlying_exchange,
            api_key=api_key,
            strategy_id=strategy_id,
            run_id=run_id,
        )
        if not ok:
            errors.append({"leg_index": leg.leg_index, "segment": leg.segment, "message": msg})
            return False, resolved, errors
        resolved.append(leg_row)
    return True, resolved, errors
