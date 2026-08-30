# blueprints/strategy_module.py
"""HTTP surface for the /strategy module: multi-leg options strategies.

This phase is configuration and read-only history. Lifecycle (start, stop,
pause, close-all) and the inbound webhook belong to the engine and are not
routed here yet, so nothing in this file can reach a broker.

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

import ipaddress
import math
import os
import re
from datetime import time as dt_time
from typing import Any

from flask import Blueprint, jsonify, request, session

from database import strategy_module_db as store
from limiter import limiter
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


# ---------------------------------------------------------------------------
# Vocabulary
#
# The enums the store exports are used directly. Everything below is a value
# this layer owns: the store has no opinion on a leg's shape, because legs live
# in a JSON column.
# ---------------------------------------------------------------------------

#: The store's PATCH allowlist doubles as the create allowlist. Sharing it is
#: deliberate: two lists would drift, and the second one would be the loose one.
CONFIG_FIELDS = store.UPDATABLE_FIELDS

PRODUCTS = ("CNC", "NRML", "MIS")
PRICETYPES = ("MARKET", "LIMIT", "SL", "SL-M")

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

LEG_SEGMENTS = ("options", "futures", "cash")
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
)
TRAIL_FIELDS = ("x", "y")
LOCK_PROFIT_FIELDS = ("mode", "if_profit_reaches", "lock_profit", "trail_step")
SCHEDULER_FIELDS = ("enabled", "days", "start_time", "auto_stop_time", "default_mode")

MIN_LEGS = 1
MAX_LEGS = 10
MAX_LOTS = 50
MAX_NAME_LENGTH = 200
MAX_UNIVERSE_TAB_LENGTH = 30
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


def _validate_trail(raw: Any, label: str) -> dict | None:
    """``{x, y}``: advance the stop by y for every x points of favourable move.

    Both halves are required together. A trail with only one of them configured
    is not a partially configured trail, it is one that never moves.
    """
    if raw is None:
        return None
    data = _mapping(raw, label)
    _reject_unknown(data, TRAIL_FIELDS, label)
    return {
        "x": _number(_required(data, "x", label), f"{label}.x", minimum=0),
        "y": _number(_required(data, "y", label), f"{label}.y", minimum=0),
    }


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
        "lots": _integer(
            _required(leg, "lots", label), f"{label}.lots", minimum=1, maximum=MAX_LOTS
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

    if leg.get("sl_pts") is not None:
        clean["sl_pts"] = _number(leg["sl_pts"], f"{label}.sl_pts", minimum=0)
    if leg.get("target_pts") is not None:
        clean["target_pts"] = _number(leg["target_pts"], f"{label}.target_pts", minimum=0)
    trail = _validate_trail(leg.get("trail"), f"{label}.trail")
    if trail is not None:
        clean["trail"] = trail

    return clean


def _validate_legs(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        raise ValidationError("legs must be a list")
    if len(raw) < MIN_LEGS:
        raise ValidationError(f"A strategy needs at least {MIN_LEGS} leg")
    if len(raw) > MAX_LEGS:
        raise ValidationError(f"A strategy takes at most {MAX_LEGS} legs, got {len(raw)}")
    legs = [_validate_leg(leg, index) for index, leg in enumerate(raw)]

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

    config: dict[str, Any] = {
        "name": _text(_required(raw, "name"), "name", max_length=MAX_NAME_LENGTH),
        "strategy_kind": _choice(
            raw.get("strategy_kind") or "batch", store.STRATEGY_KINDS, "strategy_kind"
        ),
        # Only read for signal strategies; harmless and inert on a batch one.
        "direction": _choice(raw.get("direction") or "both", store.DIRECTIONS, "direction"),
        "universe_tab": _text(
            raw.get("universe_tab") or "weekly_monthly",
            "universe_tab",
            max_length=MAX_UNIVERSE_TAB_LENGTH,
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
        "legs": _validate_legs(_required(raw, "legs")),
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

    return config


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


def _error(message: str, code: int):
    return jsonify({"status": "error", "message": message}), code


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
    """Lock the webhook: every inbound signal is refused and audited."""
    username, _row, error = _resolve(sid)
    if error:
        return error

    locked, message = store.set_webhook_locked(sid, username, True)
    if not locked:
        return _store_error(message)

    logger.warning("Kill switch engaged on strategy %s by %s", sid, username)
    return _ok({"webhook_locked": True, "message": "Webhook locked"})


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
