"""Signal-mode strategies: one TradingView alert moves one leg.

Batch mode enters every leg together on ``start`` and exits them together on
``stop``, which is what a multi-leg options spread wants. Signal mode is the
other shape: an alert fires one action at a time, a strategy may hold several
unrelated symbols, and quantity is raw shares rather than lots.

    {"action": "long_entry", "leg_id": 1}
    {"action": "short_exit", "symbol": "RELIANCE", "exchange": "NSE"}

Same tables, same engine machinery for state, orders, risk and recovery. What
differs is the protocol and the leg shape.

Three things here are deliberately not errors, because an alert engine repeats
itself and a strategy should not fight it:

    long_exit on a leg that is flat        -> no-op, "no_matching_position"
    long_entry on a leg already long       -> no-op, "already_long"
    any signal outside the trading window  -> no-op, naming the window

Each is recorded and answered 200. A refusal that reads as a failure invites a
retry, and a retry on an order path is how one alert becomes two positions.

Being rejected is different from being a no-op. A signal blocked by the
strategy's direction, or by the leg's own side, is a configuration mismatch the
operator should see, and answers as a refusal.

A leg that exits returns to "configured" rather than "closed": the same symbol
can be signalled again the same day. Its realized P&L accumulates on the leg,
and services/risk/ counts realized from any leg that has it rather than only
from closed ones.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from typing import Any

import pytz

from database import strategy_module_db as store
from services.strategy_module import order_dispatch, session, state
from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")

#: The four actions a signal-mode strategy accepts.
SIGNAL_ACTIONS = ("long_entry", "long_exit", "short_entry", "short_exit")

#: What a batch-mode strategy accepts. The router is shared; the validator
#: branches on the strategy's kind, so a start against a signal strategy and a
#: long_entry against a batch one are both refused rather than half-handled.
BATCH_ACTIONS = ("start", "stop")

_LONG = "long"
_SHORT = "short"

_SIDE_OF_ACTION = {
    "long_entry": _LONG,
    "long_exit": _LONG,
    "short_entry": _SHORT,
    "short_exit": _SHORT,
}

_IS_ENTRY = {"long_entry", "short_entry"}

#: side -> the B/S the run state records for a leg held that way.
_POSITION_OF_SIDE = {_LONG: "B", _SHORT: "S"}

_DIRECTION_ALLOWS = {
    "both": {_LONG, _SHORT},
    "long_only": {_LONG},
    "short_only": {_SHORT},
}


@dataclass
class SignalResult:
    """What one signal did, or why it did nothing."""

    ok: bool
    note: str | None = None
    error: str | None = None
    leg_id: Any = None
    run_id: int | None = None
    flipped: bool = False

    @property
    def acted(self) -> bool:
        """Whether an order was actually placed."""
        return self.ok and self.note is None


@dataclass(frozen=True)
class _StrategySnapshot:
    """Plain signal configuration safe across commits and session cleanup."""

    id: int
    user_id: str
    current_run_id: int | None
    live_enabled: bool
    strategy_type: str
    entry_time: Any
    exit_time: Any
    legs: list[dict[str, Any]]
    direction: str
    product: str
    name: str
    pricetype: str


def _snapshot_strategy(strategy: Any) -> _StrategySnapshot:
    current_run_id = getattr(strategy, "current_run_id", None)
    return _StrategySnapshot(
        id=int(strategy.id),
        user_id=str(strategy.user_id),
        current_run_id=int(current_run_id) if current_run_id is not None else None,
        live_enabled=bool(getattr(strategy, "live_enabled", False)),
        strategy_type=str(getattr(strategy, "strategy_type", "intraday") or "intraday"),
        entry_time=getattr(strategy, "entry_time", None),
        exit_time=getattr(strategy, "exit_time", None),
        legs=[dict(leg) for leg in (getattr(strategy, "legs", None) or [])],
        direction=str(getattr(strategy, "direction", "both") or "both"),
        product=str(getattr(strategy, "product", "MIS") or "MIS"),
        name=str(getattr(strategy, "name", "") or ""),
        pricetype=str(getattr(strategy, "pricetype", "MARKET") or "MARKET"),
    )


def actions_for(strategy_kind: str) -> tuple[str, ...]:
    """Which actions this kind of strategy accepts."""
    return SIGNAL_ACTIONS if strategy_kind == "signal" else BATCH_ACTIONS


def _now_ist() -> datetime:
    return datetime.now(IST)


def _window_note(strategy: Any, action: str) -> str | None:
    """Why this signal is outside the strategy's trading window, if it is.

    Entries stop at ``entry_time`` and everything stops at ``exit_time``. Exits
    are deliberately allowed before the entry window opens: a position carried
    in from a previous session must always be closable.
    """
    if getattr(strategy, "strategy_type", "intraday") != "intraday":
        return None

    now = _now_ist().time()
    entry_time = getattr(strategy, "entry_time", None)
    exit_time = getattr(strategy, "exit_time", None)

    if exit_time and now >= exit_time:
        return "outside_trading_window"
    if action in _IS_ENTRY and entry_time and now < entry_time:
        return "outside_entry_window"
    return None


def _find_leg(strategy: Any, leg_id: Any, symbol: str | None, exchange: str | None) -> dict | None:
    """The configured leg this signal targets.

    ``leg_id`` wins when both are given. The symbol fallback exists because an
    alert template is often written once and reused across strategies, where
    the leg numbering differs but the instrument does not.
    """
    legs = getattr(strategy, "legs", None) or []
    if leg_id is not None:
        wanted = str(leg_id)
        for leg in legs:
            if str(leg.get("id") or leg.get("leg_id")) == wanted:
                return leg
        return None

    if symbol:
        want_symbol = str(symbol).upper()
        want_exchange = str(exchange or "").upper()
        for leg in legs:
            if str(leg.get("symbol", "")).upper() != want_symbol:
                continue
            if want_exchange and str(leg.get("exchange", "")).upper() != want_exchange:
                continue
            return leg
    return None


def _leg_id_of(leg: dict) -> Any:
    return leg.get("id") or leg.get("leg_id")


def _day_run(strategy: Any) -> tuple[int | None, str | None]:
    """The run this signal belongs to, opening one if the day has none.

    A signal strategy has one run per trading day rather than one per start and
    stop: there is no start. The first signal of the day opens it and the
    scheduler's square-off closes it.

    Mode is not in the payload, so it is taken from the strategy's own opt-in:
    live only if the operator has explicitly enabled it, sandbox otherwise. The
    safe direction is the default.
    """
    strategy_id = int(strategy.id)
    user_id = str(strategy.user_id)
    run_id = getattr(strategy, "current_run_id", None)
    live_enabled = bool(getattr(strategy, "live_enabled", False))
    if run_id:
        run = store.get_run(run_id)
        if run and run.stopped_at is None:
            if not _started_before_today(run):
                return run_id, None

            # An open run from an earlier day. It should have been squared off
            # at its exit time; that it was not means the scheduler was down,
            # the process was restarted past the auto-stop, or the strategy is
            # positional and has none.
            #
            # Rolling it matters because a signal run IS a trading day: its
            # P&L, peak, trough and audit trail describe that day. Reusing it
            # merges every following day into the first, and a strategy left
            # alone over a long weekend silently reports one run spanning four
            # sessions.
            #
            # Route every stale run through the durable stop lifecycle. Its
            # management predicate includes superseded positions, working or
            # configured entries, in-flight signal claims, and unavailable
            # live state. Only confirmed flatness permits a replacement run.
            logger.info("Rolling signal run %s through end-of-day stop", run_id)
            if not _finalise_stale_run(strategy, run_id):
                return run_id, None

    mode = "live" if live_enabled else "sandbox"
    api_key = _api_key_for(user_id)
    broker = ""
    if mode == "live" and api_key:
        try:
            from database.auth_db import get_auth_token_broker

            _token, broker = get_auth_token_broker(api_key)
        except Exception:
            logger.exception("Could not read the broker for a signal run")

    if not store.claim_strategy_for_run(strategy_id):
        # Something else opened one between the read above and here.
        refreshed = store.get_strategy_unscoped(strategy_id)
        if refreshed and refreshed.current_run_id:
            return refreshed.current_run_id, None
        return None, "This strategy is already running"

    run = store.create_run(
        strategy_id=strategy_id,
        mode=mode,
        broker=broker or mode,
        trigger_source="webhook",
    )
    if not run:
        store.release_strategy(strategy_id)
        return None, "Could not open a run"

    # Store calls commit and synchronous order replay removes scoped sessions.
    # Never retain an ORM row beyond the boundary that created it.
    new_run_id = int(run.id)
    if not store.set_strategy_status(strategy_id, "running", new_run_id):
        cleaned = store.finish_unlinked_run_and_release_claim(
            new_run_id,
            strategy_id,
            "error",
        )
        if not cleaned:
            logger.critical(
                "Signal run %s could not be linked to strategy %s and its empty claim "
                "could not be fully released",
                new_run_id,
                strategy_id,
            )
        return None, "Could not link the new signal run; no order was placed"
    state.init_run_state(new_run_id, strategy_id, [])
    store.record_event(
        strategy_id,
        user_id,
        "run_started",
        f"Signal run opened in {mode} mode",
        run_id=new_run_id,
    )
    return new_run_id, None


# Both live in services/strategy_module/session.py now: the engine needs the
# same boundary for the daily loss limit and neither module may import the
# other. Re-exported under their old names so this file reads as it did.
_session_reset_time = session.session_reset_time
_session_day = session.session_day


def _started_before_today(run: Any) -> bool:
    """Whether a run began in an earlier trading session.

    Timestamps are stored naive UTC, so the value is converted to IST before
    the session is worked out. Comparing a UTC date against an IST one would
    move the boundary by five and a half hours.
    """
    started = getattr(run, "started_at", None)
    if started is None:
        return False
    started_ist = started.replace(tzinfo=UTC).astimezone(IST)
    return _session_day(started_ist) < _session_day(_now_ist())


def _finalise_stale_run(strategy: Any, run_id: int) -> bool:
    """Stop one stale run and say whether confirmed flatness won."""
    from services.strategy_module import engine

    strategy_id = int(strategy.id)
    user_id = str(strategy.user_id)
    result = engine.stop_run(run_id, user_id, reason="eod")
    confirmed = bool(result.get("ok")) and not bool(result.get("stop_pending"))
    if not confirmed:
        return False
    store.record_event(
        strategy_id,
        user_id,
        "eod_squareoff",
        "Previous day's run closed on the first signal of a new day",
        run_id=run_id,
        severity="warn",
    )
    return True


def _api_key_for(user_id: str) -> str | None:
    try:
        from database.auth_db import get_api_key_for_tradingview

        return get_api_key_for_tradingview(user_id)
    except Exception:
        logger.exception("Could not read the API key for %s", user_id)
        return None


def handle_signal(
    strategy: Any,
    action: str,
    *,
    leg_id: Any = None,
    symbol: str | None = None,
    exchange: str | None = None,
) -> SignalResult:
    """Apply one signal to one leg."""
    if action not in SIGNAL_ACTIONS:
        return SignalResult(ok=False, error=f"Unknown signal action: {action!r}")

    # A stale-day stop and a synchronous sandbox replay can both clean scoped
    # sessions before this call reaches _enter/_exit. The signal configuration
    # is immutable for this decision, so carry a plain snapshot, never the ORM
    # instance, across _day_run and broker dispatch.
    strategy = _snapshot_strategy(strategy)

    side = _SIDE_OF_ACTION[action]

    allowed = _DIRECTION_ALLOWS.get(
        getattr(strategy, "direction", "both") or "both", {_LONG, _SHORT}
    )
    if side not in allowed:
        return SignalResult(
            ok=False,
            error=f"This strategy is {strategy.direction}; a {side} signal is not accepted",
        )

    leg = _find_leg(strategy, leg_id, symbol, exchange)
    if leg is None:
        return SignalResult(ok=False, error="No leg matches this signal")
    resolved_leg_id = _leg_id_of(leg)

    leg_side = str(leg.get("side") or "both").lower()
    if leg_side != "both" and leg_side != side:
        return SignalResult(
            ok=False,
            leg_id=resolved_leg_id,
            error=f"Leg {resolved_leg_id} only accepts {leg_side} signals",
        )

    note = _window_note(strategy, action)
    if note:
        return SignalResult(ok=True, note=note, leg_id=resolved_leg_id)

    run_id, error = _day_run(strategy)
    if error or not run_id:
        return SignalResult(ok=False, leg_id=resolved_leg_id, error=error or "No run")

    if action in _IS_ENTRY:
        run_row = store.get_run(run_id)
        if run_row is not None and run_row.stop_requested_reason is not None:
            return SignalResult(
                ok=False,
                note="run_stopping",
                leg_id=resolved_leg_id,
                run_id=run_id,
            )
        return _enter(strategy, run_id, leg, side)
    return _exit(strategy, run_id, leg, side)


def _held_side(run_id: int, leg_id: Any) -> str | None:
    """Which side the run currently holds this leg, if any."""
    with state.run_state(run_id) as run:
        if run is None:
            return None
        live = run["legs"].get(str(leg_id))
        if live is None or live.get("status") != "open":
            return None
        return _LONG if live.get("position") == "B" else _SHORT


def _enter(strategy: Any, run_id: int, leg: dict, side: str) -> SignalResult:
    """Open a leg on the requested side, flipping it if it is on the other."""
    leg_id = _leg_id_of(leg)
    claim = state.claim_signal_entry(run_id, leg_id, _POSITION_OF_SIDE[side])
    if claim is None:
        return SignalResult(ok=False, leg_id=leg_id, run_id=run_id, error="No active run")
    if claim.get("note"):
        return SignalResult(
            ok=claim["note"] != "run_stopping",
            note=claim["note"],
            leg_id=leg_id,
            run_id=run_id,
        )

    claim_token = claim["claim_token"]
    try:
        held_position = claim.get("held_position")
        held = _LONG if held_position == "B" else _SHORT if held_position == "S" else None

        # A short that the product cannot carry, refused before anything is
        # squared. The form refuses a leg configured short outright, but a leg
        # that accepts both sides is a normal intraday configuration and only
        # the signal says which way it is about to open. Cash sold short under
        # a carry product is a naked short delivery: the broker refuses it, and
        # until it did nothing here said so.
        #
        # Order matters more than it looks. Checked after the flip below, a
        # short_entry on a leg held long squared that long and only then
        # refused the short, so a signal that was never going to open anything
        # liquidated a position instead. A refusal must cost nothing.
        short_error = _reject_uncarryable_short(strategy, leg, side)
        if short_error:
            return SignalResult(ok=False, leg_id=leg_id, error=f"Leg {leg_id}: {short_error}")

        flipped = False
        if held is not None:
            # Opposite side: square first, then open. Reversing without closing
            # would leave both positions on the book.
            closed = _exit(strategy, run_id, leg, held)
            if not closed.ok or closed.note is not None:
                return closed
            flipped = True

        # Resolves the quantity too, which in lots mode means multiplying by the
        # lot size from the master contract. This is the authoritative pass: the
        # form checks as well, but a strategy saved before the master contract was
        # downloaded, or edited directly, reaches here unchecked.
        resolved, error = _resolve_signal_leg(leg, side)
        if error:
            return SignalResult(ok=False, leg_id=leg_id, error=f"Leg {leg_id}: {error}")

        resolved["position_ref"] = claim["position_ref"]
        outcome = _place(
            strategy,
            run_id,
            resolved,
            "entry",
            _POSITION_OF_SIDE[side],
            entry_claim=claim,
        )
        if not outcome.ok:
            return SignalResult(ok=False, leg_id=leg_id, run_id=run_id, error=outcome.error)

        return SignalResult(ok=True, leg_id=leg_id, run_id=run_id, flipped=flipped)
    finally:
        released = state.release_signal_entry_claim(run_id, leg_id, claim_token)
        if released:
            # Every refusal before finish_signal_entry leaves the exact claim
            # here. A stop may have become durable at any resolver/auth/store/
            # install seam; release first, then do database/broker work after
            # the run lock has exited.
            from services.strategy_module import engine

            engine.reconcile_pending_stop(run_id)


def _reject_uncarryable_short(strategy: Any, leg: dict, side: str) -> str | None:
    """Why this short cannot be opened, or None if it can.

    Cash equity is sold short intraday and never carried short: a delivery sell
    has to be covered by stock the account holds. The product is read as intent
    everywhere in this module, so anything that is not MIS reaches a cash venue
    as CNC, which makes the order a naked short delivery.
    """
    if side != _SHORT:
        return None
    product = str(getattr(strategy, "product", "MIS") or "MIS").upper()
    if product == "MIS":
        return None

    from services.strategy_module.symbol_resolver import DERIVATIVE_EXCHANGES

    exchange = str(leg.get("exchange") or "").upper()
    if not exchange or exchange in DERIVATIVE_EXCHANGES:
        return None
    return (
        f"cash cannot be held short overnight, and product {product} carries the position. "
        f"Use MIS for an intraday short."
    )


def _resolve_signal_leg(leg: dict, side: str) -> tuple[dict | None, str | None]:
    """A signal leg in the shape run state expects, or the reason it is not.

    The side comes from the signal, never from the configuration. A signal leg
    is configured with which signals it *accepts*, which is not the same as
    which way it is currently held, and conflating the two is how a long leg
    ends up evaluated as a short.

    The quantity is resolved here rather than taken as written. In lots mode
    the configured number is a lot count and the quantity is that count times
    the lot size from the master contract, so five lots of NIFTY at a lot size
    of 65 becomes 325. Storing the lot count rather than the product is what
    lets a leg survive an exchange revising its lot size.
    """
    from services.strategy_module.symbol_resolver import (
        contract_exists,
        resolve_quantity,
    )

    symbol = leg.get("symbol")
    exchange = leg.get("exchange")
    raw_qty = leg.get("qty") or leg.get("quantity")
    if not symbol or not exchange or not raw_qty:
        return None, "symbol, exchange and quantity are all required"

    symbol = str(symbol).upper()
    exchange = str(exchange).upper()

    # A signal leg names its instrument outright, so this is the only place
    # that can tell whether it names a real one. A futures leg configured as
    # the base symbol produced an entirely plausible quantity, because the lot
    # size is read from the root, and then sent the literal base to the broker
    # as an order. Batch mode refuses the same leg with contract_not_found.
    #
    # Checked on every venue, cash included. Guarding this on a derivative
    # exchange left a misspelled equity as the one instrument nothing verified:
    # a cash leg is not resolved from an underlying either, so "RELAINCE" on
    # NSE reached the broker verbatim while batch mode refused the identical
    # typo. contract_exists answers True when the master contract has no rows
    # for the venue at all, so a fresh install is still not blocked.
    if not contract_exists(symbol, exchange):
        return None, f"{symbol} is not a contract on {exchange}"
    quantity, lot_size, error = resolve_quantity(
        raw_qty, leg.get("qty_mode") or "units", symbol, exchange
    )
    if error:
        return None, error

    return {
        "leg_id": _leg_id_of(leg),
        "position": _POSITION_OF_SIDE[side],
        "symbol": symbol,
        "exchange": exchange,
        "quantity": quantity,
        # The lot count, so the UI and the audit trail can show what was
        # configured rather than only what was sent.
        "lots": int(raw_qty) if leg.get("qty_mode") == "lots" else 1,
        "lot_size": lot_size,
        "sl_pts": leg.get("sl_pts"),
        "target_pts": leg.get("target_pts"),
        "trail": leg.get("trail") or {},
        "risk_unit": leg.get("risk_unit") or "points",
    }, None


def _exit(strategy: Any, run_id: int, leg: dict, side: str) -> SignalResult:
    """Close a leg held on the requested side, or say it was not."""
    leg_id = _leg_id_of(leg)
    held = _held_side(run_id, leg_id)
    if held != side:
        # Before calling this flat: a flip whose closing order was refused
        # leaves the outgoing position held while the leg describes the new
        # one, so an exit for the old side is real and has nowhere else to go.
        outgoing = state.claim_superseded_exit(run_id, leg_id, _POSITION_OF_SIDE[side])
        if outgoing is not None:
            placed = _place(
                strategy,
                run_id,
                outgoing,
                "exit_signal",
                outgoing["position"],
                True,
                exit_owner="superseded",
            )
            if not placed.ok:
                released = state.release_superseded_exit(run_id, leg_id, placed.exit_claim_id)
                if released:
                    from services.strategy_module import order_events

                    order_events.report_flip_outgoing_exit_rejected(run_id, leg_id, "refused")
                return SignalResult(ok=False, leg_id=leg_id, run_id=run_id, error=placed.error)
            return SignalResult(ok=True, leg_id=leg_id, run_id=run_id)

        # Flat, or held the other way. An exit for something not held is not a
        # failure; the alert simply arrived after the position had gone.
        return SignalResult(ok=True, note="no_matching_position", leg_id=leg_id, run_id=run_id)

    # Claim the leg before dispatching. A leg stays "open" until its exit fill
    # arrives, so a repeated exit alert, or a late one after the scheduler had
    # already squared off, found _held_side still answering and sent a second
    # closing order: the account ended up positioned the opposite way. Signal
    # mode is precisely the mode driven by an alert engine that repeats itself.
    snapshot = state.claim_leg_exit(run_id, leg_id, "exit_signal")
    if snapshot is None:
        # Two very different reasons the claim can fail, and they must not be
        # answered the same way. An exit already in flight, or a leg that is no
        # longer held, is a no-op: reporting it as a failure would invite the
        # retry that turns one alert into two positions. An entry the broker
        # has accepted but not filled is neither, and answering "nothing held"
        # there lets a flip open the opposite side while the original entry is
        # still working, leaving both on the book.
        run_state = state.get_run_state(run_id) or {}
        live = (run_state.get("legs") or {}).get(str(leg_id)) or {}
        if live.get("status") == "open" and live.get("entry_status") != "complete":
            return SignalResult(
                ok=False,
                leg_id=leg_id,
                run_id=run_id,
                error=(
                    "The entry for this leg has been accepted but not filled, so there is no "
                    "confirmed quantity to exit. Retry once it fills."
                ),
            )
        return SignalResult(ok=True, note="no_matching_position", leg_id=leg_id, run_id=run_id)

    outcome = _place(strategy, run_id, snapshot, "exit_signal", snapshot["position"], exiting=True)
    if not outcome.ok:
        # Leave the leg exitable: its stop loss, its target and the square-off
        # all skip a leg that still looks like it has an exit in flight.
        state.release_leg_exit(run_id, leg_id, outcome.exit_claim_id)
        return SignalResult(ok=False, leg_id=leg_id, run_id=run_id, error=outcome.error)

    return SignalResult(ok=True, leg_id=leg_id, run_id=run_id)


@dataclass
class _Placement:
    ok: bool
    error: str | None = None
    exit_claim_id: Any = None


def _place(
    strategy: Any,
    run_id: int,
    leg: dict,
    kind: str,
    position: str,
    exiting: bool = False,
    exit_owner: str = "live",
    entry_claim: dict | None = None,
) -> _Placement:
    """Place one signal-driven order and record it."""
    # Dispatch may synchronously publish a fill whose cleanup removes every
    # scoped session on this thread. Snapshot every strategy scalar needed by
    # acknowledgement and audit before the broker call.
    strategy_id = int(strategy.id)
    user_id = str(strategy.user_id)
    strategy_product = getattr(strategy, "product", "MIS")
    strategy_name = getattr(strategy, "name", "")
    strategy_pricetype = getattr(strategy, "pricetype", "MARKET")
    exit_claim_id = (
        leg.get("claim_token")
        if exit_owner == "superseded"
        else leg.get("exit_claim_token")
        if exiting
        else None
    )
    api_key = _api_key_for(user_id)
    if not api_key:
        return _Placement(
            ok=False,
            error="No API key is configured for this user",
            exit_claim_id=exit_claim_id,
        )

    run = store.get_run(run_id)
    mode = str(run.mode) if run else "sandbox"

    action = (
        order_dispatch.exit_action(position) if exiting else ("BUY" if position == "B" else "SELL")
    )
    order = order_dispatch.build_order(
        symbol=leg["symbol"],
        exchange=leg["exchange"],
        action=action,
        quantity=leg.get("quantity") or leg.get("qty"),
        product=strategy_product,
        strategy_name=strategy_name,
        pricetype=order_dispatch.EXIT_PRICETYPE if exiting else strategy_pricetype,
    )
    # Durable intent before the broker is called, exactly as the batch path
    # does. Recording afterwards meant a crash or a database failure between
    # broker acceptance and the insert left a real position that no row
    # described: invisible to the operator, to recovery and to every later
    # exit. The row carries no broker id yet, because there is not one yet.
    row = store.record_order(
        run_id,
        leg["leg_id"],
        kind,
        {
            "symbol": leg["symbol"],
            "exchange": leg["exchange"],
            "action": action,
            "qty": leg.get("quantity") or leg.get("qty"),
            "product": order.get("product"),
            "pricetype": order.get("pricetype", "MARKET"),
            "status": "pending",
            "position_ref": leg.get("position_ref"),
        },
    )
    if row is None and not exiting:
        # An entry that cannot be recorded is one that cannot be managed, so it
        # is not placed. Exits take the opposite decision below, deliberately.
        store.record_event(
            strategy_id,
            user_id,
            "leg_entry_rejected",
            f"Signal entry for leg {leg['leg_id']} not placed: its order row could not be written",
            run_id=run_id,
            leg_id=leg["leg_id"],
            severity="critical",
        )
        return _Placement(ok=False, error="Could not record the order before placing it")

    # The id, not the instance: dispatch runs arbitrary code in between, and
    # the sandbox publishes its fill from inside the call.
    row_id = row.id if row is not None else None
    if not exiting and row_id is not None:
        installed = state.add_leg(
            run_id,
            leg,
            entry_claim.get("claim_token") if entry_claim else None,
            entry_claim.get("expected_position_ref") if entry_claim else None,
            row_id,
        )
        if installed is None:
            store.update_order(
                row_id,
                status="rejected",
                reject_reason="Signal entry claim changed before dispatch",
            )
            return _Placement(
                ok=False,
                error="The position changed before its entry could be placed",
            )
    if exiting and exit_owner == "live" and row_id is not None:
        if not state.bind_live_exit(
            run_id,
            leg["leg_id"],
            leg.get("exit_claim_token"),
            row_id,
            leg.get("position_ref"),
        ):
            store.update_order(
                row_id,
                status="rejected",
                reject_reason="Live position exit claim changed before dispatch",
            )
            return _Placement(
                ok=False,
                error="The live position changed before its exit could be placed",
                exit_claim_id=leg.get("exit_claim_token"),
            )
        exit_claim_id = row_id
    if exiting and exit_owner == "superseded" and row_id is not None:
        if not state.bind_superseded_exit(run_id, leg["leg_id"], leg.get("claim_token"), row_id):
            store.update_order(
                row_id,
                status="rejected",
                reject_reason="Outgoing position exit claim changed before dispatch",
            )
            return _Placement(
                ok=False,
                error="The outgoing position changed before its exit could be placed",
                exit_claim_id=leg.get("claim_token"),
            )
        exit_claim_id = row_id
    if row is None:
        # An exit that cannot be recorded is placed anyway. Refusing would
        # leave the position open with a database outage between it and every
        # attempt to close it; getting flat wins, and the audit row is lost.
        store.record_event(
            strategy_id,
            user_id,
            "leg_exit_placed",
            (
                f"Signal exit for leg {leg['leg_id']} is being placed without an order row: "
                "it could not be written"
            ),
            run_id=run_id,
            leg_id=leg["leg_id"],
            severity="critical",
        )

    result = order_dispatch.dispatch_order(mode=mode, api_key=api_key, order=order)

    if row_id is not None:
        from services.strategy_module.engine import _record_acknowledgement

        _record_acknowledgement(row_id, result, strategy_id, user_id, run_id, leg["leg_id"])

    reconcile_rejected_entry_stop = False
    if not exiting and entry_claim is not None:
        state.finish_signal_entry(
            run_id,
            leg["leg_id"],
            leg["position_ref"],
            entry_claim["claim_token"],
            result.ok,
        )
        reconcile_rejected_entry_stop = not result.ok

    store.record_event(
        strategy_id,
        user_id,
        "leg_exit_placed" if exiting else "leg_entry_placed",
        f"Signal {action} {leg.get('quantity') or leg.get('qty')} {leg['symbol']}"
        + ("" if result.ok else f" rejected: {result.error}"),
        run_id=run_id,
        leg_id=leg["leg_id"],
        severity="info" if result.ok else "warn",
    )

    if row_id is not None and result.ok:
        # After the leg bookkeeping and accepted-placement audit above, never
        # before either. Synchronous replay may finish a pending stop and emit
        # run_stopped, so the placement that made it flat must already exist.
        from services.strategy_module.engine import _replay_order_update

        _replay_order_update(result.broker_order_id)

    if reconcile_rejected_entry_stop:
        # A stop can become durable while dispatch is in flight. Once a
        # zero-fill refusal has released the entry claim, reconcile outside
        # the state lock so a now-flat pending stop can atomically finish.
        from services.strategy_module import engine

        engine.reconcile_pending_stop(run_id)

    return _Placement(ok=result.ok, error=result.error, exit_claim_id=exit_claim_id)
