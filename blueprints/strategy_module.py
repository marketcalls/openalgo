# blueprints/strategy_module.py
"""HTTP surface for the /strategy module: multi-leg options strategies.

Three surfaces live here: strategy configuration, read-only history, and the
lifecycle and webhook routes that reach the engine and therefore a broker. The
validation below is what stands between an inbound payload and an order.

The store in ``database/strategy_module_db.py`` deliberately does no
validation: its enums are plain tuples rather than SQL CHECK constraints, since
SQLite cannot alter a constraint in place. That makes this module the only
place a bad payload is refused, and the reason the validator below is the bulk
of the file rather than an afterthought. A field that reaches the store
unchecked is a field that ends up in a JSON column shaped however the caller
felt like sending it, and the engine discovers it mid-position.

Three rules the routes hold to:

* **404, never 403, for a strategy that is not yours.** A 403 confirms the row
  exists. Every ``<int:sid>`` route resolves through the owner-scoped
  ``get_strategy`` before doing anything else, so the two cases are
  indistinguishable from outside.
* **409, not 400, while a strategy is running.** Editing or deleting live
  configuration is a state conflict, not a malformed request, and the caller's
  fix is to stop the strategy rather than to change the payload.
* **A PATCH is validated as the strategy it will become.** The change set is
  merged onto the stored configuration and the whole thing is re-validated, so
  a cross-field rule (entry before exit, a lock floor no higher than the profit
  that arms it) cannot be broken one field at a time.
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import re
from datetime import time as dt_time
from typing import Any

from flask import Blueprint, jsonify, request, session
from flask_socketio import join_room, leave_room

from database import strategy_module_db as store
from extensions import socketio
from limiter import limiter
from services.strategy_module.audit_messages import CLOSE_ALL_REQUESTED_MESSAGE
from utils.ip_helper import get_real_ip
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

strategy_module_bp = Blueprint("strategy_module_bp", __name__, url_prefix="/strategy")

# The same budget /chartink already applies to its session-authenticated
# strategy pages. One knob an operator has configured, not a second one.
STRATEGY_RATE_LIMIT = os.getenv("STRATEGY_RATE_LIMIT", "200 per minute")

# One shared scope across the module, so a client cannot draw a fresh budget per
# endpoint simply by alternating between them.
_api_limit = limiter.shared_limit(STRATEGY_RATE_LIMIT, scope="strategy_module_api")

# The same variable and default /chartink and /flow read, so an operator who has
# already tuned the webhook budget gets it applied here too.
WEBHOOK_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "100 per minute")


def _webhook_token_key():
    """Rate-limit key naming the strategy instead of the caller.

    Hashed, because the limiter's in-memory storage keeps a key forever once
    it has seen it: the event list for an expired window is emptied but the
    key itself is never removed. A raw token there would be a second copy of
    the credential sitting in process memory for the life of the worker, one
    entry per token ever presented, including every guess from a scanner. The
    digest keys the same bucket without being replayable.
    """
    token = (request.view_args or {}).get("token") or ""
    return "strategy-webhook:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


# Two limits at one budget, because neither subsumes the other.
#
# By caller address: the only key that can stop someone walking the token space.
# Every guess carries a different token, so a token-keyed limit would score each
# against an empty bucket and never fire, while each miss still costs a lookup.
#
# By token: bounds what one leaked token can do to the broker account however
# many addresses replay it. The token is the whole credential here, so this is
# the limit that caps real order flow.
_webhook_caller_limit = limiter.shared_limit(WEBHOOK_RATE_LIMIT, scope="strategy_webhook_caller")
_webhook_token_limit = limiter.shared_limit(
    WEBHOOK_RATE_LIMIT, scope="strategy_webhook_token", key_func=_webhook_token_key
)


@strategy_module_bp.errorhandler(429)
def _rate_limited(error):
    """Answer an over-limit caller with 429 JSON rather than the app-wide redirect.

    app.py's handler returns JSON only for paths under /api/, and redirects
    everything else to the React rate-limited page. A browser reads that page;
    TradingView does not. A throttled alert would follow the redirect, receive
    200 and HTML, and be recorded as delivered, so a strategy silently dropping
    signals would look exactly like a healthy one.
    """
    retry_after = 60
    breached = getattr(error, "limit", None)
    try:
        retry_after = int(breached.limit.get_expiry())
    except (AttributeError, TypeError, ValueError):
        pass

    response = jsonify(
        {
            "status": "error",
            "result": "rate_limited",
            "message": "Rate limit exceeded. Please slow down your requests.",
            "retry_after": retry_after,
        }
    )
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


# ---------------------------------------------------------------------------
# Vocabulary
#
# The enums the store exports are used directly. Everything below is a value
# this layer owns: the store has no opinion on a leg's shape, because legs live
# in a JSON column.
# ---------------------------------------------------------------------------

#: The store's PATCH allowlist doubles as the create allowlist. Sharing it is
#: deliberate: two lists would drift, and the second one would be the loose one.
#:
#: strategy_kind is the one field that is settable at create and not updatable
#: afterwards, so it is added here rather than to the store's list. It also has
#: to survive the PATCH merge: the merge seeds itself from these fields, and a
#: signal strategy whose kind was dropped on the way in would have its legs
#: re-validated as batch legs and fail on its own stored configuration.
CONFIG_FIELDS = store.UPDATABLE_FIELDS | {"strategy_kind"}

PRODUCTS = ("CNC", "NRML", "MIS")
# MARKET only, and deliberately so. Neither the strategy configuration nor a
# leg carries a price, so a LIMIT, SL or SL-M entry was built with price and
# trigger_price both defaulting to zero: every entry of a LIMIT strategy went
# out as a limit order at zero. Accepting a price type the module cannot
# supply a price for is worse than not offering it. Exits are MARKET on every
# path regardless, because a stop that cannot fill is not a stop.
PRICETYPES = ("MARKET",)

#: Exchanges an underlying can be quoted on. Indices are where an options
#: strategy usually starts, but a stock or an MCX commodity underlying is valid
#: too. Derivative exchanges are accepted because a futures leg's underlying may
#: legitimately be named there.
UNDERLYING_EXCHANGES = (
    "NSE",
    "BSE",
    "NFO",
    "BFO",
    "CDS",
    "BCD",
    "MCX",
    "NCDEX",
    "NCO",
    "NSE_INDEX",
    "BSE_INDEX",
)

#: How the wizard groups instruments, and the only thing that says which
#: segments a leg may use. Stored on the strategy and echoed back, so it was
#: previously validated as free text: any thirty characters were accepted and
#: every rule hanging off the tab lived in the browser. A cash leg on an index
#: tab therefore validated here and failed at run start with "no cash contract
#: found for NIFTY on NSE", which is the correct refusal arriving far too late.
UNIVERSE_TABS = ("weekly_monthly", "monthly_only", "stocks_fno", "mcx")

LEG_SEGMENTS = ("options", "futures", "cash")

#: Which segments each tab offers. Cash appears on one tab only, because an
#: index has no cash instrument of its own and an MCX commodity has no spot:
#: both resolve to a symbol the master contract does not list. This mirrors
#: TAB_SEGMENTS in frontend/src/types/strategy_module.ts, which is where the
#: rule used to live on its own.
TAB_SEGMENTS = {
    "weekly_monthly": ("futures", "options"),
    "monthly_only": ("futures", "options"),
    "stocks_fno": ("cash", "futures", "options"),
    "mcx": ("futures", "options"),
}

LEG_POSITIONS = ("B", "S")
LEG_OPTION_TYPES = ("CE", "PE")
LEG_STRIKE_MODES = ("atm", "strike")
LEG_EXPIRIES = ("weekly", "next_week", "monthly", "next_month", "current", "next")

#: A strike named relative to the money. Five steps either side is what the
#: wizard offers; a leg further out names its strike absolutely instead.
ATM_OFFSETS = (
    ("ATM",) + tuple(f"ITM{n}" for n in range(1, 6)) + tuple(f"OTM{n}" for n in range(1, 6))
)

LOCK_PROFIT_MODES = ("lock", "lock_and_trail")

# How a leg's stop, target and trail are expressed. Points is the default and
# is what every strategy written before this existed carries, so an absent
# value means points and no stored configuration has to change.
#
# One toggle covers all three deliberately: a leg whose stop is a percentage of
# entry and whose target is an absolute point distance is far more likely to be
# a mistake than an intention.
RISK_UNITS = ("points", "percent")
SCHEDULER_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

LEG_FIELDS = (
    "id",
    "segment",
    "position",
    "lots",
    "option_type",
    "strike_mode",
    "atm_offset",
    "strike",
    "expiry",
    "sl_pts",
    "target_pts",
    "trail",
    "risk_unit",
)
#: A signal leg is a different shape from a batch leg, not a superset of it.
#: It names its own instrument and its own absolute quantity, and it carries no
#: option fields at all: multi-leg option spreads stay in batch mode.
# Where a signal leg may trade. Cash plus the derivative venues; an index
# pseudo-exchange is not orderable and is deliberately absent.
SIGNAL_LEG_EXCHANGES = ("NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "NCO")

SIGNAL_LEG_FIELDS = (
    "id",
    "symbol",
    "exchange",
    "side",
    "qty",
    "qty_mode",
    "segment",
    "expiry",
    "sl_pts",
    "target_pts",
    "trail",
    "risk_unit",
)

#: Which signals a leg accepts. Not the side it is currently held - that is
#: decided by whichever signal opened it and lives in run state.
LEG_SIDES = ("long", "short", "both")

#: How a signal leg's quantity is counted.
#:
#: "lots"  the number is a lot count; the quantity sent is count * lot size.
#: "units" the number is the quantity itself.
#:
#: Storing lots is what makes a derivative leg survive a lot-size change.
#: Exchanges revise them - NIFTY moved from 75 to 65 - and a leg stored as 325
#: units silently becomes 5 lots under one size and 4.33 under the next. A leg
#: stored as 5 lots is still 5 lots.
QTY_MODES = ("lots", "units")

#: Cash has no lot size, so a cash leg is always counted in units.
MAX_SIGNAL_QTY = 1_000_000

#: A lot count is small; the cap on units is much larger.
MAX_SIGNAL_LOTS = 10_000

TRAIL_FIELDS = ("x", "y")
LOCK_PROFIT_FIELDS = ("mode", "if_profit_reaches", "lock_profit", "trail_step")
SCHEDULER_FIELDS = ("enabled", "days", "start_time", "auto_stop_time", "default_mode")

MIN_LEGS = 1
MAX_LEGS = 10
MAX_LOTS = 50
# A cash leg's "lots" is a share count, because a cash contract's lot size is 1.
# Matched to the signal path's own cash ceiling so the same instrument is not
# capped differently by which kind of strategy holds it.
MAX_CASH_QUANTITY = 1_000_000
MAX_NAME_LENGTH = 200
MAX_UNDERLYING_LENGTH = 50
MAX_IP_ALLOWLIST = 20

#: Event history page size. The engine writes an event per risk transition per
#: leg, so an unbounded read would serialize a whole trading day.
EVENTS_DEFAULT_LIMIT = 500
EVENTS_MAX_LIMIT = 1000

NOT_FOUND = "Strategy not found"

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


class ValidationError(ValueError):
    """A payload the API refuses, carrying the message the caller is shown.

    Raised from the leaf helpers and caught once at the public entry point.
    Threading an ``(value, error)`` tuple through thirty nested checks is how
    a check ends up silently unread.
    """


# ---------------------------------------------------------------------------
# Leaf validators
# ---------------------------------------------------------------------------


def _mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def _reject_unknown(value: dict, allowed, label: str) -> None:
    """Refuse fields this layer does not know.

    Dropping them silently is the failure mode worth avoiding: a caller that
    misspells ``overall_sl_mtm`` would otherwise be told the strategy saved and
    would find out at the first drawdown that it has no stop.
    """
    extra = sorted(set(value) - set(allowed))
    if extra:
        raise ValidationError(
            f"{label} does not accept {', '.join(extra)}. "
            f"Accepted fields: {', '.join(sorted(allowed))}"
        )


def _required(mapping: dict, key: str, label: str = "") -> Any:
    name = f"{label}.{key}" if label else key
    if key not in mapping or mapping[key] is None:
        raise ValidationError(f"{name} is required")
    return mapping[key]


def _text(value: Any, label: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text")
    text = value.strip()
    if not text:
        raise ValidationError(f"{label} is required")
    if len(text) > max_length:
        raise ValidationError(f"{label} must be at most {max_length} characters, got {len(text)}")
    return text


def _choice(value: Any, allowed, label: str) -> str:
    """One of ``allowed``, matched case-insensitively and returned canonically.

    Normalizing here is what makes the validator idempotent, which a PATCH
    depends on: the stored value is fed back through on the next update and must
    survive unchanged.
    """
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be one of: {', '.join(allowed)}")
    text = value.strip()
    for option in allowed:
        if text.lower() == option.lower():
            return option
    raise ValidationError(f"{label} must be one of: {', '.join(allowed)}. Got {value!r}")


def _number(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    greater_than: float | None = None,
) -> int | float:
    """A finite JSON number, returned with its own type intact.

    int stays int and float stays float. Nothing here calls ``int()`` on a
    value, which is what keeps a fractional strike (VEDL 292.5) from being
    rounded into a contract that does not exist.

    ``bool`` is an int subclass, so ``True`` would otherwise validate as 1.
    """
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a number")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise ValidationError(f"{label} must be a number, got {value!r}") from None
    if not isinstance(value, int | float) or not math.isfinite(value):
        raise ValidationError(f"{label} must be a number")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{label} must be {minimum} or more, got {value}")
    if greater_than is not None and value <= greater_than:
        raise ValidationError(f"{label} must be greater than {greater_than}, got {value}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{label} must be {maximum} or less, got {value}")
    return value


def _integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a whole number")
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            raise ValidationError(f"{label} must be a whole number, got {value!r}") from None
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError(f"{label} must be a whole number, got {value}")
        value = int(value)
    if not isinstance(value, int):
        raise ValidationError(f"{label} must be a whole number")
    if value < minimum or value > maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}, got {value}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{label} must be true or false")
    return value


def _hhmm(value: Any, label: str) -> dt_time:
    """A ``HH:MM`` 24-hour clock time as ``datetime.time``.

    The two Time columns want a ``time``; the scheduler's JSON keeps strings.
    Both go through here so one spelling is accepted for both.
    """
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a HH:MM 24-hour time, for example 09:20")
    match = _HHMM.match(value.strip())
    if not match:
        raise ValidationError(
            f"{label} must be a HH:MM 24-hour time, for example 09:20. Got {value!r}"
        )
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValidationError(f"{label} is not a valid time of day: {value!r}")
    return dt_time(hour=hour, minute=minute)


def _loss_amount(value: Any, label: str) -> float | int | None:
    """A loss threshold, entered as a positive amount.

    The engine compares the running MTM against the negative of this number, so
    a caller who "helpfully" sends -5000 would be asking to stop at a profit of
    5000. Refusing it, and saying why, is the only version of this that cannot
    be misread. The stored value stays positive: the sign is applied where the
    comparison happens, not in the column.
    """
    if value is None:
        return None
    number = _number(value, label)
    if number < 0:
        raise ValidationError(
            f"{label} is entered as a positive amount and applied as a negative "
            f"threshold, so it cannot be negative. Enter 5000 to stop at a loss of 5000."
        )
    return number


def _gain_amount(value: Any, label: str) -> float | int | None:
    if value is None:
        return None
    return _number(value, label, minimum=0)


# ---------------------------------------------------------------------------
# Legs
# ---------------------------------------------------------------------------


def _risk_max(risk_unit: str) -> float | None:
    """The ceiling for a risk number in this unit.

    A percentage above 100 is not a wider stop, it is a number that cannot mean
    what it says: 150% of entry below a long's entry price is negative. Points
    keep their existing open ceiling, because a point distance is bounded by
    the instrument, not by arithmetic.
    """
    return 100.0 if risk_unit == "percent" else None


def _validate_trail(raw: Any, label: str, risk_unit: str = "points") -> dict | None:
    """``{x, y}``: advance the stop by y for every x of favourable move.

    Both halves are required together. A trail with only one of them configured
    is not a partially configured trail, it is one that never moves.

    x and y are read in the leg's own risk unit, so a percent leg trails in
    percent of entry and a points leg in points.
    """
    if raw is None:
        return None
    data = _mapping(raw, label)
    _reject_unknown(data, TRAIL_FIELDS, label)
    ceiling = _risk_max(risk_unit)
    return {
        "x": _number(_required(data, "x", label), f"{label}.x", minimum=0, maximum=ceiling),
        "y": _number(_required(data, "y", label), f"{label}.y", minimum=0, maximum=ceiling),
    }


def _validate_signal_leg(raw: Any, index: int) -> dict:
    """One signal-mode leg: its own instrument, side and absolute quantity."""
    label = f"legs[{index}]"
    leg = _mapping(raw, label)
    _reject_unknown(leg, SIGNAL_LEG_FIELDS, label)

    segment = _choice(leg.get("segment") or "cash", ("cash", "futures"), f"{label}.segment")
    clean: dict[str, Any] = {
        "id": (
            _integer(leg["id"], f"{label}.id", minimum=1, maximum=MAX_LEGS)
            if leg.get("id") is not None
            else index + 1
        ),
        "symbol": _text(_required(leg, "symbol", label), f"{label}.symbol", max_length=100).upper(),
        # Checked against the known venues, not taken as free text. Nothing
        # downstream catches a typo: a signal leg is never resolved against an
        # underlying, so "NSEE" simply became the exchange on a real order.
        "exchange": _choice(
            _text(_required(leg, "exchange", label), f"{label}.exchange", max_length=20).upper(),
            SIGNAL_LEG_EXCHANGES,
            f"{label}.exchange",
        ),
        # Which signals this leg accepts. "both" is the usual intraday case.
        "side": _choice(leg.get("side") or "both", LEG_SIDES, f"{label}.side"),
        "segment": segment,
    }

    # A derivative is naturally counted in lots and cash in units, so the mode
    # defaults to whichever the venue implies rather than making every caller
    # state it. An explicit value always wins.
    from services.strategy_module.symbol_resolver import DERIVATIVE_EXCHANGES

    derivative = clean["exchange"] in DERIVATIVE_EXCHANGES
    qty_mode = _choice(
        leg.get("qty_mode") or ("lots" if derivative else "units"),
        QTY_MODES,
        f"{label}.qty_mode",
    )
    if qty_mode == "lots" and not derivative:
        raise ValidationError(
            f"{label}.qty_mode is 'lots', but {clean['exchange']} has no lot size. "
            "Cash instruments are counted in units."
        )
    clean["qty_mode"] = qty_mode
    clean["qty"] = _integer(
        _required(leg, "qty", label),
        f"{label}.qty",
        minimum=1,
        maximum=MAX_SIGNAL_LOTS if qty_mode == "lots" else MAX_SIGNAL_QTY,
    )

    # A signal leg names its own contract, so this rank is descriptive only:
    # nothing resolves against it. What used to happen is that "NIFTY" on NFO
    # with expiry "current" placed an order for the literal string NIFTY, with
    # a quantity that looked entirely plausible because the lot size is read
    # from the root. _resolve_signal_leg now refuses a symbol the master
    # contract does not list, which is what actually stops that.
    if segment == "futures":
        clean["expiry"] = _choice(leg.get("expiry") or "current", LEG_EXPIRIES, f"{label}.expiry")
    elif leg.get("expiry") is not None:
        raise ValidationError(f"{label}.expiry does not apply to a cash leg")

    # Optional per-leg risk, in the same shape and with the same helper the
    # batch leg uses, so a signal leg is evaluated by exactly the same rules.
    risk_unit = _choice(leg.get("risk_unit") or "points", RISK_UNITS, f"{label}.risk_unit")
    if leg.get("sl_pts") is not None:
        clean["sl_pts"] = _number(
            leg["sl_pts"], f"{label}.sl_pts", minimum=0, maximum=_risk_max(risk_unit)
        )
    if leg.get("target_pts") is not None:
        clean["target_pts"] = _number(
            leg["target_pts"], f"{label}.target_pts", minimum=0, maximum=_risk_max(risk_unit)
        )
    trail = _validate_trail(leg.get("trail"), label, risk_unit)
    if trail is not None:
        clean["trail"] = trail
    # Stored on every leg, including the default, so nothing downstream has to
    # decide what an absent value meant.
    clean["risk_unit"] = risk_unit

    # A derivative trades in whole lots. The broker refuses anything else at
    # order time, so catching it here turns a rejected order into a message the
    # user can act on while still in the form.
    #
    # A lot size that cannot be determined is not treated as a failure: the
    # master contract may not be downloaded yet, and refusing a configuration
    # for a reason the user cannot fix from this screen would be worse than
    # letting the engine check again at entry, where the real contract is known.
    from services.strategy_module.symbol_resolver import quantity_is_whole_lots

    # Only meaningful in units mode. A lot count is a whole number of lots by
    # construction, so checking it against the lot size would be nonsense.
    whole, lot_size = (
        quantity_is_whole_lots(clean["qty"], clean["symbol"], clean["exchange"])
        if clean["qty_mode"] == "units"
        else (True, None)
    )
    if not whole:
        raise ValidationError(
            f"{label}.qty is {clean['qty']}, which is not a whole number of lots. "
            f"{clean['symbol']} on {clean['exchange']} trades in lots of {lot_size}."
        )

    return clean


def _validate_leg(raw: Any, index: int) -> dict:
    label = f"legs[{index}]"
    leg = _mapping(raw, label)
    _reject_unknown(leg, LEG_FIELDS, label)

    segment = _choice(_required(leg, "segment", label), LEG_SEGMENTS, f"{label}.segment")
    clean: dict[str, Any] = {
        # Position within the basket, so orders, events and checkpoints can name
        # a leg after the strategy is edited. Defaults to the leg's index.
        "id": (
            _integer(leg["id"], f"{label}.id", minimum=1, maximum=MAX_LEGS)
            if leg.get("id") is not None
            else index + 1
        ),
        "segment": segment,
        "position": _choice(_required(leg, "position", label), LEG_POSITIONS, f"{label}.position"),
        # A cash contract's lot size is 1, so on a cash leg this number is the
        # share count and the derivative cap of 50 made 50 shares the largest
        # cash order a batch strategy could place. Signal mode counts the same
        # instrument in units up to a million. The cap that matters on a
        # derivative is lots; on cash it is shares, and they are not the same
        # number.
        "lots": _integer(
            _required(leg, "lots", label),
            f"{label}.lots",
            minimum=1,
            maximum=MAX_CASH_QUANTITY if segment == "cash" else MAX_LOTS,
        ),
    }

    # Fields that only mean something for an options leg. Accepting them on a
    # futures leg and then ignoring them is how a strategy ends up looking
    # correct in the editor and trading something else.
    options_only = ("option_type", "strike_mode", "atm_offset", "strike")
    if segment == "options":
        clean["option_type"] = _choice(
            _required(leg, "option_type", label), LEG_OPTION_TYPES, f"{label}.option_type"
        )
        strike_mode = _choice(
            leg.get("strike_mode") or "atm", LEG_STRIKE_MODES, f"{label}.strike_mode"
        )
        clean["strike_mode"] = strike_mode
        if strike_mode == "atm":
            if leg.get("strike") is not None:
                raise ValidationError(
                    f"{label}.strike is only used when strike_mode is 'strike'. "
                    f"Set strike_mode to 'strike', or remove the strike."
                )
            clean["atm_offset"] = _choice(
                leg.get("atm_offset") or "ATM", ATM_OFFSETS, f"{label}.atm_offset"
            )
        else:
            if leg.get("atm_offset") is not None:
                raise ValidationError(
                    f"{label}.atm_offset is only used when strike_mode is 'atm'. "
                    f"Set strike_mode to 'atm', or remove the offset."
                )
            # Kept exactly as sent. Strikes are fractional on plenty of
            # contracts (VEDL 292.5), and rounding one names a contract that is
            # not listed.
            clean["strike"] = _number(
                _required(leg, "strike", label), f"{label}.strike", greater_than=0
            )
    else:
        for field in options_only:
            if leg.get(field) is not None:
                raise ValidationError(f"{label}.{field} is only valid on an options leg")

    if segment == "cash":
        if leg.get("expiry") is not None:
            raise ValidationError(f"{label}.expiry is not valid on a cash leg")
    else:
        clean["expiry"] = _choice(_required(leg, "expiry", label), LEG_EXPIRIES, f"{label}.expiry")

    risk_unit = _choice(leg.get("risk_unit") or "points", RISK_UNITS, f"{label}.risk_unit")
    if leg.get("sl_pts") is not None:
        clean["sl_pts"] = _number(
            leg["sl_pts"], f"{label}.sl_pts", minimum=0, maximum=_risk_max(risk_unit)
        )
    if leg.get("target_pts") is not None:
        clean["target_pts"] = _number(
            leg["target_pts"], f"{label}.target_pts", minimum=0, maximum=_risk_max(risk_unit)
        )
    trail = _validate_trail(leg.get("trail"), f"{label}.trail", risk_unit)
    if trail is not None:
        clean["trail"] = trail
    clean["risk_unit"] = risk_unit

    return clean


def _validate_legs(raw: Any, kind: str = "batch") -> list[dict]:
    if not isinstance(raw, list):
        raise ValidationError("legs must be a list")
    if len(raw) < MIN_LEGS:
        raise ValidationError(f"A strategy needs at least {MIN_LEGS} leg")
    if len(raw) > MAX_LEGS:
        raise ValidationError(f"A strategy takes at most {MAX_LEGS} legs, got {len(raw)}")
    validate = _validate_signal_leg if kind == "signal" else _validate_leg
    legs = [validate(leg, index) for index, leg in enumerate(raw)]

    ids = [leg["id"] for leg in legs]
    if len(set(ids)) != len(ids):
        raise ValidationError("Every leg needs its own id")
    return legs


# ---------------------------------------------------------------------------
# Risk blocks
# ---------------------------------------------------------------------------


def _validate_lock_profit(raw: Any) -> dict | None:
    """``{mode, if_profit_reaches, lock_profit, trail_step}``.

    ``trail_step`` is only required for ``lock_and_trail``: a plain lock sets
    one floor and leaves it there.
    """
    if raw is None:
        return None
    label = "lock_profit"
    data = _mapping(raw, label)
    _reject_unknown(data, LOCK_PROFIT_FIELDS, label)

    mode = _choice(_required(data, "mode", label), LOCK_PROFIT_MODES, f"{label}.mode")
    if_profit_reaches = _number(
        _required(data, "if_profit_reaches", label),
        f"{label}.if_profit_reaches",
        greater_than=0,
    )
    # Zero is allowed: locking at breakeven is a real and common choice.
    locked = _number(_required(data, "lock_profit", label), f"{label}.lock_profit", minimum=0)
    if locked > if_profit_reaches:
        raise ValidationError(
            f"{label}.lock_profit cannot be more than {label}.if_profit_reaches: "
            f"the floor would be above the profit that arms it"
        )

    clean: dict[str, Any] = {
        "mode": mode,
        "if_profit_reaches": if_profit_reaches,
        "lock_profit": locked,
    }
    if mode == "lock_and_trail":
        if data.get("trail_step") is None:
            raise ValidationError(f"{label}.trail_step is required when mode is 'lock_and_trail'")
        clean["trail_step"] = _number(data["trail_step"], f"{label}.trail_step", greater_than=0)
    elif data.get("trail_step") is not None:
        clean["trail_step"] = _number(data["trail_step"], f"{label}.trail_step", greater_than=0)
    return clean


def _validate_scheduler(raw: Any) -> dict | None:
    """``{enabled, days[], start_time, auto_stop_time, default_mode}``.

    The times and days are only enforced as present once the scheduler is
    enabled, so a half-filled panel still saves. ``default_mode`` defaults to
    sandbox, matching the store's rule that live trading is opt-in per strategy.
    """
    if raw is None:
        return None
    label = "scheduler"
    data = _mapping(raw, label)
    _reject_unknown(data, SCHEDULER_FIELDS, label)

    enabled = _boolean(data.get("enabled", False), f"{label}.enabled")

    raw_days = data.get("days") or []
    if not isinstance(raw_days, list):
        raise ValidationError(f"{label}.days must be a list of days, MON to SUN")
    days: list[str] = []
    for index, day in enumerate(raw_days):
        canonical = _choice(day, SCHEDULER_DAYS, f"{label}.days[{index}]")
        if canonical in days:
            raise ValidationError(f"{label}.days lists {canonical} more than once")
        days.append(canonical)
    if enabled and not days:
        raise ValidationError(f"{label}.days needs at least one day when the scheduler is enabled")

    start_raw = data.get("start_time")
    stop_raw = data.get("auto_stop_time")
    if enabled:
        start_raw = _required(data, "start_time", label)
        stop_raw = _required(data, "auto_stop_time", label)
    start = _hhmm(start_raw, f"{label}.start_time") if start_raw is not None else None
    stop = _hhmm(stop_raw, f"{label}.auto_stop_time") if stop_raw is not None else None
    if start and stop and start >= stop:
        raise ValidationError(f"{label}.start_time must be earlier than {label}.auto_stop_time")

    return {
        "enabled": enabled,
        # Week order, not the order they arrived, so two equivalent schedules
        # compare equal.
        "days": sorted(days, key=SCHEDULER_DAYS.index),
        "start_time": start.strftime("%H:%M") if start else None,
        "auto_stop_time": stop.strftime("%H:%M") if stop else None,
        "default_mode": _choice(
            data.get("default_mode") or "sandbox", store.RUN_MODES, f"{label}.default_mode"
        ),
    }


def _validate_ip_allowlist(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    label = "webhook_ip_allowlist"
    if not isinstance(raw, list):
        raise ValidationError(f"{label} must be a list of IP addresses or CIDR ranges")
    if len(raw) > MAX_IP_ALLOWLIST:
        raise ValidationError(f"{label} takes at most {MAX_IP_ALLOWLIST} entries, got {len(raw)}")
    entries: list[str] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, str) or not entry.strip():
            raise ValidationError(f"{label}[{index}] must be an IP address or CIDR range")
        text = entry.strip()
        try:
            # strict=False so 192.168.1.5/24 is read as the network it names
            # rather than refused for having host bits set.
            ipaddress.ip_network(text, strict=False)
        except ValueError:
            raise ValidationError(
                f"{label}[{index}] is not a valid IP address or CIDR range: {text!r}"
            ) from None
        entries.append(text)
    return entries


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_strategy_config(payload: Any) -> tuple[dict | None, str | None]:
    """Validate a whole strategy configuration.

    The single entry point for both create and update. A PATCH merges its
    change set onto the stored configuration and passes the result here, so
    there is one definition of a valid strategy rather than a strict one and a
    lenient one.

    Returns ``(config, None)`` or ``(None, message)``. The config is normalized
    and ready for the store: enums in their canonical spelling, times as
    ``datetime.time``, defaults filled in.
    """
    try:
        return _validate_strategy_config(payload), None
    except ValidationError as exc:
        return None, str(exc)


def _validate_strategy_config(payload: Any) -> dict:
    raw = _mapping(payload, "The request body")
    _reject_unknown(raw, CONFIG_FIELDS, "The request")

    # Legs first, because the universe tab is derived from them when the caller
    # names none, and that derivation has to read the segment a leg will
    # actually carry. Reading the raw payload saw no segment on a signal leg
    # that relied on the default, derived a tab for a derivative universe, and
    # then refused the very cash leg the default had just produced.
    kind = _choice(raw.get("strategy_kind") or "batch", store.STRATEGY_KINDS, "strategy_kind")
    legs = _validate_legs(_required(raw, "legs"), kind)

    config: dict[str, Any] = {
        "name": _text(_required(raw, "name"), "name", max_length=MAX_NAME_LENGTH),
        "strategy_kind": kind,
        # Only read for signal strategies; harmless and inert on a batch one.
        "direction": _choice(raw.get("direction") or "both", store.DIRECTIONS, "direction"),
        # Derived from the legs when the caller does not say, because the tab
        # is a grouping the wizard uses and not something an API caller should
        # have to know. Defaulting it to weekly_monthly and then refusing the
        # cash leg underneath it would be a refusal about a field the caller
        # never set. An explicit tab is still checked, and still governs.
        "universe_tab": _choice(
            raw.get("universe_tab") or _tab_for_legs(raw, legs), UNIVERSE_TABS, "universe_tab"
        ),
        "underlying": _text(
            _required(raw, "underlying"), "underlying", max_length=MAX_UNDERLYING_LENGTH
        ).upper(),
        "underlying_exchange": _choice(
            _required(raw, "underlying_exchange"), UNDERLYING_EXCHANGES, "underlying_exchange"
        ),
        "strategy_type": _choice(
            raw.get("strategy_type") or "intraday", store.STRATEGY_TYPES, "strategy_type"
        ),
        "product": _choice(raw.get("product") or "NRML", PRODUCTS, "product"),
        "pricetype": _choice(raw.get("pricetype") or "MARKET", PRICETYPES, "pricetype"),
        "legs": legs,
        "overall_sl_mtm": _loss_amount(raw.get("overall_sl_mtm"), "overall_sl_mtm"),
        "overall_target_mtm": _gain_amount(raw.get("overall_target_mtm"), "overall_target_mtm"),
        "lock_profit": _validate_lock_profit(raw.get("lock_profit")),
        "trail_sl_to_entry": _boolean(raw.get("trail_sl_to_entry", False), "trail_sl_to_entry"),
        "scheduler": _validate_scheduler(raw.get("scheduler")),
        "daily_loss_limit_inr": _loss_amount(
            raw.get("daily_loss_limit_inr"), "daily_loss_limit_inr"
        ),
        "webhook_ip_allowlist": _validate_ip_allowlist(raw.get("webhook_ip_allowlist")),
    }

    # An intraday strategy with no exit time has nothing to square off against,
    # so both times are required there and optional for a positional one.
    entry_raw = raw.get("entry_time")
    exit_raw = raw.get("exit_time")
    if config["strategy_type"] == "intraday":
        if entry_raw is None:
            raise ValidationError("entry_time is required for an intraday strategy")
        if exit_raw is None:
            raise ValidationError("exit_time is required for an intraday strategy")
    config["entry_time"] = _hhmm(entry_raw, "entry_time") if entry_raw is not None else None
    config["exit_time"] = _hhmm(exit_raw, "exit_time") if exit_raw is not None else None
    if config["entry_time"] and config["exit_time"] and config["entry_time"] >= config["exit_time"]:
        raise ValidationError("entry_time must be earlier than exit_time")

    _reject_contradictory_sides(config)
    _reject_segments_outside_tab(config)
    _reject_cash_on_a_derivative_venue(config)
    _reject_uncoverable_short_cash(config)
    return config


#: Underlying exchanges whose instruments belong to the commodity tab.
_COMMODITY_EXCHANGES = frozenset({"MCX", "NCDEX", "NCO"})

#: Expiry ranks that only exist where an instrument lists weekly contracts.
_WEEKLY_RANKS = frozenset({"weekly", "next_week"})


def _tab_for_legs(raw: Any, legs: list[dict[str, Any]]) -> str:
    """The tab a configuration belongs to, read off the configuration itself.

    Used only when the caller did not name one. Takes the *validated* legs
    rather than the raw ones: a signal leg's segment defaults to cash, and
    deriving from the raw payload missed that default, picked a derivative
    universe, and then refused the cash leg validation had just produced. Kept
    in step with the same derivation in
    upgrade/migrate_strategy_universe_tab.py, which normalizes rows written
    before the tab was validated.
    """
    segments = {str(leg.get("segment") or "").lower() for leg in legs if isinstance(leg, dict)}
    if "cash" in segments:
        return "stocks_fno"

    if str(raw.get("underlying_exchange") or "").upper() in _COMMODITY_EXCHANGES:
        return "mcx"

    ranks = {str(leg.get("expiry") or "").lower() for leg in legs if isinstance(leg, dict)}
    return "weekly_monthly" if ranks & _WEEKLY_RANKS else "monthly_only"


def _reject_segments_outside_tab(config: dict[str, Any]) -> None:
    """Refuse a leg whose segment the strategy's universe tab does not offer.

    The tab decides what the underlying is, so it decides which segments can
    resolve against it. A cash leg on an index tab names the index itself,
    which has no cash instrument, and a cash leg on the commodity tab names a
    spot that does not exist. Both were accepted here and refused at run start,
    after the operator had finished the form and pressed Start.
    """
    tab = config.get("universe_tab", "weekly_monthly")
    allowed = TAB_SEGMENTS.get(tab)
    if not allowed:
        return

    for index, leg in enumerate(config.get("legs") or []):
        segment = leg.get("segment")
        if segment and segment not in allowed:
            raise ValidationError(
                f"legs[{index}].segment is {segment!r}, which the {tab!r} universe does not "
                f"offer. That tab trades {' and '.join(allowed)}."
            )


def _reject_cash_on_a_derivative_venue(config: dict[str, Any]) -> None:
    """Refuse a signal leg whose segment and exchange disagree.

    A signal leg names its own venue, and nothing downstream reconciles that
    against its segment: a leg marked cash on NFO was accepted, and the segment
    was then simply ignored, so the leg traded whatever the symbol happened to
    be. Batch legs take their venue from the strategy's underlying and are
    covered by the tab rule above instead.
    """
    if config.get("strategy_kind") != "signal":
        return

    from services.strategy_module.symbol_resolver import DERIVATIVE_EXCHANGES

    for index, leg in enumerate(config.get("legs") or []):
        segment = leg.get("segment")
        exchange = leg.get("exchange")
        if not segment or not exchange:
            continue
        if segment == "cash" and exchange in DERIVATIVE_EXCHANGES:
            raise ValidationError(
                f"legs[{index}] is a cash leg on {exchange}, which lists derivatives. "
                f"Use NSE or BSE for cash, or set the segment to 'futures'."
            )
        if segment == "futures" and exchange not in DERIVATIVE_EXCHANGES:
            raise ValidationError(
                f"legs[{index}] is a futures leg on {exchange}, which lists cash. "
                f"Use a derivative exchange, or set the segment to 'cash'."
            )


def _reject_uncoverable_short_cash(config: dict[str, Any]) -> None:
    """Refuse a short cash leg the product cannot deliver.

    Indian cash equity can be sold short intraday and not carried short: a
    delivery sell has to be covered by stock the account holds. The product is
    read as intent, so anything that is not MIS is carry and reaches a cash
    venue as CNC. A short cash leg under carry is therefore a naked short
    delivery, which the broker refuses at order time and nothing refused here.

    Batch legs only, and deliberately. A batch leg's position is what it will
    be entered as the moment the run starts, so a short cash leg under carry is
    an order that cannot be placed. A signal leg's ``side`` is only which
    signals it accepts: a leg set to short, or to both, is an ordinary intraday
    configuration until an alert actually asks for a short, and refusing it
    here would block the common case to catch a rarer one. That case is caught
    at signal time by ``signals._reject_uncarryable_short``, which knows the
    side being opened rather than the sides being accepted.
    """
    if config.get("strategy_kind") == "signal":
        return
    product = (config.get("product") or "").upper()
    if product == "MIS":
        return

    for index, leg in enumerate(config.get("legs") or []):
        if leg.get("segment") != "cash":
            continue
        if leg.get("position") == "S":
            raise ValidationError(
                f"legs[{index}] sells cash short, but product {product!r} carries the position. "
                f"Cash cannot be held short overnight. Use MIS for an intraday short, or make "
                f"the leg long."
            )


#: Which leg sides a strategy-level direction can ever act on.
_DIRECTION_ACCEPTS = {
    "both": {"long", "short", "both"},
    "long_only": {"long", "both"},
    "short_only": {"short", "both"},
}


def _reject_contradictory_sides(config: dict[str, Any]) -> None:
    """Refuse a leg whose side the strategy's direction can never act on.

    A long_only strategy will discard every short signal before it reaches a
    leg, so a leg declared short is configuration that looks complete and can
    never trade. Nothing downstream complains: the direction gate refuses the
    signal, the leg simply never opens, and the operator is left watching a
    strategy that does nothing for a reason the form never mentioned.

    Batch legs carry a B/S position rather than a side and are entered as a
    basket regardless of direction, so this applies to signal strategies only.
    """
    if config.get("strategy_kind") != "signal":
        return

    direction = config.get("direction", "both")
    accepted = _DIRECTION_ACCEPTS.get(direction, {"long", "short", "both"})

    for index, leg in enumerate(config.get("legs") or []):
        side = leg.get("side", "both")
        if side not in accepted:
            raise ValidationError(
                f"legs[{index}].side is {side!r}, which a {direction!r} strategy never acts on. "
                f"Use {' or '.join(sorted(accepted))}, or change the strategy direction."
            )


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


def _current_user() -> str | None:
    """The session username, the way every other session blueprint reads it."""
    return session.get("user")


def _ok(payload: dict | None = None, code: int = 200):
    body = {"status": "success"}
    if payload:
        body.update(payload)
    return jsonify(body), code


def _error(message: str, code: int, payload: dict | None = None):
    body = {"status": "error", "message": message}
    if payload:
        body.update(payload)
    return jsonify(body), code


def _store_error(message: str | None):
    """Map a store message to a status code.

    'Stop the strategy before ...' is a state conflict (409), a missing row is
    404, and anything else is ours rather than the caller's.
    """
    text = message or "The request could not be completed"
    if text == "Strategy not found":
        return _error(NOT_FOUND, 404)
    if text.startswith("Stop the strategy"):
        return _error(text, 409)
    if "already exists" in text:
        return _error(text, 409)
    return _error(text, 500)


def _sync_schedule(sid: int, *, removed: bool = False) -> None:
    """Bring this strategy's cron jobs in line with what was just saved.

    Without this the scheduler only ever reflects the configuration as it stood
    at boot: a schedule saved today would not fire until the next restart, an
    edited start time would keep firing at the old one, and a deleted strategy
    would leave its jobs behind. The job store is in memory precisely so that
    the database stays the single source of truth, which only holds if every
    write syncs.

    Never allowed to fail the request. The configuration is saved either way,
    and the next boot re-derives every job from it.
    """
    try:
        from services.strategy_module import scheduler

        if removed:
            scheduler.remove_strategy_jobs(sid)
        else:
            scheduler.sync_strategy_jobs(sid)
    except Exception:
        logger.exception("Could not sync scheduler jobs for strategy %s", sid)


def _resolve(sid: int):
    """``(username, row, error_response)`` for an owner-scoped route.

    A row belonging to somebody else is indistinguishable from one that does
    not exist: both answer 404. Returning 403 would confirm the id is real.
    """
    username = _current_user()
    if not username:
        return None, None, _error("Not authenticated", 401)
    row = store.get_strategy(sid, username)
    if not row:
        return username, None, _error(NOT_FOUND, 404)
    return username, row, None


def _json_body():
    """The request body as a dict, or ``(None, error_response)``."""
    payload = request.get_json(silent=True)
    if payload is None:
        return None, _error("A JSON body is required", 400)
    if not isinstance(payload, dict):
        return None, _error("The request body must be a JSON object", 400)
    return payload, None


def _int_arg(name: str) -> tuple[int | None, Any]:
    """An optional integer query parameter."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None, None
    try:
        return int(raw), None
    except ValueError:
        return None, _error(f"{name} must be a whole number", 400)


# ---------------------------------------------------------------------------
# Strategy CRUD
# ---------------------------------------------------------------------------


@strategy_module_bp.route("/api/strategies", methods=["GET"])
@check_session_validity
@_api_limit
def list_strategies():
    """Every strategy for the logged-in user, newest first."""
    username = _current_user()
    if not username:
        return _error("Not authenticated", 401)

    status = request.args.get("status")
    if status and status not in store.STRATEGY_STATUSES:
        return _error(
            f"status must be one of: {', '.join(store.STRATEGY_STATUSES)}",
            400,
        )
    query = (request.args.get("q") or "").strip()[:100]

    return _ok({"data": store.list_strategies(username, status=status, q=query or None)})


@strategy_module_bp.route("/api/strategies", methods=["POST"])
@check_session_validity
@_api_limit
def create_strategy():
    """Create a strategy and hand back its webhook token, once.

    The token is stored only as a SHA-256 digest, so this response is the only
    time it can be read. It is returned at the top level rather than inside
    ``data`` so it cannot be mistaken for a stored field that a later GET would
    return again.
    """
    username = _current_user()
    if not username:
        return _error("Not authenticated", 401)

    payload, error = _json_body()
    if error:
        return error

    config, message = validate_strategy_config(payload)
    if message:
        return _error(message, 400)

    created, store_message = store.create_strategy(username, config)
    if not created:
        return _store_error(store_message)

    token = created.pop("webhook_token", None)
    store.record_event(
        created["id"],
        username,
        "strategy_created",
        f"Strategy '{created['name']}' created",
    )
    _sync_schedule(created["id"])
    logger.info("Created strategy %s for %s", created["id"], username)
    return _ok(
        {
            "data": created,
            "webhook_token": token,
            "message": (
                "Copy the webhook token now. It is stored as a hash and cannot be "
                "shown again; rotate it if you lose it."
            ),
        },
        201,
    )


@strategy_module_bp.route("/api/strategies/<int:sid>", methods=["GET"])
@check_session_validity
@_api_limit
def get_strategy_detail(sid):
    """One strategy: configuration and legs. Never the webhook token."""
    _username, row, error = _resolve(sid)
    if error:
        return error
    return _ok({"data": store.strategy_to_dict(row)})


@strategy_module_bp.route("/api/strategies/<int:sid>", methods=["PATCH"])
@check_session_validity
@_api_limit
def update_strategy(sid):
    """Update a stopped strategy.

    The change set is checked against the store's own ``UPDATABLE_FIELDS``
    allowlist rather than a second list kept here, then merged onto the stored
    configuration and re-validated whole. Validating the fragment alone would
    let a two-field invariant be broken one request at a time.
    """
    username, row, error = _resolve(sid)
    if error:
        return error

    payload, error = _json_body()
    if error:
        return error
    if not payload:
        return _error("Nothing to update", 400)

    unknown = sorted(set(payload) - set(CONFIG_FIELDS))
    if unknown:
        return _error(
            f"The request does not accept {', '.join(unknown)}. "
            f"Updatable fields: {', '.join(sorted(CONFIG_FIELDS))}",
            400,
        )

    if row.status == "running":
        return _error("Stop the strategy before editing it", 409)

    # Refused here rather than left to the merge. strategy_kind is in
    # CONFIG_FIELDS because the merge seeds itself from that set and a signal
    # strategy whose kind was dropped would have its legs re-validated as batch
    # legs, failing on its own stored configuration. But that also let a PATCH
    # carry a kind: a changed one then failed on leg shape, naming a leg field
    # instead of the field the caller actually tried to change, and an
    # unchanged one was recorded as an update that changed nothing.
    requested_kind = payload.get("strategy_kind")
    if requested_kind is not None and requested_kind != row.strategy_kind:
        return _error(
            "A strategy cannot change between batch and signal. The two kinds do not "
            "share a leg shape, so every leg would describe the wrong kind of contract. "
            "Create a new strategy instead.",
            400,
        )
    payload.pop("strategy_kind", None)
    if not payload:
        return _error("Nothing to update", 400)

    stored = store.strategy_to_dict(row)
    merged = {field: stored[field] for field in CONFIG_FIELDS if field in stored}
    merged.update(payload)

    config, message = validate_strategy_config(merged)
    if message:
        return _error(message, 400)

    changes = {field: config[field] for field in payload if field in config}
    updated, store_message = store.update_strategy(sid, username, changes)
    if not updated:
        return _store_error(store_message)

    store.record_event(
        sid,
        username,
        "strategy_updated",
        f"Updated {', '.join(sorted(changes))}",
        payload={"fields": sorted(changes)},
    )
    # An edited start time must take effect now, not at the next restart.
    _sync_schedule(sid)
    return _ok({"data": updated})


@strategy_module_bp.route("/api/strategies/<int:sid>", methods=["DELETE"])
@check_session_validity
@_api_limit
def delete_strategy(sid):
    """Delete a stopped strategy and everything that belongs to it."""
    username, row, error = _resolve(sid)
    if error:
        return error
    if row.status == "running":
        return _error("Stop the strategy before deleting it", 409)

    deleted, message = store.delete_strategy(sid, username)
    if not deleted:
        return _store_error(message)

    _sync_schedule(sid, removed=True)
    logger.info("Deleted strategy %s for %s", sid, username)
    return _ok({"message": "Strategy deleted"})


# ---------------------------------------------------------------------------
# Webhook token, live mode, kill switch
# ---------------------------------------------------------------------------


@strategy_module_bp.route("/api/strategies/<int:sid>/webhook/rotate", methods=["POST"])
@check_session_validity
@_api_limit
def rotate_webhook(sid):
    """Issue a fresh webhook token. The old one stops working immediately."""
    username, _row, error = _resolve(sid)
    if error:
        return error

    token, message = store.rotate_webhook_token(sid, username)
    if not token:
        return _store_error(message)

    store.record_event(sid, username, "webhook_token_rotated", "Webhook token rotated")
    logger.info("Rotated the webhook token on strategy %s", sid)
    return _ok(
        {
            "webhook_token": token,
            "message": (
                "Copy the new webhook token now. The previous one no longer works "
                "and this one cannot be shown again."
            ),
        }
    )


@strategy_module_bp.route("/api/strategies/<int:sid>/live", methods=["POST"])
@check_session_validity
@_api_limit
def set_live(sid):
    """Turn live trading on or off. Body: ``{"enabled": true|false}``."""
    username, row, error = _resolve(sid)
    if error:
        return error

    payload, error = _json_body()
    if error:
        return error
    if "enabled" not in payload:
        return _error("enabled is required", 400)
    if not isinstance(payload["enabled"], bool):
        return _error("enabled must be true or false", 400)
    if row.status == "running":
        return _error("Stop the strategy before changing its mode", 409)

    enabled = payload["enabled"]
    changed, message = store.set_live_enabled(sid, username, enabled)
    if not changed:
        return _store_error(message)

    store.record_event(
        sid,
        username,
        "live_enabled" if enabled else "live_disabled",
        "Live trading enabled" if enabled else "Live trading disabled",
        severity="warn" if enabled else "info",
    )
    return _ok({"live_enabled": enabled})


@strategy_module_bp.route("/api/strategies/<int:sid>/kill_switch", methods=["POST"])
@check_session_validity
@_api_limit
def engage_kill_switch(sid):
    """Lock the webhook and flatten: every inbound signal is refused and audited."""
    username, row, error = _resolve(sid)
    if error:
        return error

    locked, message = store.set_webhook_locked(sid, username, True)
    if not locked:
        return _store_error(message)

    # Locking the webhook alone would stop new signals and leave whatever is
    # already open still exposed. A kill switch that does not flatten is not a
    # kill switch, so an active run is stopped too. The lock goes on first, so
    # a signal arriving mid-flatten cannot re-enter behind it.
    run_id = row.current_run_id
    stopped = False
    stop_pending = False
    exits = []
    accepted = False
    if run_id:
        from services.strategy_module import engine

        result = engine.stop_run(run_id, username, reason="manual")
        accepted = bool(result.get("ok"))
        stop_pending = bool(result.get("stop_pending", False))
        exits = result.get("exits", [])
        stopped = accepted and not stop_pending
        if not accepted:
            logger.error(
                "Kill switch on strategy %s locked the webhook but could not flatten run %s: %s",
                sid,
                run_id,
                result.get("error"),
            )

    if stopped:
        flatten_message = " and open legs closed"
    elif accepted and stop_pending:
        flatten_message = "; exit fills pending"
    elif stop_pending:
        flatten_message = "; flatten refused, stop remains pending and retryable"
    else:
        flatten_message = ""
    store.record_event(
        sid,
        username,
        "webhook_locked",
        "Kill switch engaged" + flatten_message,
        run_id=run_id,
        severity="critical",
    )
    logger.warning("Kill switch engaged on strategy %s by %s", sid, username)
    return _ok(
        {
            "webhook_locked": True,
            "run_stopped": stopped,
            "stop_pending": stop_pending,
            "exits": exits,
            "message": "Webhook locked" + flatten_message,
        }
    )


# ---------------------------------------------------------------------------
# Lifecycle
#
# These are the routes that move money. The engine is imported inside each
# handler rather than at module scope: it pulls in the order path, which
# imports restx_api, which imports back into the order path, and making this
# blueprint the entry point of that cycle fails with a partially initialised
# module. app.py never hits it because restx_api loads first.
# ---------------------------------------------------------------------------


@strategy_module_bp.route("/api/strategies/<int:sid>/start", methods=["POST"])
@check_session_validity
@_api_limit
def start_strategy(sid):
    """Start a run, in the mode the caller asks for.

    Mode is required and never defaulted. Defaulting it would mean a caller
    that forgot the field placing real orders on a strategy the operator
    believed was on paper.
    """
    username, _row, error = _resolve(sid)
    if error:
        return error

    body, body_error = _json_body()
    if body_error:
        return body_error

    mode = body.get("mode")
    if mode not in store.RUN_MODES:
        return _error(f"mode must be one of: {', '.join(sorted(store.RUN_MODES))}", 400)

    from services.strategy_module import engine

    result = engine.start_run(sid, username, mode, trigger_source="manual")
    if not result.ok:
        # A refusal here is a conflict or a bad configuration, not a server
        # fault; 409 lets the UI tell the two apart from a 400.
        code = 409 if "already running" in (result.error or "") else 400
        return _error(result.error or "Could not start the strategy", code)

    return _ok({"run_id": result.run_id, "mode": mode, "legs": result.legs})


@strategy_module_bp.route("/api/strategies/<int:sid>/stop", methods=["POST"])
@check_session_validity
@_api_limit
def stop_strategy(sid):
    """Exit every open leg at market and stop the run."""
    return _stop_run_for(sid, reason="manual")


@strategy_module_bp.route("/api/strategies/<int:sid>/close_all", methods=["POST"])
@check_session_validity
@_api_limit
def close_all(sid):
    """Same effect as stop, named for what the operator requested.

    Kept as its own route rather than an alias so the audit trail records the
    intent without claiming the broker is already flat.  Confirmed-flat
    finalisation is recorded separately when the exit orders settle.
    """
    return _stop_run_for(sid, reason="manual", event="close_all_manual")


def _stop_run_for(sid: int, reason: str, event: str | None = None):
    username, row, error = _resolve(sid)
    if error:
        return error

    run_id = row.current_run_id
    if not run_id:
        return _error("This strategy is not running", 409)

    from services.strategy_module import engine

    if event:
        store.record_event(
            sid,
            username,
            event,
            CLOSE_ALL_REQUESTED_MESSAGE,
            run_id=run_id,
        )

    result = engine.stop_run(run_id, username, reason=reason)
    if not result.get("ok"):
        return _error(
            result.get("error") or "Could not stop the run",
            409,
            {
                "stop_pending": result.get("stop_pending", False),
                "exits": result.get("exits", []),
            },
        )

    return _ok(
        {
            "run_id": run_id,
            "stop_pending": result.get("stop_pending", False),
            "exits": result.get("exits", []),
        }
    )


@strategy_module_bp.route("/api/strategies/<int:sid>/legs/<leg_id>/close", methods=["POST"])
@check_session_validity
@_api_limit
def close_one_leg(sid, leg_id):
    """Exit a single leg. The run continues with the rest.

    Deliberately does not trigger trail-to-entry: that rule answers the market
    moving against the book, and an operator closing one leg by hand is an
    override rather than a signal.
    """
    username, row, error = _resolve(sid)
    if error:
        return error

    run_id = row.current_run_id
    if not run_id:
        return _error("This strategy is not running", 409)

    from services.strategy_module import engine

    result = engine.close_leg(run_id, leg_id, username)
    if not result.get("ok"):
        return _error(result.get("error") or "Could not close that leg", 409)

    return _ok(
        {
            "run_id": run_id,
            "leg_id": leg_id,
            "run_stopped": result.get("run_stopped", False),
            "exits": result.get("exits", []),
        }
    )


@strategy_module_bp.route("/api/strategies/<int:sid>/unlock_webhook", methods=["POST"])
@check_session_validity
@_api_limit
def release_kill_switch(sid):
    """Release the webhook lock."""
    username, _row, error = _resolve(sid)
    if error:
        return error

    unlocked, message = store.set_webhook_locked(sid, username, False)
    if not unlocked:
        return _store_error(message)

    logger.info("Kill switch released on strategy %s by %s", sid, username)
    return _ok({"webhook_locked": False, "message": "Webhook unlocked"})


# ---------------------------------------------------------------------------
# Read-only history
#
# Every one of these resolves ownership first. list_runs, list_orders_for_
# strategy, list_events and list_webhook_events are all scoped by strategy_id in
# the store, so ownership of the strategy is enough. list_checkpoints is keyed
# on run_id, so that route both checks the run belongs here and passes the
# strategy id down to the store.
# ---------------------------------------------------------------------------


@strategy_module_bp.route("/api/strategies/<int:sid>/runs", methods=["GET"])
@check_session_validity
@_api_limit
def list_runs(sid):
    """Every activation of this strategy, newest first."""
    _username, _row, error = _resolve(sid)
    if error:
        return error
    return _ok({"data": store.list_runs(sid)})


@strategy_module_bp.route("/api/strategies/<int:sid>/orders", methods=["GET"])
@check_session_validity
@_api_limit
def list_orders(sid):
    """Orders across this strategy's runs, optionally narrowed to one run."""
    _username, _row, error = _resolve(sid)
    if error:
        return error

    run_id, error = _int_arg("run_id")
    if error:
        return error
    return _ok({"data": store.list_orders_for_strategy(sid, run_id=run_id)})


@strategy_module_bp.route("/api/strategies/<int:sid>/events", methods=["GET"])
@check_session_validity
@_api_limit
def list_events(sid):
    """The risk-event audit trail for this strategy."""
    _username, _row, error = _resolve(sid)
    if error:
        return error

    run_id, error = _int_arg("run_id")
    if error:
        return error

    kind = request.args.get("kind")
    if kind and kind not in store.EVENT_KINDS:
        return _error(f"kind must be one of: {', '.join(store.EVENT_KINDS)}", 400)

    severity = request.args.get("severity")
    if severity and severity not in store.EVENT_SEVERITIES:
        return _error(f"severity must be one of: {', '.join(store.EVENT_SEVERITIES)}", 400)

    requested, error = _int_arg("limit")
    if error:
        return error
    # Clamped rather than passed through: SQLite reads a negative LIMIT as
    # "no limit", so ?limit=-1 would serialize every event the strategy has.
    limit = min(max(requested or EVENTS_DEFAULT_LIMIT, 1), EVENTS_MAX_LIMIT)

    return _ok(
        {"data": store.list_events(sid, run_id=run_id, kind=kind, severity=severity, limit=limit)}
    )


@strategy_module_bp.route("/api/strategies/<int:sid>/webhook_events", methods=["GET"])
@check_session_validity
@_api_limit
def list_webhook_events(sid):
    """Every inbound webhook for this strategy, accepted or rejected."""
    _username, _row, error = _resolve(sid)
    if error:
        return error
    return _ok({"data": store.list_webhook_events(sid)})


def _api_key_for(username: str) -> str | None:
    """The user's own API key, for the server-side broker calls these views make."""
    try:
        from database.auth_db import get_api_key_for_tradingview

        return get_api_key_for_tradingview(username)
    except Exception:
        logger.exception("Could not read the API key for %s", username)
        return None


def _book(sid: int, fetch):
    """Shared shape for the three broker-backed views."""
    username, _row, error = _resolve(sid)
    if error:
        return error

    run_id, error = _int_arg("run_id")
    if error:
        return error

    api_key = _api_key_for(username)
    if not api_key:
        return _error("No API key is configured for this user", 400)

    payload = fetch(sid, api_key, run_id)
    if payload.get("status") != "success":
        # The broker's own refusal, passed through rather than reshaped: the
        # message is more useful than anything this layer could invent.
        return jsonify(payload), 502
    return jsonify(payload), 200


@strategy_module_bp.route("/api/strategies/<int:sid>/orderbook", methods=["GET"])
@check_session_validity
@_api_limit
def strategy_orderbook(sid):
    """This strategy's orders, as the broker currently reports them.

    Not derived from the stored rows. Those record what was placed; the broker
    knows what actually happened to it, and for money that difference is the
    whole point. The envelope matches the global /orderbook exactly, so the
    same table renders it.
    """
    from services.strategy_module import views

    return _book(sid, views.strategy_orderbook)


@strategy_module_bp.route("/api/strategies/<int:sid>/tradebook", methods=["GET"])
@check_session_validity
@_api_limit
def strategy_tradebook(sid):
    """This strategy's fills, as the broker reports them."""
    from services.strategy_module import views

    return _book(sid, views.strategy_tradebook)


@strategy_module_bp.route("/api/strategies/<int:sid>/positions", methods=["GET"])
@check_session_validity
@_api_limit
def strategy_positions(sid):
    """This strategy's positions, filtered from the broker's position book.

    A weaker guarantee than the orderbook, and deliberately so: a position row
    is per contract, so if the same contract is also held from a manual order
    or another strategy, the row is shared and cannot be divided. The
    strategy's reported P&L comes from its own fills, never from these rows.
    """
    from services.strategy_module import views

    return _book(sid, views.strategy_positions)


@strategy_module_bp.route("/api/strategies/<int:sid>/checkpoints", methods=["GET"])
@check_session_validity
@_api_limit
def list_checkpoints(sid):
    """Runtime snapshots for one run, oldest first: the P&L curve of a session.

    Defaults to the current run, then to the most recent one. A requested run
    is checked against this strategy, and the strategy id is passed to the
    store as well, so neither layer alone is load bearing.
    """
    _username, row, error = _resolve(sid)
    if error:
        return error

    run_id, error = _int_arg("run_id")
    if error:
        return error

    if run_id is None:
        run_id = row.current_run_id
        if run_id is None:
            recent = store.list_runs(sid, limit=1)
            run_id = recent[0]["id"] if recent else None
        if run_id is None:
            return _ok({"data": [], "run_id": None})
    else:
        run = store.get_run(run_id)
        if not run or run.strategy_id != sid:
            return _error("Run not found", 404)

    # Scoped at both layers: the check above gives a useful 404, and the
    # strategy_id narrows the query itself so the store cannot answer for
    # another strategy's run even if that check were ever removed.
    return _ok({"data": store.list_checkpoints(run_id, strategy_id=sid), "run_id": run_id})


# ---------------------------------------------------------------------------
# Public webhook
#
# CSRF exempt and unauthenticated by design: the URL token is the credential.
# Exempted in app.py, beside the /chartink and /flow webhooks.
# ---------------------------------------------------------------------------


@strategy_module_bp.route("/webhook/<token>", methods=["POST"])
@_webhook_caller_limit
@_webhook_token_limit
def webhook(token):
    """Take one inbound alert and hand it to the validation pipeline.

    Every decision lives in services/strategy_module/webhook.py, which audits
    each outcome and never raises. This route only reads the request and turns
    the outcome into a response.

    An unknown token is answered here rather than by aborting, because an
    unauthenticated 404 feeds Error404Tracker and counts toward an IP ban. A
    scanner walking the token space must not be able to get the owner's own
    address banned, and a legitimate alert carrying a rotated token deserves a
    clear answer rather than a redirect.
    """
    from services.strategy_module.webhook import MAX_PAYLOAD_BYTES, handle_webhook

    # Refuse an oversized body from the header, before reading it. The cap
    # applied inside the pipeline is measured on bytes already in memory, so
    # an unauthenticated caller could make the worker read whatever it sent
    # before anything checked the token.
    declared = request.content_length
    if declared is not None and declared > MAX_PAYLOAD_BYTES:
        return jsonify(
            {
                "status": "error",
                "message": f"Payload larger than {MAX_PAYLOAD_BYTES} bytes",
            }
        ), 413

    outcome = handle_webhook(
        token,
        request.get_data(cache=False),
        # get_real_ip, not remote_addr: behind a reverse proxy, which is how
        # most installs run, remote_addr is the proxy and every caller looks
        # like the same address. The IP allowlist is then either useless or
        # blocks everything, and the audit trail names the proxy.
        ip=get_real_ip(),
        user_agent=request.headers.get("User-Agent"),
    )
    body, status = outcome.as_response()
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Live updates
#
# A page watching one strategy joins that strategy's room and is pushed to,
# instead of polling. Rooms are per strategy rather than per user: a page open
# on strategy 4 must not be woken by strategy 9's ticks.
#
# The default Socket.IO namespace has no connect-time authentication in this
# codebase, so ownership is checked here, on the join. Without that a connected
# client could name any id and receive another strategy's live P&L and
# positions. Answering the same way for a strategy that is not yours and one
# that does not exist keeps the id space unprobeable, as the REST routes do.
# ---------------------------------------------------------------------------


@socketio.on("strategy_subscribe")
def _strategy_subscribe(data):
    """Join a strategy's live room, if the caller owns it."""
    username = _current_user()
    if not username:
        return {"status": "error", "message": "Not authenticated"}

    try:
        sid = int((data or {}).get("strategy_id"))
    except (TypeError, ValueError):
        return {"status": "error", "message": "strategy_id is required"}

    if not store.get_strategy(sid, username):
        return {"status": "error", "message": NOT_FOUND}

    from services.strategy_module import broadcast

    join_room(broadcast.room_for(sid))
    logger.debug("Socket joined strategy room %s for %s", sid, username)

    # Send the current picture immediately rather than leaving the page blank
    # until the next tick. A stopped strategy has no run state, and the client
    # falls back to its REST read for that case.
    row = store.get_strategy(sid, username)
    if row and row.current_run_id:
        broadcast.push_snapshot(row.current_run_id)
    return {"status": "success", "strategy_id": sid}


@socketio.on("strategy_unsubscribe")
def _strategy_unsubscribe(data):
    """Leave a strategy's live room."""
    try:
        sid = int((data or {}).get("strategy_id"))
    except (TypeError, ValueError):
        return {"status": "error", "message": "strategy_id is required"}

    from services.strategy_module import broadcast

    leave_room(broadcast.room_for(sid))
    return {"status": "success", "strategy_id": sid}
