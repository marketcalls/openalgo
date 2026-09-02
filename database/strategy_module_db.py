# database/strategy_module_db.py
"""
Persistence for the /strategy module: multi-leg options strategies with
end-to-end risk management.

Six tables, all ``sm_`` prefixed. The prefix is not decoration: this codebase
already carries five unrelated things called "strategy" (the Strategy Builder's
``strategy_portfolio``, ``strategy_book``, ``strategy_order_tags``,
``strategy_pending_fills``, and the Python strategy host), and the retired
legacy module owned the unprefixed ``strategies`` table. Namespacing here is
what keeps a future reader from wiring the wrong one.

- ``sm_strategy``            config: legs, risk parameters, scheduler, webhook token hash
- ``sm_strategy_run``        one activation, start to stop; a strategy has many
- ``sm_strategy_order``      every order the engine places, audit grade
- ``sm_strategy_checkpoint`` periodic runtime snapshot, for crash recovery
- ``sm_webhook_event``       every inbound webhook, accepted or rejected
- ``sm_strategy_event``      risk-event audit trail (SL hit, lock profit, ...)

Timestamps are stored naive UTC and rendered IST at the API boundary. SQLite
does not preserve a timezone on a DateTime column whatever you pass it, so
storing aware datetimes would silently hand back naive ones on the next read
and make every comparison a coin flip. One convention, applied at both edges,
is the only version of this that stays true.

Money is ``Numeric(18, 2)``, matching database/sandbox_db.py's DECIMAL columns.
Read helpers convert to float at the boundary so Decimal never reaches jsonify.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from cachetools import TTLCache
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    exists,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

# Canonical engine factory enforces the project-wide pooling policy
# (SQLite -> NullPool with check_same_thread=False) for FD hygiene.
engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Webhook dispatch happens on an unauthenticated public path and is looked up
# by token hash on every request, so it is cached the way flow_db caches its
# own webhook lookups. Bounded and short-lived: a rotated or deleted token must
# stop working quickly, and the cache is invalidated explicitly on both.
_webhook_token_cache: TTLCache = TTLCache(maxsize=2000, ttl=300)

# What each strategy has banked this session, read on every tick by the daily
# loss limit. Bounded by strategy count rather than by tick rate, and
# invalidated whenever a run's realized figure changes, so the TTL only covers
# a path that forgot to invalidate.
_session_pnl_cache: TTLCache = TTLCache(maxsize=512, ttl=60)


def _forget_session_pnl(strategy_id: int | None) -> None:
    """Drop the cached session total for one strategy, or all of them."""
    for key in [k for k in list(_session_pnl_cache) if strategy_id is None or k[0] == strategy_id]:
        _session_pnl_cache.pop(key, None)


# Webhook token prefix, so a leaked string is recognisable in a log or a paste.
WEBHOOK_TOKEN_PREFIX = "oaws_"


# ---------------------------------------------------------------------------
# Enumerated values
#
# Kept as plain tuples rather than SQL CHECK constraints. SQLite cannot alter a
# CHECK constraint in place, so a constraint here would make every future value
# a table rebuild (see CLAUDE.md on migrations). Validation lives at the API
# boundary instead, where it can return a useful error.
# ---------------------------------------------------------------------------

STRATEGY_KINDS = ("batch", "signal")
DIRECTIONS = ("both", "long_only", "short_only")
STRATEGY_TYPES = ("intraday", "positional")
RUN_MODES = ("live", "sandbox")
STRATEGY_STATUSES = ("stopped", "running", "paused", "errored")
TRIGGER_SOURCES = ("manual", "webhook", "scheduler")

STOP_REASONS = (
    "manual",
    "scheduler",
    "overall_sl",
    "overall_target",
    "lock_profit",
    "eod",
    "expiry",
    "daily_loss_limit",
    "tick_stale",
    "recovery_failed",
    "error",
)

ORDER_KINDS = (
    "entry",
    "exit_sl",
    "exit_target",
    "exit_trail",
    "exit_overall_sl",
    "exit_overall_target",
    "exit_lock_profit",
    "exit_eod",
    "exit_expiry",
    "exit_daily_loss_limit",
    "exit_close_all",
    "exit_leg_manual",
    "exit_recovery",
    # Signal mode: an exit driven by a long_exit / short_exit alert rather than
    # by a rule. Its own kind, so the audit trail can tell an operator-driven
    # exit from a rule-driven one from a signal-driven one.
    "exit_signal",
)

ORDER_STATUSES = ("pending", "open", "complete", "cancelled", "rejected")

_TERMINAL_ORDER_STATUSES = frozenset({"complete", "cancelled", "rejected"})


@dataclass(frozen=True, slots=True)
class OrderFactFold:
    """The durable result of folding one cumulative broker order frame."""

    order_id: int
    previous_status: str
    status: str
    previous_filled_qty: int
    cumulative_filled_qty: int
    fill_delta: int
    previous_average_fill_price: float | None
    average_fill_price: float | None
    changed: bool

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_ORDER_STATUSES

    @property
    def was_terminal(self) -> bool:
        return self.previous_status in _TERMINAL_ORDER_STATUSES


EVENT_SEVERITIES = ("info", "warn", "critical")

EVENT_KINDS = (
    # Lifecycle
    "strategy_created",
    "strategy_updated",
    "webhook_token_rotated",
    "live_enabled",
    "live_disabled",
    "webhook_locked",
    "webhook_unlocked",
    "run_started",
    "run_paused",
    "run_resumed",
    "run_stop_requested",
    "run_stopped",
    "run_stop_failed",
    "flip_outgoing_exit_rejected",
    "close_all_manual",
    # Entry and exit
    "leg_entry_placed",
    "leg_entry_filled",
    "leg_entry_rejected",
    "leg_exit_placed",
    "leg_exit_filled",
    "leg_exit_rejected",
    "leg_close_manual",
    "leg_expiry_fallback",
    "order_ack_unrecorded",
    # Per-leg risk
    "leg_sl_hit",
    "leg_target_hit",
    "leg_trail_armed",
    "leg_trail_advanced",
    # Strategy risk
    "overall_sl_hit",
    "overall_target_hit",
    "lock_profit_armed",
    "lock_profit_floor_advanced",
    "lock_profit_triggered",
    "trail_to_entry_activated",
    "eod_squareoff",
    "expiry_squareoff",
    # Tick source
    "tick_source_switched_to_polling",
    "tick_source_switched_to_ws",
    "tick_source_stale",
    # Operational
    "recovery_succeeded",
    "recovery_failed",
)

WEBHOOK_RESULTS = (
    "ok",
    "rejected_token",
    "rejected_ip",
    "rate_limited",
    "rejected_dedupe",
    "rejected_cooling_off",
    "rejected_invalid_action",
    "rejected_live_disabled",
    "rejected_locked",
    "rejected_payload",
    "rejected_engine_error",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SmStrategy(Base):
    """Strategy configuration. One row per saved strategy.

    ``legs`` is JSON rather than a child table on purpose. A leg is only ever
    read as part of its whole strategy, never queried across strategies, and
    the wizard's shape is still moving; a child table would buy nothing and
    cost a migration every time the UI gains a field. Validation happens at the
    API boundary.
    """

    __tablename__ = "sm_strategy"

    id = Column(Integer, primary_key=True)
    # The session username, matching database/watchlist_db.py and
    # database/scalping_db.py. OpenAlgo is single user per deployment, so this
    # keeps the schema honest rather than isolating tenants.
    user_id = Column(String(80), nullable=False, index=True)

    name = Column(String(200), nullable=False)

    # 'batch'  = multi-leg spread entered and exited as a unit (start/stop).
    # 'signal' = per-leg signals (long_entry/long_exit/short_entry/short_exit).
    strategy_kind = Column(String(20), nullable=False, default="batch")
    # Signal-mode direction filter. Ignored for batch strategies.
    direction = Column(String(20), nullable=False, default="both")

    universe_tab = Column(String(30), nullable=False)
    underlying = Column(String(50), nullable=False)
    underlying_exchange = Column(String(20), nullable=False)

    strategy_type = Column(String(20), nullable=False, default="intraday")
    entry_time = Column(Time, nullable=True)
    exit_time = Column(Time, nullable=True)

    product = Column(String(10), nullable=False, default="NRML")
    pricetype = Column(String(10), nullable=False, default="MARKET")

    legs = Column(JSON, nullable=False, default=list)

    overall_sl_mtm = Column(Numeric(18, 2), nullable=True)
    overall_target_mtm = Column(Numeric(18, 2), nullable=True)
    lock_profit = Column(JSON, nullable=True)
    trail_sl_to_entry = Column(Boolean, nullable=False, default=False)

    scheduler = Column(JSON, nullable=True)

    # Live trading is opt-in per strategy. A strategy is born sandbox-only so
    # that a misconfigured webhook discovered after the fact cannot have been
    # placing real orders.
    live_enabled = Column(Boolean, nullable=False, default=False)

    # SHA-256 hex of the URL-embedded webhook token. Plaintext is shown once on
    # create and on rotate, and is never stored. Unique-indexed so dispatch is
    # a single indexed lookup rather than a scan.
    webhook_token_hash = Column(String(64), nullable=False, unique=True, index=True)
    webhook_ip_allowlist = Column(JSON, nullable=True)
    # Kill switch. While set, the webhook refuses every inbound signal for this
    # strategy and audits it as 'rejected_locked'.
    webhook_locked = Column(Boolean, nullable=False, default=False)

    daily_loss_limit_inr = Column(Numeric(18, 2), nullable=True)

    status = Column(String(20), nullable=False, default="stopped", index=True)

    # Deliberately a plain Integer, not a ForeignKey. sm_strategy and
    # sm_strategy_run reference each other, and SQLite cannot ALTER TABLE to
    # add a constraint after the fact, so the circular FK that Postgres builds
    # with use_alter has no equivalent here. The application maintains it.
    current_run_id = Column(Integer, nullable=True)

    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_sm_strategy_user_name"),
        Index("ix_sm_strategy_user_status", "user_id", "status"),
    )


class SmStrategyRun(Base):
    """One activation of a strategy, from start to stop."""

    __tablename__ = "sm_strategy_run"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(
        Integer,
        ForeignKey("sm_strategy.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode = Column(String(10), nullable=False)
    broker = Column(String(50), nullable=False, default="")

    started_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    stopped_at = Column(DateTime, nullable=True)
    stop_reason = Column(String(30), nullable=True)
    stop_requested_at = Column(DateTime, nullable=True)
    stop_requested_reason = Column(String(30), nullable=True)

    # Final realized P&L, written on stop. While the run is live the authority
    # is in-process state plus the checkpoint rows, not this column.
    pnl_realized = Column(Numeric(18, 2), nullable=False, default=0)
    pnl_peak = Column(Numeric(18, 2), nullable=False, default=0)
    pnl_trough = Column(Numeric(18, 2), nullable=False, default=0)

    trigger_source = Column(String(20), nullable=False, default="manual")
    # Plain Integer for the same circular-reference reason as current_run_id.
    webhook_event_id = Column(Integer, nullable=True)

    # Expiries are resolved once at run start and held for the run, so a
    # positional strategy does not silently roll to a new contract mid-run.
    resolved_expiries = Column(JSON, nullable=True)

    __table_args__ = (Index("ix_sm_run_strategy_started", "strategy_id", "started_at"),)


class SmStrategyOrder(Base):
    """Every order the engine places. Append-only apart from fill updates."""

    __tablename__ = "sm_strategy_order"

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("sm_strategy_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leg_id = Column(Integer, nullable=False)
    kind = Column(String(30), nullable=False)
    # A leg can represent an outgoing and replacement position during a signal
    # flip. This durable reference lets fills settle the position they belong to.
    position_ref = Column(String(32), nullable=True)

    # Broker reference. Live runs carry the broker's own id; sandbox runs carry
    # the sandbox engine's, which is date-prefixed and numeric rather than
    # prefixed with a word. Both are opaque here.
    broker_order_id = Column(String(100), nullable=True, index=True)
    symbol = Column(String(100), nullable=False)
    exchange = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)
    qty = Column(Integer, nullable=False)
    # What was actually sent, which is not always what the strategy carries:
    # build_order translates the product to the venue, so a CNC strategy with
    # an option leg sends NRML for that leg. Without this column nothing
    # records which, and an order cannot be reconciled against the broker's.
    product = Column(String(10), nullable=True)
    pricetype = Column(String(10), nullable=False, default="MARKET")
    price = Column(Numeric(18, 4), nullable=False, default=0)
    trigger_price = Column(Numeric(18, 4), nullable=False, default=0)

    status = Column(String(20), nullable=False, default="pending")
    placed_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    filled_at = Column(DateTime, nullable=True)
    avg_fill_price = Column(Numeric(18, 4), nullable=True)
    filled_qty = Column(Integer, nullable=True)
    reject_reason = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_sm_order_run_placed", "run_id", "placed_at"),
        Index("ix_sm_order_run_leg_position", "run_id", "leg_id", "position_ref"),
    )


class SmStrategyCheckpoint(Base):
    """Periodic snapshot of runtime state, so a crash loses seconds not a run."""

    __tablename__ = "sm_strategy_checkpoint"

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("sm_strategy_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    pnl_realized = Column(Numeric(18, 2), nullable=False, default=0)
    pnl_unrealized = Column(Numeric(18, 2), nullable=False, default=0)
    pnl_total = Column(Numeric(18, 2), nullable=False, default=0)
    pnl_peak = Column(Numeric(18, 2), nullable=False, default=0)
    pnl_trough = Column(Numeric(18, 2), nullable=False, default=0)

    lock_floor = Column(Numeric(18, 2), nullable=True)
    trail_to_entry_active = Column(Boolean, nullable=False, default=False)

    leg_state = Column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_sm_checkpoint_run_ts", "run_id", "ts"),)


class SmWebhookEvent(Base):
    """Audit row for every inbound webhook, accepted or rejected.

    ``strategy_id`` is nullable because a request carrying an unknown token
    cannot be resolved to a strategy. The token plaintext is never written to
    ``payload``; it lives in the URL and is stripped before the row is saved.
    """

    __tablename__ = "sm_webhook_event"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(
        Integer,
        ForeignKey("sm_strategy.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action = Column(String(20), nullable=True)
    mode = Column(String(10), nullable=True)
    payload = Column(JSON, nullable=True)

    # String, not INET: SQLite has no inet type, and this holds IPv6 too.
    ip = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    received_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    result = Column(String(50), nullable=False)
    error = Column(Text, nullable=True)

    __table_args__ = (Index("ix_sm_webhook_strategy_received", "strategy_id", "received_at"),)


class SmStrategyEvent(Base):
    """Risk-event audit trail. Every engine state change lands here.

    ``run_id`` is nullable so config-layer events (created, updated, token
    rotated) can share the table with runtime risk events rather than needing
    a second one.
    """

    __tablename__ = "sm_strategy_event"

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("sm_strategy_run.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    strategy_id = Column(
        Integer,
        ForeignKey("sm_strategy.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String(80), nullable=False, index=True)

    ts = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    kind = Column(String(40), nullable=False)
    severity = Column(String(10), nullable=False, default="info")
    leg_id = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    payload = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_sm_event_strategy_ts", "strategy_id", "ts"),
        Index("ix_sm_event_run_ts", "run_id", "ts"),
    )


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create the strategy-module tables if they do not exist."""
    logger.info("Initializing Strategy Module DB")
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Naive UTC, matching how every timestamp column in this module is stored."""
    return datetime.now(UTC).replace(tzinfo=None)


def generate_webhook_token() -> str:
    """A fresh URL-embedded webhook token.

    32 bytes of entropy behind a recognisable prefix. The token identifies the
    strategy on its own, so it is a credential and is only ever shown once.
    """
    return f"{WEBHOOK_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_webhook_token(token: str) -> str:
    """SHA-256 hex of a webhook token.

    SHA-256 rather than a slow KDF on purpose. The input is 256 bits of
    machine-generated entropy, so there is no dictionary to defend against, and
    an unsalted deterministic digest is what allows the O(1) indexed lookup
    that dispatch depends on. A slow salted hash would force a table scan.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _num(value: Any) -> float | None:
    """Decimal or None to float or None, so jsonify never meets a Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _iso(value: datetime | None) -> str | None:
    """A stored naive-UTC timestamp as an explicit UTC ISO string.

    The API layer converts to IST for display. Emitting the offset here means a
    consumer never has to guess what the bare string meant.
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat()


def strategy_to_dict(row: SmStrategy, *, include_legs: bool = True) -> dict:
    """A strategy row as plain JSON-safe data.

    Never includes the webhook token: only its hash is stored, and the
    plaintext is unrecoverable by design.
    """
    data = {
        "id": row.id,
        "name": row.name,
        "strategy_kind": row.strategy_kind,
        "direction": row.direction,
        "universe_tab": row.universe_tab,
        "underlying": row.underlying,
        "underlying_exchange": row.underlying_exchange,
        "strategy_type": row.strategy_type,
        "entry_time": row.entry_time.strftime("%H:%M") if row.entry_time else None,
        "exit_time": row.exit_time.strftime("%H:%M") if row.exit_time else None,
        "product": row.product,
        "pricetype": row.pricetype,
        "overall_sl_mtm": _num(row.overall_sl_mtm),
        "overall_target_mtm": _num(row.overall_target_mtm),
        "lock_profit": row.lock_profit,
        "trail_sl_to_entry": bool(row.trail_sl_to_entry),
        "scheduler": row.scheduler,
        "live_enabled": bool(row.live_enabled),
        "webhook_locked": bool(row.webhook_locked),
        "webhook_ip_allowlist": row.webhook_ip_allowlist,
        "daily_loss_limit_inr": _num(row.daily_loss_limit_inr),
        "status": row.status,
        "current_run_id": row.current_run_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    if include_legs:
        data["legs"] = row.legs or []
    return data


def run_to_dict(row: SmStrategyRun) -> dict:
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "mode": row.mode,
        "broker": row.broker,
        "started_at": _iso(row.started_at),
        "stopped_at": _iso(row.stopped_at),
        "stop_reason": row.stop_reason,
        "stop_requested_at": _iso(row.stop_requested_at),
        "stop_requested_reason": row.stop_requested_reason,
        "pnl_realized": _num(row.pnl_realized),
        "pnl_peak": _num(row.pnl_peak),
        "pnl_trough": _num(row.pnl_trough),
        "trigger_source": row.trigger_source,
        "webhook_event_id": row.webhook_event_id,
        "resolved_expiries": row.resolved_expiries,
    }


def order_to_dict(row: SmStrategyOrder) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "leg_id": row.leg_id,
        "kind": row.kind,
        "position_ref": row.position_ref,
        "broker_order_id": row.broker_order_id,
        "symbol": row.symbol,
        "exchange": row.exchange,
        "action": row.action,
        "qty": row.qty,
        "product": row.product,
        "pricetype": row.pricetype,
        "price": _num(row.price),
        "trigger_price": _num(row.trigger_price),
        "status": row.status,
        "placed_at": _iso(row.placed_at),
        "filled_at": _iso(row.filled_at),
        "avg_fill_price": _num(row.avg_fill_price),
        "filled_qty": row.filled_qty,
        "reject_reason": row.reject_reason,
    }


def event_to_dict(row: SmStrategyEvent) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "strategy_id": row.strategy_id,
        "ts": _iso(row.ts),
        "kind": row.kind,
        "severity": row.severity,
        "leg_id": row.leg_id,
        "message": row.message,
        "payload": row.payload,
    }


def webhook_event_to_dict(row: SmWebhookEvent) -> dict:
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "action": row.action,
        "mode": row.mode,
        "payload": row.payload,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "received_at": _iso(row.received_at),
        "result": row.result,
        "error": row.error,
    }


def checkpoint_to_dict(row: SmStrategyCheckpoint) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "ts": _iso(row.ts),
        "pnl_realized": _num(row.pnl_realized),
        "pnl_unrealized": _num(row.pnl_unrealized),
        "pnl_total": _num(row.pnl_total),
        "pnl_peak": _num(row.pnl_peak),
        "pnl_trough": _num(row.pnl_trough),
        "lock_floor": _num(row.lock_floor),
        "trail_to_entry_active": bool(row.trail_to_entry_active),
        "leg_state": row.leg_state or {},
    }


# ---------------------------------------------------------------------------
# Strategy CRUD
# ---------------------------------------------------------------------------


def create_strategy(user_id: str, config: dict) -> tuple[dict | None, str | None]:
    """Create a strategy and issue its webhook token.

    Returns ``(payload, error)``. The payload carries ``webhook_token`` exactly
    once: it is stored only as a hash, so this response is the single
    opportunity the user has to copy it.
    """
    try:
        existing = (
            db_session.query(SmStrategy).filter_by(user_id=user_id, name=config["name"]).first()
        )
        if existing:
            return None, f"A strategy named '{config['name']}' already exists"

        token = generate_webhook_token()
        row = SmStrategy(
            user_id=user_id,
            name=config["name"],
            strategy_kind=config.get("strategy_kind", "batch"),
            direction=config.get("direction", "both"),
            universe_tab=config.get("universe_tab", "weekly_monthly"),
            underlying=config["underlying"],
            underlying_exchange=config["underlying_exchange"],
            strategy_type=config.get("strategy_type", "intraday"),
            entry_time=config.get("entry_time"),
            exit_time=config.get("exit_time"),
            product=config.get("product", "NRML"),
            pricetype=config.get("pricetype", "MARKET"),
            legs=config.get("legs", []),
            overall_sl_mtm=config.get("overall_sl_mtm"),
            overall_target_mtm=config.get("overall_target_mtm"),
            lock_profit=config.get("lock_profit"),
            trail_sl_to_entry=bool(config.get("trail_sl_to_entry", False)),
            scheduler=config.get("scheduler"),
            daily_loss_limit_inr=config.get("daily_loss_limit_inr"),
            webhook_ip_allowlist=config.get("webhook_ip_allowlist"),
            webhook_token_hash=hash_webhook_token(token),
        )
        db_session.add(row)
        db_session.commit()

        payload = strategy_to_dict(row)
        payload["webhook_token"] = token
        return payload, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not create strategy for %s", user_id)
        return None, "Could not create the strategy"


def list_strategies(user_id: str, status: str | None = None, q: str | None = None) -> list[dict]:
    """Every strategy for a user, newest first, with its last finalised run.

    A checkpoint is an in-flight measurement and can precede a filled exit.
    The list needs the durable run value for a stopped strategy, so join its
    most recently finalised run here rather than making the browser guess from
    the final checkpoint of every row.
    """
    try:
        latest_finalized_run_id = (
            db_session.query(SmStrategyRun.id)
            .filter(
                SmStrategyRun.strategy_id == SmStrategy.id,
                SmStrategyRun.stopped_at.is_not(None),
            )
            .order_by(SmStrategyRun.stopped_at.desc(), SmStrategyRun.id.desc())
            .limit(1)
            .correlate(SmStrategy)
            .scalar_subquery()
        )
        query = (
            db_session.query(SmStrategy, SmStrategyRun)
            .outerjoin(SmStrategyRun, SmStrategyRun.id == latest_finalized_run_id)
            .filter(SmStrategy.user_id == user_id)
        )
        if status:
            query = query.filter(SmStrategy.status == status)
        if q:
            query = query.filter(SmStrategy.name.ilike(f"%{q}%"))
        rows = query.order_by(SmStrategy.created_at.desc()).all()
        listed = []
        for strategy, last_run in rows:
            data = strategy_to_dict(strategy, include_legs=False)
            data["last_finalized_run"] = (
                None
                if last_run is None
                else {
                    "id": last_run.id,
                    "pnl_realized": _num(last_run.pnl_realized),
                    "stopped_at": _iso(last_run.stopped_at),
                }
            )
            listed.append(data)
        return listed
    except Exception:
        logger.exception("Could not list strategies for %s", user_id)
        return []


def get_strategy(strategy_id: int, user_id: str) -> SmStrategy | None:
    """One strategy, scoped to its owner.

    The ``user_id`` filter is in the signature rather than left to callers so
    that no call site can forget it.
    """
    try:
        return db_session.query(SmStrategy).filter_by(id=strategy_id, user_id=user_id).first()
    except Exception:
        logger.exception("Could not read strategy %s", strategy_id)
        return None


def get_strategy_unscoped(strategy_id: int) -> SmStrategy | None:
    """One strategy without an owner filter.

    Every other read here takes a user_id so no call site can forget it. This
    one exists for the engine, which reaches a strategy through a run it is
    already executing rather than through a request: there is no user in scope
    to filter by, and the run row is the authority on which strategy it belongs
    to. Do not use it to serve a request.
    """
    try:
        return db_session.query(SmStrategy).filter_by(id=strategy_id).first()
    except Exception:
        logger.exception("Could not read strategy %s", strategy_id)
        return None


# Fields a PATCH is allowed to touch. An allowlist, not a denylist: it is the
# only thing standing between a mass-assignment and a caller setting
# webhook_token_hash, user_id or current_run_id directly.
#
# strategy_kind is deliberately absent. The two kinds do not share a leg shape:
# a batch leg carries a segment, a position and a lot count resolved from the
# strategy's underlying, while a signal leg names its own instrument, side and
# absolute quantity. Flipping the kind leaves every stored leg describing the
# other kind's contract, and the legs are an opaque JSON column, so nothing
# downstream notices until a run tries to resolve them. The wizard already
# refuses to send it; this is the half that a caller cannot route around.
UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "direction",
        "universe_tab",
        "underlying",
        "underlying_exchange",
        "strategy_type",
        "entry_time",
        "exit_time",
        "product",
        "pricetype",
        "legs",
        "overall_sl_mtm",
        "overall_target_mtm",
        "lock_profit",
        "trail_sl_to_entry",
        "scheduler",
        "daily_loss_limit_inr",
        "webhook_ip_allowlist",
    }
)


def update_strategy(
    strategy_id: int, user_id: str, changes: dict
) -> tuple[dict | None, str | None]:
    """Update a stopped strategy. Refuses while it is running."""
    try:
        row = get_strategy(strategy_id, user_id)
        if not row:
            return None, "Strategy not found"
        if row.status == "running":
            return None, "Stop the strategy before editing it"

        # Said rather than silently dropped. strategy_kind is outside
        # UPDATABLE_FIELDS, so a caller asking to change it would otherwise get
        # a 200 and a strategy that did not change, which reads as success.
        requested_kind = changes.get("strategy_kind")
        if requested_kind is not None and requested_kind != row.strategy_kind:
            return None, (
                "A strategy cannot change between batch and signal. The two kinds do not "
                "share a leg shape, so every leg would describe the wrong kind of contract. "
                "Create a new strategy instead."
            )

        for field, value in changes.items():
            if field in UPDATABLE_FIELDS:
                setattr(row, field, value)

        db_session.commit()
        return strategy_to_dict(row), None
    except Exception:
        db_session.rollback()
        logger.exception("Could not update strategy %s", strategy_id)
        return None, "Could not update the strategy"


def delete_strategy(strategy_id: int, user_id: str) -> tuple[bool, str | None]:
    """Delete a stopped strategy and every row that belongs to it.

    The children are removed explicitly rather than left to the ``ondelete``
    clauses on the foreign keys. Those clauses are declarative only here:
    SQLite enforces a foreign key only when ``PRAGMA foreign_keys=ON`` is set
    per connection, and this project never sets it (see
    ``database/engine_factory.py`` and ``upgrade/_pragmas.py``, which set
    journal mode, synchronous and busy_timeout and nothing else). Relying on
    the cascade would leave a deleted strategy's runs, orders, checkpoints,
    events and webhook audit behind forever, unreachable through any query the
    module offers and growing without bound in a process that never restarts.

    Webhook events go too, rather than having ``strategy_id`` set to NULL. The
    only reader is ``list_webhook_events(strategy_id)``, so a NULLed row is
    invisible to every surface the product has: it would be growth, not an
    audit trail.
    """
    try:
        row = get_strategy(strategy_id, user_id)
        if not row:
            return False, "Strategy not found"
        if row.status == "running":
            return False, "Stop the strategy before deleting it"

        run_ids = [
            r.id
            for r in db_session.query(SmStrategyRun.id).filter_by(strategy_id=strategy_id).all()
        ]
        if run_ids:
            db_session.query(SmStrategyCheckpoint).filter(
                SmStrategyCheckpoint.run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            db_session.query(SmStrategyOrder).filter(SmStrategyOrder.run_id.in_(run_ids)).delete(
                synchronize_session=False
            )

        db_session.query(SmStrategyEvent).filter_by(strategy_id=strategy_id).delete(
            synchronize_session=False
        )
        db_session.query(SmWebhookEvent).filter_by(strategy_id=strategy_id).delete(
            synchronize_session=False
        )
        db_session.query(SmStrategyRun).filter_by(strategy_id=strategy_id).delete(
            synchronize_session=False
        )

        _webhook_token_cache.pop(row.webhook_token_hash, None)
        db_session.delete(row)
        db_session.commit()
        return True, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not delete strategy %s", strategy_id)
        return False, "Could not delete the strategy"


def set_strategy_status(strategy_id: int, status: str, run_id: int | None = None) -> bool:
    """Move a strategy's status, and point it at its current run.

    Not owner-scoped: the engine and the scheduler both call this and already
    hold a strategy they were handed through an owner-scoped read.
    """
    try:
        row = db_session.query(SmStrategy).filter_by(id=strategy_id).first()
        if not row:
            return False
        row.status = status
        row.current_run_id = run_id
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        logger.exception("Could not set status on strategy %s", strategy_id)
        return False


def claim_strategy_for_run(strategy_id: int) -> bool:
    """Move a strategy from stopped to running, and say whether this call did it.

    This is the idempotency guard for starting a run, and it is a single
    conditional UPDATE rather than a read followed by a write. Three triggers
    can start the same strategy at the same moment - the UI, the scheduler and
    an inbound webhook - and a check-then-set between them would let two of
    them both see "stopped" and both place a full set of entry orders.

    The original guards this with SELECT ... FOR UPDATE, which SQLite parses
    and does not honour, so the guard would be silently absent here. Making the
    UPDATE itself carry the condition puts the check and the write in one
    statement, which SQLite does serialise. The loser sees rowcount 0 and backs
    off.

    Returns True when this call is the one that started it.
    """
    try:
        updated = (
            db_session.query(SmStrategy)
            .filter(SmStrategy.id == strategy_id, SmStrategy.status == "stopped")
            .update({"status": "running"}, synchronize_session=False)
        )
        db_session.commit()
        return bool(updated)
    except Exception:
        db_session.rollback()
        logger.exception("Could not claim strategy %s for a run", strategy_id)
        return False


def release_strategy(strategy_id: int) -> bool:
    """Return a strategy to stopped and clear its current run."""
    try:
        db_session.query(SmStrategy).filter(SmStrategy.id == strategy_id).update(
            {"status": "stopped", "current_run_id": None}, synchronize_session=False
        )
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        logger.exception("Could not release strategy %s", strategy_id)
        return False


def rotate_webhook_token(strategy_id: int, user_id: str) -> tuple[str | None, str | None]:
    """Issue a fresh webhook token, invalidating the old one immediately."""
    try:
        row = get_strategy(strategy_id, user_id)
        if not row:
            return None, "Strategy not found"

        _webhook_token_cache.pop(row.webhook_token_hash, None)
        token = generate_webhook_token()
        row.webhook_token_hash = hash_webhook_token(token)
        db_session.commit()
        return token, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not rotate webhook token on strategy %s", strategy_id)
        return None, "Could not rotate the webhook token"


def set_live_enabled(strategy_id: int, user_id: str, enabled: bool) -> tuple[bool, str | None]:
    """Turn live trading on or off for one strategy."""
    try:
        row = get_strategy(strategy_id, user_id)
        if not row:
            return False, "Strategy not found"
        if row.status == "running":
            return False, "Stop the strategy before changing its mode"
        row.live_enabled = bool(enabled)
        db_session.commit()
        return True, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not set live_enabled on strategy %s", strategy_id)
        return False, "Could not change the live setting"


def set_webhook_locked(strategy_id: int, user_id: str, locked: bool) -> tuple[bool, str | None]:
    """Engage or release the per-strategy webhook kill switch."""
    try:
        row = get_strategy(strategy_id, user_id)
        if not row:
            return False, "Strategy not found"
        row.webhook_locked = bool(locked)
        db_session.commit()
        _webhook_token_cache.pop(row.webhook_token_hash, None)
        return True, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not set webhook_locked on strategy %s", strategy_id)
        return False, "Could not change the webhook lock"


def get_strategy_by_webhook_token(token: str) -> SmStrategy | None:
    """Resolve an inbound webhook token to its strategy.

    Hashes the presented token and looks the digest up on the unique index.
    A miss is cached as well as a hit, so a scanner walking the token space
    cannot turn each guess into a database round trip.
    """
    try:
        digest = hash_webhook_token(token)
        if digest in _webhook_token_cache:
            strategy_id = _webhook_token_cache[digest]
            if strategy_id is None:
                return None
            return db_session.query(SmStrategy).filter_by(id=strategy_id).first()

        row = db_session.query(SmStrategy).filter_by(webhook_token_hash=digest).first()
        _webhook_token_cache[digest] = row.id if row else None
        return row
    except Exception:
        logger.exception("Could not resolve a webhook token")
        return None


def clear_strategy_module_cache() -> None:
    """Drop the webhook lookup cache. Called on logout and session teardown."""
    _webhook_token_cache.clear()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def create_run(
    strategy_id: int,
    mode: str,
    broker: str,
    trigger_source: str = "manual",
    webhook_event_id: int | None = None,
    resolved_expiries: dict | None = None,
) -> SmStrategyRun | None:
    """Open a new run for a strategy."""
    try:
        row = SmStrategyRun(
            strategy_id=strategy_id,
            mode=mode,
            broker=broker or "",
            trigger_source=trigger_source,
            webhook_event_id=webhook_event_id,
            resolved_expiries=resolved_expiries,
        )
        db_session.add(row)
        db_session.commit()
        return row
    except Exception:
        db_session.rollback()
        logger.exception("Could not create a run for strategy %s", strategy_id)
        return None


def finish_run(
    run_id: int,
    stop_reason: str,
    pnl_realized: float = 0.0,
    pnl_peak: float = 0.0,
    pnl_trough: float = 0.0,
) -> bool:
    """Close an active run exactly once and write its final numbers."""
    try:
        strategy_id = (
            db_session.query(SmStrategyRun.strategy_id).filter(SmStrategyRun.id == run_id).scalar()
        )
        if strategy_id is None:
            return False
        updated = (
            db_session.query(SmStrategyRun)
            .filter(
                SmStrategyRun.id == run_id,
                SmStrategyRun.stopped_at.is_(None),
            )
            .update(
                {
                    "stopped_at": utcnow(),
                    "stop_reason": stop_reason,
                    "stop_requested_at": None,
                    "stop_requested_reason": None,
                    "pnl_realized": pnl_realized,
                    "pnl_peak": pnl_peak,
                    "pnl_trough": pnl_trough,
                },
                synchronize_session=False,
            )
        )
        db_session.commit()
        db_session.expire_all()
        if updated == 1:
            _forget_session_pnl(strategy_id)
            return True
        return False
    except Exception:
        db_session.rollback()
        logger.exception("Could not finish run %s", run_id)
        return False


def finish_run_and_release_strategy(
    run_id: int,
    strategy_id: int,
    stop_reason: str,
    pnl_realized: float = 0.0,
    pnl_peak: float = 0.0,
    pnl_trough: float = 0.0,
) -> bool:
    """Atomically finish one active run and release only its current strategy.

    The two conditional updates share one transaction. If the run was already
    finished, or the strategy now points at another run, neither row changes.
    The single True caller owns terminal events and in-process cleanup.
    """
    try:
        finished = (
            db_session.query(SmStrategyRun)
            .filter(
                SmStrategyRun.id == run_id,
                SmStrategyRun.strategy_id == strategy_id,
                SmStrategyRun.stopped_at.is_(None),
            )
            .update(
                {
                    "stopped_at": utcnow(),
                    "stop_reason": stop_reason,
                    "stop_requested_at": None,
                    "stop_requested_reason": None,
                    "pnl_realized": pnl_realized,
                    "pnl_peak": pnl_peak,
                    "pnl_trough": pnl_trough,
                },
                synchronize_session=False,
            )
        )
        if finished != 1:
            db_session.rollback()
            return False

        released = (
            db_session.query(SmStrategy)
            .filter(
                SmStrategy.id == strategy_id,
                SmStrategy.current_run_id == run_id,
            )
            .update(
                {"status": "stopped", "current_run_id": None},
                synchronize_session=False,
            )
        )
        if released != 1:
            db_session.rollback()
            db_session.expire_all()
            return False

        db_session.commit()
        db_session.expire_all()
        _forget_session_pnl(strategy_id)
        return True
    except Exception:
        db_session.rollback()
        logger.exception(
            "Could not atomically finish run %s and release strategy %s",
            run_id,
            strategy_id,
        )
        return False


def finish_detached_run(
    run_id: int,
    strategy_id: int,
    stop_reason: str,
    pnl_realized: float = 0.0,
    pnl_peak: float = 0.0,
    pnl_trough: float = 0.0,
) -> bool:
    """Finish one residual run only when it is not the strategy's current run.

    A late broker correction can reopen an older run while a newer run owns
    the strategy pointer. That residual still needs an exact terminal CAS, but
    must never release or relabel the newer run. The ``NOT EXISTS`` guard is
    part of the same UPDATE as ``stopped_at IS NULL`` so there is no read/write
    gap in which current-run ownership can be confused.
    """
    try:
        current_owner = exists().where(
            SmStrategy.id == strategy_id,
            SmStrategy.current_run_id == run_id,
        )
        finished = (
            db_session.query(SmStrategyRun)
            .filter(
                SmStrategyRun.id == run_id,
                SmStrategyRun.strategy_id == strategy_id,
                SmStrategyRun.stopped_at.is_(None),
                ~current_owner,
            )
            .update(
                {
                    "stopped_at": utcnow(),
                    "stop_reason": stop_reason,
                    "stop_requested_at": None,
                    "stop_requested_reason": None,
                    "pnl_realized": pnl_realized,
                    "pnl_peak": pnl_peak,
                    "pnl_trough": pnl_trough,
                },
                synchronize_session=False,
            )
        )
        if finished != 1:
            db_session.rollback()
            db_session.expire_all()
            return False
        db_session.commit()
        db_session.expire_all()
        _forget_session_pnl(strategy_id)
        return True
    except Exception:
        db_session.rollback()
        logger.exception(
            "Could not atomically finish detached run %s for strategy %s",
            run_id,
            strategy_id,
        )
        return False


def finish_empty_unlinked_run_and_release_claim(
    run_id: int,
    strategy_id: int,
    stop_reason: str,
    pnl_realized: float = 0.0,
    pnl_peak: float = 0.0,
    pnl_trough: float = 0.0,
) -> bool:
    """Atomically finish the exact crash window between run creation and linkage.

    Entry dispatch is sequenced after ``set_strategy_status``. Therefore the
    only safe unlinked recovery shape is an open, zero-order run whose strategy
    still carries the empty ``running/current_run_id=NULL`` claim. Both rows
    are conditional updates in one transaction, so an older detached run or a
    newer owner cannot be closed or released by this cleanup.
    """
    try:
        empty_claim = exists().where(
            SmStrategy.id == strategy_id,
            SmStrategy.status == "running",
            SmStrategy.current_run_id.is_(None),
        )
        no_orders = ~exists().where(SmStrategyOrder.run_id == run_id)
        finished = (
            db_session.query(SmStrategyRun)
            .filter(
                SmStrategyRun.id == run_id,
                SmStrategyRun.strategy_id == strategy_id,
                SmStrategyRun.stopped_at.is_(None),
                empty_claim,
                no_orders,
            )
            .update(
                {
                    "stopped_at": utcnow(),
                    "stop_reason": stop_reason,
                    "stop_requested_at": None,
                    "stop_requested_reason": None,
                    "pnl_realized": pnl_realized,
                    "pnl_peak": pnl_peak,
                    "pnl_trough": pnl_trough,
                },
                synchronize_session=False,
            )
        )
        if finished != 1:
            db_session.rollback()
            return False

        released = (
            db_session.query(SmStrategy)
            .filter(
                SmStrategy.id == strategy_id,
                SmStrategy.status == "running",
                SmStrategy.current_run_id.is_(None),
            )
            .update(
                {"status": "stopped", "current_run_id": None},
                synchronize_session=False,
            )
        )
        if released != 1:
            db_session.rollback()
            db_session.expire_all()
            return False

        db_session.commit()
        db_session.expire_all()
        _forget_session_pnl(strategy_id)
        return True
    except Exception:
        db_session.rollback()
        logger.exception(
            "Could not atomically finish empty unlinked run %s and release strategy %s",
            run_id,
            strategy_id,
        )
        return False


def finish_unlinked_run_and_release_claim(
    run_id: int,
    strategy_id: int,
    stop_reason: str,
) -> bool:
    """Close a never-linked run, then release only its empty strategy claim.

    Run creation and strategy linkage are separate durable writes. If linkage
    fails, no order may be dispatched, but the already-created run still has
    to become terminal. ``finish_detached_run`` refuses to close a run that is
    current, and the second CAS refuses to release a strategy that now points
    at any run. A newer owner therefore survives a delayed cleanup intact.

    The close intentionally commits first. If releasing the empty claim then
    fails, the strategy remains fail-closed as ``running`` with no current run
    rather than leaving an open orphan that recovery could mistake for
    exposure.
    """
    if not finish_detached_run(run_id, strategy_id, stop_reason):
        return False

    try:
        released = (
            db_session.query(SmStrategy)
            .filter(
                SmStrategy.id == strategy_id,
                SmStrategy.status == "running",
                SmStrategy.current_run_id.is_(None),
            )
            .update(
                {"status": "stopped", "current_run_id": None},
                synchronize_session=False,
            )
        )
        db_session.commit()
        db_session.expire_all()
        return released == 1
    except Exception:
        db_session.rollback()
        logger.exception(
            "Could not release the empty run claim for strategy %s after closing run %s",
            strategy_id,
            run_id,
        )
        return False


def request_run_stop(run_id: int, reason: str) -> bool:
    """Persist a stop request while leaving the run active until it is flat."""
    try:
        updated = (
            db_session.query(SmStrategyRun)
            .filter(
                SmStrategyRun.id == run_id,
                SmStrategyRun.stopped_at.is_(None),
                SmStrategyRun.stop_requested_at.is_(None),
                SmStrategyRun.stop_requested_reason.is_(None),
            )
            .update(
                {
                    "stop_requested_at": utcnow(),
                    "stop_requested_reason": reason,
                },
                synchronize_session=False,
            )
        )
        db_session.commit()
        db_session.expire_all()
        if updated == 1:
            return True
        existing = (
            db_session.query(SmStrategyRun.id)
            .filter(
                SmStrategyRun.id == run_id,
                SmStrategyRun.stopped_at.is_(None),
                SmStrategyRun.stop_requested_at.is_not(None),
                SmStrategyRun.stop_requested_reason.is_not(None),
            )
            .first()
        )
        return existing is not None
    except Exception:
        db_session.rollback()
        logger.exception("Could not request stop for run %s", run_id)
        return False


def reopen_run_for_late_entry_fill(run_id: int) -> bool:
    """Reopen a terminal run after stronger durable entry-fill evidence.

    A broker may first report ``cancelled, filled=0`` and later correct that
    terminal fact to ``complete`` with a higher cumulative quantity. The
    original stop was allowed to finish on the zero fact, so this conditional
    repair restores its pending-stop reason. If the strategy is still free it
    also regains ordinary current-run ownership; if a newer run owns it, the
    old run remains an independently managed residual and the shared pending
    stop reconciler still services it.
    """
    try:
        db_session.expire_all()
        run = db_session.query(SmStrategyRun).filter_by(id=run_id).first()
        if run is None:
            return False
        if run.stopped_at is None:
            return run.stop_requested_reason is not None

        stopped_at = run.stopped_at
        strategy_id = run.strategy_id
        reason = run.stop_reason or "manual"
        reopened = (
            db_session.query(SmStrategyRun)
            .filter(
                SmStrategyRun.id == run_id,
                SmStrategyRun.stopped_at == stopped_at,
            )
            .update(
                {
                    "stopped_at": None,
                    "stop_reason": None,
                    "stop_requested_at": utcnow(),
                    "stop_requested_reason": reason,
                },
                synchronize_session=False,
            )
        )
        if reopened != 1:
            db_session.rollback()
            db_session.expire_all()
            current = db_session.query(SmStrategyRun).filter_by(id=run_id).first()
            return bool(
                current is not None
                and current.stopped_at is None
                and current.stop_requested_reason is not None
            )

        # Claim the ordinary UI/current-run pointer only when nobody newer owns
        # it. This conditional update races safely with a fresh start.
        db_session.query(SmStrategy).filter(
            SmStrategy.id == strategy_id,
            SmStrategy.current_run_id.is_(None),
            SmStrategy.status == "stopped",
        ).update(
            {"status": "running", "current_run_id": run_id},
            synchronize_session=False,
        )
        db_session.commit()
        db_session.expire_all()
        _forget_session_pnl(strategy_id)
        return True
    except Exception:
        db_session.rollback()
        logger.exception("Could not reopen run %s after a late entry fill", run_id)
        return False


def get_run(run_id: int) -> SmStrategyRun | None:
    try:
        return db_session.query(SmStrategyRun).filter_by(id=run_id).first()
    except Exception:
        logger.exception("Could not read run %s", run_id)
        return None


def realized_pnl_since(
    strategy_id: int, since: datetime, exclude_run_id: int | None = None
) -> float:
    """What this strategy has already banked this session, as a signed figure.

    Summed over the runs that have finished since the session began, so a
    strategy that starts and stops repeatedly, which is every signal strategy
    and every scheduler-driven one, is judged on the day rather than on
    whichever run happens to be open. A loss is negative.

    ``exclude_run_id`` leaves the live run out, because its own figure is read
    from run state where it is current rather than from the row where it is
    only written at finalisation.
    """
    # started_at is stored as naive UTC, so an aware boundary has to be
    # converted rather than compared: SQLite would otherwise compare the
    # strings and quietly answer with the wrong set of runs.
    if since.tzinfo is not None:
        since = since.astimezone(UTC).replace(tzinfo=None)

    # Cached, because the caller is the per-tick risk evaluation and this
    # figure only changes when a run finishes. Without it a strategy with a
    # daily limit set opened and closed a database connection on every tick of
    # every leg, which under NullPool is a real connection each time, in the
    # one worker that serves everything else too. finish_run and
    # reconcile_run_pnl invalidate it, so the TTL is a safety net rather than
    # the mechanism.
    key = (strategy_id, since, exclude_run_id)
    cached = _session_pnl_cache.get(key)
    if cached is not None:
        return cached

    try:
        query = db_session.query(SmStrategyRun.pnl_realized).filter(
            SmStrategyRun.strategy_id == strategy_id,
            SmStrategyRun.started_at >= since,
        )
        if exclude_run_id is not None:
            query = query.filter(SmStrategyRun.id != exclude_run_id)
        total = float(sum(float(row[0] or 0.0) for row in query.all()))
        _session_pnl_cache[key] = total
        return total
    except Exception:
        logger.exception("Could not total realized P&L for strategy %s", strategy_id)
        # Zero, not a guess. A caller uses this to decide whether a limit has
        # been reached, and inventing a loss would stop a strategy that has
        # not lost anything.
        return 0.0


@dataclass(frozen=True, slots=True)
class _PnlFillFact:
    order_id: int
    placed_at: datetime
    kind: str
    action: str
    quantity: int
    price: float | None


def _pnl_fill_fact(order: SmStrategyOrder) -> _PnlFillFact | None:
    status = (order.status or "").lower()
    terminal_partial = status in {"cancelled", "rejected"}
    if status != "complete" and not terminal_partial:
        return None
    if terminal_partial:
        # A dead remainder does not erase the portion that traded. Zero means
        # nothing traded and must never fall back to the requested quantity.
        quantity = int(order.filled_qty or 0)
    else:
        # Some brokers omit filled_qty after confirming the whole request.
        quantity = int(order.filled_qty or order.qty or 0)
    if quantity <= 0:
        return None
    raw_price = float(order.avg_fill_price) if order.avg_fill_price is not None else 0.0
    return _PnlFillFact(
        order_id=int(order.id),
        placed_at=order.placed_at,
        kind=order.kind,
        action=(order.action or "").upper(),
        quantity=quantity,
        price=raw_price if raw_price > 0 else None,
    )


def _fold_owner_pnl(facts: list[_PnlFillFact], *, referenced: bool) -> tuple[float, int] | None:
    """FIFO one provable owner; ``None`` means its ownership is ambiguous."""
    # A positive but unpriced fact leaves checkpoint/live P&L authoritative for
    # this owner. Do not manufacture a partial owner valuation from later rows.
    if any(fact.price is None for fact in facts):
        return 0.0, 0

    lots: list[dict[str, Any]] = []
    owner_action: str | None = None
    realized = 0.0
    settled = 0
    for fact in sorted(facts, key=lambda item: (item.placed_at, item.order_id)):
        if fact.kind == "entry":
            if fact.action not in {"BUY", "SELL"}:
                return None
            open_actions = {lot["action"] for lot in lots if lot["remaining"] > 0}
            if referenced:
                if owner_action is not None and fact.action != owner_action:
                    return None
                owner_action = fact.action
            elif open_actions and fact.action not in open_actions:
                # NULL references can only be associated safely in chronological
                # FIFO order. Overlapping opposite positions are unknowable.
                return None
            lots.append(
                {
                    "action": fact.action,
                    "price": fact.price,
                    "remaining": fact.quantity,
                }
            )
            continue

        remaining_lots = [lot for lot in lots if lot["remaining"] > 0]
        if not remaining_lots:
            # An exit placed before any attributable entry cannot be paired with
            # an entry that happens to appear later in durable history.
            return None
        expected_exit = "SELL" if remaining_lots[0]["action"] == "BUY" else "BUY"
        if fact.action != expected_exit:
            return None

        quantity_left = fact.quantity
        matched = 0
        for lot in remaining_lots:
            lot_exit = "SELL" if lot["action"] == "BUY" else "BUY"
            if fact.action != lot_exit:
                return None
            applied = min(quantity_left, int(lot["remaining"]))
            sign = 1.0 if lot["action"] == "BUY" else -1.0
            realized += (float(fact.price) - float(lot["price"])) * applied * sign
            lot["remaining"] -= applied
            quantity_left -= applied
            matched += applied
            if quantity_left <= 0:
                break
        # Broker evidence can exceed the locally provable owner quantity. Cap
        # it here; never let it consume another position-reference group.
        if matched:
            settled += 1

    return realized, settled


def reconcile_run_pnl(run_id: int) -> float | None:
    """Recompute provable realized P&L from durable position-owner facts.

    Runs normally remain managed until fill-confirmed flatness. This repair is
    for a late broker correction that arrives after live state was detached (or
    during recovery): referenced owners are reconciled independently, while
    legacy NULL rows use chronological FIFO within their leg. The stored value
    is left untouched if ownership is ambiguous or no priced round trip exists.
    """
    try:
        row = db_session.query(SmStrategyRun).filter_by(id=run_id).first()
        if row is None:
            return None

        owner_facts: dict[tuple[Any, ...], list[_PnlFillFact]] = {}
        for order in db_session.query(SmStrategyOrder).filter_by(run_id=run_id).all():
            fact = _pnl_fill_fact(order)
            if fact is None:
                continue
            if order.position_ref:
                owner_key = ("referenced", order.leg_id, order.position_ref)
            else:
                # Legacy rows are deliberately isolated from every referenced
                # owner, even when their leg IDs are identical.
                owner_key = ("legacy", order.leg_id)
            owner_facts.setdefault(owner_key, []).append(fact)

        realized = 0.0
        settled = 0
        for owner_key, facts in owner_facts.items():
            folded = _fold_owner_pnl(facts, referenced=owner_key[0] == "referenced")
            if folded is None:
                return None
            owner_realized, owner_settled = folded
            realized += owner_realized
            settled += owner_settled

        if not settled:
            # No round trip is recorded on any order row, so this cannot speak
            # to what the run made. Writing the zero it would otherwise compute
            # would overwrite a figure the engine had already got right from
            # live state, which is exactly backwards.
            return None

        row.pnl_realized = realized
        db_session.commit()
        _forget_session_pnl(row.strategy_id)
        return realized
    except Exception:
        db_session.rollback()
        logger.exception("Could not reconcile the P&L of run %s", run_id)
        return None


def list_runs(strategy_id: int, limit: int = 100) -> list[dict]:
    try:
        rows = (
            db_session.query(SmStrategyRun)
            .filter_by(strategy_id=strategy_id)
            .order_by(SmStrategyRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [run_to_dict(r) for r in rows]
    except Exception:
        logger.exception("Could not list runs for strategy %s", strategy_id)
        return []


def list_open_runs() -> list[SmStrategyRun]:
    """Every run with no stopped_at. The starting point for boot recovery."""
    try:
        return db_session.query(SmStrategyRun).filter(SmStrategyRun.stopped_at.is_(None)).all()
    except Exception:
        logger.exception("Could not list open runs")
        return []


def list_open_run_ids_after(after_id: int, limit: int) -> list[int]:
    """A bounded ascending page of open run ids for background safety sweeps."""
    try:
        page_size = max(1, min(int(limit), 100))
        rows = (
            db_session.query(SmStrategyRun.id)
            .filter(
                SmStrategyRun.stopped_at.is_(None),
                SmStrategyRun.id > max(0, int(after_id)),
            )
            .order_by(SmStrategyRun.id.asc())
            .limit(page_size)
            .all()
        )
        return [int(row[0]) for row in rows]
    except Exception:
        logger.exception("Could not page open runs after %s", after_id)
        return []


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def record_order(run_id: int, leg_id: int, kind: str, order: dict) -> SmStrategyOrder | None:
    """Write an order row at placement time, before the broker answers.

    DB-first on purpose: an order that reached the broker but never got written
    here is invisible to recovery, which is the one failure this table exists
    to prevent.
    """
    try:
        row = SmStrategyOrder(
            run_id=run_id,
            leg_id=leg_id,
            kind=kind,
            position_ref=order.get("position_ref"),
            broker_order_id=order.get("broker_order_id"),
            symbol=order["symbol"],
            exchange=order["exchange"],
            action=order["action"],
            qty=order["qty"],
            product=order.get("product"),
            pricetype=order.get("pricetype", "MARKET"),
            price=order.get("price", 0) or 0,
            trigger_price=order.get("trigger_price", 0) or 0,
            status=order.get("status", "pending"),
        )
        db_session.add(row)
        db_session.commit()
        return row
    except Exception:
        db_session.rollback()
        logger.exception("Could not record an order for run %s leg %s", run_id, leg_id)
        return None


def fold_order_broker_frame(
    order_id: int,
    *,
    status: str,
    avg_fill_price: float | None,
    filled_qty: int | None,
    reject_reason: str | None = None,
) -> OrderFactFold | None:
    """Atomically fold one cumulative broker frame into an order row.

    Broker updates can arrive concurrently and out of order. Quantity evidence
    is cumulative, so only a positive increase produces a state-layer delta.
    A working frame may add later fill evidence but can never reopen a terminal
    row. A later ``complete`` frame upgrades a dead row only when it brings a
    strictly higher cumulative quantity.

    The conditional update includes the status and quantity observed by this
    transaction. A losing worker retries from the winner's facts instead of
    overwriting them with its stale snapshot.
    """
    incoming_status = str(status or "").strip().lower()
    if incoming_status not in {"open", "complete", "cancelled", "rejected"}:
        incoming_status = "open"

    try:
        incoming_qty = max(0, int(filled_qty or 0))
    except (TypeError, ValueError):
        incoming_qty = 0

    for _attempt in range(8):
        try:
            db_session.expire_all()
            row = db_session.query(SmStrategyOrder).filter_by(id=order_id).first()
            if row is None:
                return None

            raw_previous_status = row.status
            previous_status = str(raw_previous_status or "pending").strip().lower()
            raw_previous_qty = row.filled_qty
            try:
                previous_qty = max(0, int(raw_previous_qty or 0))
            except (TypeError, ValueError):
                previous_qty = 0
            previous_price = _num(row.avg_fill_price)

            evidence_qty = incoming_qty
            if incoming_status == "complete" and evidence_qty <= 0:
                # A complete order with an omitted/zero broker quantity means
                # the whole requested amount traded. Dead/working zeroes do
                # not carry that implication.
                evidence_qty = max(0, int(row.qty or 0))
            cumulative_qty = max(previous_qty, evidence_qty)
            fill_delta = cumulative_qty - previous_qty

            if previous_status == "complete":
                next_status = "complete"
            elif previous_status in {"cancelled", "rejected"}:
                if incoming_status == "complete" and fill_delta > 0:
                    next_status = "complete"
                else:
                    next_status = previous_status
            elif incoming_status in _TERMINAL_ORDER_STATUSES:
                next_status = incoming_status
            else:
                next_status = "open"

            status_changed = next_status != previous_status
            changed = status_changed or fill_delta > 0
            if not changed:
                return OrderFactFold(
                    order_id=order_id,
                    previous_status=previous_status,
                    status=previous_status,
                    previous_filled_qty=previous_qty,
                    cumulative_filled_qty=previous_qty,
                    fill_delta=0,
                    previous_average_fill_price=previous_price,
                    average_fill_price=previous_price,
                    changed=False,
                )

            fields: dict[str, Any] = {"status": next_status}
            if fill_delta > 0:
                fields["filled_qty"] = cumulative_qty
                # None is intentional here. Retaining an older average after
                # a larger unpriced cumulative fact would let reconciliation
                # value quantity the broker never priced.
                fields["avg_fill_price"] = avg_fill_price
            if next_status == "complete" and previous_status != "complete":
                fields["filled_at"] = utcnow()
            if reject_reason is not None and next_status in {"cancelled", "rejected"}:
                fields["reject_reason"] = reject_reason

            query = db_session.query(SmStrategyOrder).filter(
                SmStrategyOrder.id == order_id,
                SmStrategyOrder.status == raw_previous_status,
            )
            if raw_previous_qty is None:
                query = query.filter(SmStrategyOrder.filled_qty.is_(None))
            else:
                query = query.filter(SmStrategyOrder.filled_qty == raw_previous_qty)
            updated = query.update(fields, synchronize_session=False)
            if updated != 1:
                db_session.rollback()
                continue

            db_session.commit()
            db_session.expire_all()
            return OrderFactFold(
                order_id=order_id,
                previous_status=previous_status,
                status=next_status,
                previous_filled_qty=previous_qty,
                cumulative_filled_qty=cumulative_qty,
                fill_delta=fill_delta,
                previous_average_fill_price=previous_price,
                average_fill_price=avg_fill_price if fill_delta > 0 else previous_price,
                changed=True,
            )
        except Exception:
            db_session.rollback()
            logger.exception("Could not fold broker facts for order %s", order_id)
            return None

    logger.error("Could not fold broker facts for order %s after concurrent updates", order_id)
    return None


def update_order(
    order_id: int,
    status: str | None = None,
    broker_order_id: str | None = None,
    avg_fill_price: float | None = None,
    filled_qty: int | None = None,
    reject_reason: str | None = None,
) -> bool:
    """Update an order as the broker reports on it."""
    try:
        row = db_session.query(SmStrategyOrder).filter_by(id=order_id).first()
        if not row:
            return False
        if status is not None:
            row.status = status
            if status == "complete" and row.filled_at is None:
                row.filled_at = utcnow()
        if broker_order_id is not None:
            row.broker_order_id = broker_order_id
        if avg_fill_price is not None:
            row.avg_fill_price = avg_fill_price
        if filled_qty is not None:
            row.filled_qty = filled_qty
        if reject_reason is not None:
            row.reject_reason = reject_reason
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        logger.exception("Could not update order %s", order_id)
        return False


def transition_order_terminal(
    order_id: int,
    status: str,
    avg_fill_price: float | None = None,
    filled_qty: int | None = None,
    reject_reason: str | None = None,
) -> bool:
    """Atomically move one non-terminal order into a terminal status.

    Returns True only to the worker whose conditional UPDATE won. Duplicate
    terminal frames return False and must not mutate run state.
    """
    if status not in {"complete", "cancelled", "rejected"}:
        return False
    fields: dict[str, Any] = {"status": status}
    if status == "complete":
        fields["filled_at"] = utcnow()
    if avg_fill_price is not None:
        fields["avg_fill_price"] = avg_fill_price
    if filled_qty is not None:
        fields["filled_qty"] = filled_qty
    if reject_reason is not None:
        fields["reject_reason"] = reject_reason
    try:
        updated = (
            db_session.query(SmStrategyOrder)
            .filter(
                SmStrategyOrder.id == order_id,
                SmStrategyOrder.status.notin_(("complete", "cancelled", "rejected")),
            )
            .update(fields, synchronize_session=False)
        )
        db_session.commit()
        db_session.expire_all()
        return updated == 1
    except Exception:
        db_session.rollback()
        logger.exception("Could not transition order %s to %s", order_id, status)
        return False


def get_order_by_broker_id(broker_order_id: str) -> SmStrategyOrder | None:
    """The strategy order carrying this broker reference, if any.

    Order updates arrive for every order the platform places, most of which
    belong to other surfaces. This is the cheap "is it ours" test, and the
    column is indexed for it.
    """
    if not broker_order_id:
        return None
    try:
        return (
            db_session.query(SmStrategyOrder)
            .filter_by(broker_order_id=str(broker_order_id))
            .first()
        )
    except Exception:
        logger.exception("Could not look up strategy order %s", broker_order_id)
        return None


def get_order(order_id: int) -> SmStrategyOrder | None:
    """Read one strategy order by its durable row id."""
    try:
        return db_session.query(SmStrategyOrder).filter_by(id=order_id).first()
    except Exception:
        logger.exception("Could not read strategy order row %s", order_id)
        return None


def bind_order_acknowledgement(
    order_id: int,
    run_id: int,
    leg_id: int,
    *,
    broker_order_id: str | None,
    status: str,
    reject_reason: str | None,
) -> str:
    """Repair one exact pre-dispatch row from its durable ack event.

    Returns ``repaired``, ``already_bound``, ``conflict`` or ``missing``.
    Only the exact pending row identified by id/run/leg may move. An existing
    different broker id is never overwritten, and the statement also refuses
    a broker id already carried by another strategy order. Replays preserve a
    later terminal broker fact rather than reopening it.
    """
    desired_status = str(status or "").strip().lower()
    if desired_status not in {"open", "rejected"}:
        return "conflict"
    desired_broker_id = str(broker_order_id).strip() if broker_order_id else None
    if desired_status == "open" and not desired_broker_id:
        return "conflict"

    for _attempt in range(4):
        try:
            db_session.expire_all()
            row = (
                db_session.query(SmStrategyOrder)
                .filter(
                    SmStrategyOrder.id == order_id,
                    SmStrategyOrder.run_id == run_id,
                    SmStrategyOrder.leg_id == leg_id,
                )
                .first()
            )
            if row is None:
                return "missing"

            raw_status = row.status
            current_status = str(raw_status or "pending").strip().lower()
            raw_broker_id = row.broker_order_id
            current_broker_id = str(raw_broker_id).strip() if raw_broker_id else None
            if current_broker_id and current_broker_id != desired_broker_id:
                return "conflict"

            if desired_broker_id:
                collision = (
                    db_session.query(SmStrategyOrder.id)
                    .filter(
                        SmStrategyOrder.id != order_id,
                        SmStrategyOrder.broker_order_id == desired_broker_id,
                    )
                    .first()
                )
                if collision is not None:
                    return "conflict"

            if current_status != "pending":
                if desired_status == "open" and current_broker_id == desired_broker_id:
                    # Open or a later terminal fact with the exact id is
                    # stronger than the lost initial acknowledgement.
                    return "already_bound"
                if (
                    desired_status == "rejected"
                    and current_status == "rejected"
                    and current_broker_id == desired_broker_id
                ):
                    return "already_bound"
                return "conflict"

            fields: dict[str, Any] = {"status": desired_status}
            if desired_broker_id:
                fields["broker_order_id"] = desired_broker_id
            if desired_status == "rejected":
                fields["reject_reason"] = reject_reason

            query = db_session.query(SmStrategyOrder).filter(
                SmStrategyOrder.id == order_id,
                SmStrategyOrder.run_id == run_id,
                SmStrategyOrder.leg_id == leg_id,
                SmStrategyOrder.status == raw_status,
            )
            if raw_broker_id is None:
                query = query.filter(SmStrategyOrder.broker_order_id.is_(None))
            else:
                query = query.filter(SmStrategyOrder.broker_order_id == raw_broker_id)
            if desired_broker_id:
                other_owner = exists().where(
                    (SmStrategyOrder.id != order_id)
                    & (SmStrategyOrder.broker_order_id == desired_broker_id)
                )
                query = query.filter(~other_owner)

            updated = query.update(fields, synchronize_session=False)
            if updated != 1:
                db_session.rollback()
                continue
            db_session.commit()
            db_session.expire_all()
            return "repaired"
        except Exception:
            db_session.rollback()
            logger.exception(
                "Could not bind acknowledgement for order row %s on run %s",
                order_id,
                run_id,
            )
            return "conflict"

    return "conflict"


def list_orders(run_id: int) -> list[dict]:
    try:
        rows = (
            db_session.query(SmStrategyOrder)
            .filter_by(run_id=run_id)
            .order_by(SmStrategyOrder.placed_at.asc())
            .all()
        )
        return [order_to_dict(r) for r in rows]
    except Exception:
        logger.exception("Could not list orders for run %s", run_id)
        return []


def list_orders_for_strategy(strategy_id: int, run_id: int | None = None) -> list[dict]:
    """Orders across a strategy's runs, optionally narrowed to one run."""
    try:
        query = (
            db_session.query(SmStrategyOrder)
            .join(SmStrategyRun, SmStrategyOrder.run_id == SmStrategyRun.id)
            .filter(SmStrategyRun.strategy_id == strategy_id)
        )
        if run_id is not None:
            query = query.filter(SmStrategyOrder.run_id == run_id)
        rows = query.order_by(SmStrategyOrder.placed_at.asc()).all()
        return [order_to_dict(r) for r in rows]
    except Exception:
        logger.exception("Could not list orders for strategy %s", strategy_id)
        return []


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def list_order_ack_events(run_id: int) -> list[dict] | None:
    """All append-only lost-ack witnesses for one run, oldest first."""
    try:
        rows = (
            db_session.query(SmStrategyEvent)
            .filter(
                SmStrategyEvent.run_id == run_id,
                SmStrategyEvent.kind == "order_ack_unrecorded",
            )
            .order_by(SmStrategyEvent.id.asc())
            .all()
        )
        return [event_to_dict(row) for row in rows]
    except Exception:
        logger.exception("Could not list unrecorded acknowledgements for run %s", run_id)
        # Empty means "there are no witnesses". None means the safety query
        # itself failed and callers must keep the run reserved.
        return None


def record_event(
    strategy_id: int,
    user_id: str,
    kind: str,
    message: str,
    run_id: int | None = None,
    leg_id: int | None = None,
    severity: str = "info",
    payload: dict | None = None,
) -> SmStrategyEvent | None:
    """Append one row to the risk-event audit trail.

    Append-only: nothing in this module updates or deletes an event row.
    """
    try:
        row = SmStrategyEvent(
            run_id=run_id,
            strategy_id=strategy_id,
            user_id=user_id,
            kind=kind,
            severity=severity,
            leg_id=leg_id,
            message=message,
            payload=payload,
        )
        db_session.add(row)
        db_session.commit()
        return row
    except Exception:
        db_session.rollback()
        logger.exception("Could not record event %s for strategy %s", kind, strategy_id)
        return None


def list_events(
    strategy_id: int,
    run_id: int | None = None,
    kind: str | None = None,
    severity: str | None = None,
    limit: int = 500,
) -> list[dict]:
    try:
        query = db_session.query(SmStrategyEvent).filter_by(strategy_id=strategy_id)
        if run_id is not None:
            query = query.filter(SmStrategyEvent.run_id == run_id)
        if kind:
            query = query.filter(SmStrategyEvent.kind == kind)
        if severity:
            query = query.filter(SmStrategyEvent.severity == severity)
        rows = query.order_by(SmStrategyEvent.ts.desc()).limit(limit).all()
        return [event_to_dict(r) for r in rows]
    except Exception:
        logger.exception("Could not list events for strategy %s", strategy_id)
        return []


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


def write_checkpoint(run_id: int, snapshot: dict) -> bool:
    """Persist a runtime snapshot for crash recovery."""
    try:
        row = SmStrategyCheckpoint(
            run_id=run_id,
            pnl_realized=snapshot.get("pnl_realized", 0),
            pnl_unrealized=snapshot.get("pnl_unrealized", 0),
            pnl_total=snapshot.get("pnl_total", 0),
            pnl_peak=snapshot.get("pnl_peak", 0),
            pnl_trough=snapshot.get("pnl_trough", 0),
            lock_floor=snapshot.get("lock_floor"),
            trail_to_entry_active=bool(snapshot.get("trail_to_entry_active", False)),
            leg_state=snapshot.get("leg_state", {}),
        )
        db_session.add(row)
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        logger.exception("Could not write a checkpoint for run %s", run_id)
        return False


def latest_checkpoint(run_id: int) -> dict | None:
    """The most recent checkpoint for a run, which is what recovery restores."""
    try:
        row = (
            db_session.query(SmStrategyCheckpoint)
            .filter_by(run_id=run_id)
            .order_by(SmStrategyCheckpoint.ts.desc())
            .first()
        )
        return checkpoint_to_dict(row) if row else None
    except Exception:
        logger.exception("Could not read the latest checkpoint for run %s", run_id)
        return None


def list_checkpoints(run_id: int, limit: int = 1000, strategy_id: int | None = None) -> list[dict]:
    """A run's checkpoints, oldest first.

    ``strategy_id`` narrows the query to a run that actually belongs to that
    strategy. Every other list helper here is scoped by strategy already; this
    one was keyed only by run id, which left each caller to re-check ownership
    for itself. A caller that forgot would answer for somebody else's run.
    Passing it makes the store safe by default rather than by convention.
    """
    try:
        query = db_session.query(SmStrategyCheckpoint).filter(SmStrategyCheckpoint.run_id == run_id)
        if strategy_id is not None:
            query = query.join(
                SmStrategyRun, SmStrategyCheckpoint.run_id == SmStrategyRun.id
            ).filter(SmStrategyRun.strategy_id == strategy_id)
        rows = query.order_by(SmStrategyCheckpoint.ts.asc()).limit(limit).all()
        return [checkpoint_to_dict(r) for r in rows]
    except Exception:
        logger.exception("Could not list checkpoints for run %s", run_id)
        return []


def prune_checkpoints(run_id: int, keep: int = 200) -> int:
    """Keep only the newest ``keep`` checkpoints for a run.

    Checkpoints are written every few seconds for the length of a trading day,
    which is thousands of rows per run. Recovery only ever reads the newest
    one; the rest exist for the P&L chart, which does not need second-level
    resolution over a whole session. Pruning bounds a table that would
    otherwise grow without limit in a process that never restarts.
    """
    try:
        keep_ids = [
            r.id
            for r in db_session.query(SmStrategyCheckpoint.id)
            .filter_by(run_id=run_id)
            .order_by(SmStrategyCheckpoint.ts.desc())
            .limit(keep)
            .all()
        ]
        if not keep_ids:
            return 0
        deleted = (
            db_session.query(SmStrategyCheckpoint)
            .filter(
                SmStrategyCheckpoint.run_id == run_id,
                SmStrategyCheckpoint.id.notin_(keep_ids),
            )
            .delete(synchronize_session=False)
        )
        db_session.commit()
        return int(deleted or 0)
    except Exception:
        db_session.rollback()
        logger.exception("Could not prune checkpoints for run %s", run_id)
        return 0


# ---------------------------------------------------------------------------
# Webhook events
# ---------------------------------------------------------------------------


# An event that names no strategy came in on a token nothing recognises, so
# there is no owner to show it to and nothing that ever deletes it. Left
# unbounded, anyone who can reach the webhook URL can grow the database without
# limit, and none of it is visible to say so. Kept, because the first sign of
# somebody walking the token space is a run of these, but capped.
MAX_UNATTRIBUTED_WEBHOOK_EVENTS = 1000
_PRUNE_UNATTRIBUTED_EVERY = 100
_unattributed_since_prune = 0


def _prune_unattributed_webhook_events() -> None:
    """Trim ownerless audit rows to the newest MAX, every Nth one.

    Counted in process rather than queried per request: the check itself must
    not become the cost of the flood it is bounding.
    """
    global _unattributed_since_prune
    _unattributed_since_prune += 1
    if _unattributed_since_prune < _PRUNE_UNATTRIBUTED_EVERY:
        return
    _unattributed_since_prune = 0
    try:
        keep = (
            db_session.query(SmWebhookEvent.id)
            .filter(SmWebhookEvent.strategy_id.is_(None))
            .order_by(SmWebhookEvent.id.desc())
            .limit(MAX_UNATTRIBUTED_WEBHOOK_EVENTS)
            .all()
        )
        if len(keep) < MAX_UNATTRIBUTED_WEBHOOK_EVENTS:
            return
        oldest_kept = keep[-1][0]
        removed = (
            db_session.query(SmWebhookEvent)
            .filter(
                SmWebhookEvent.strategy_id.is_(None),
                SmWebhookEvent.id < oldest_kept,
            )
            .delete(synchronize_session=False)
        )
        db_session.commit()
        if removed:
            logger.info("Pruned %d unattributed webhook audit rows", removed)
    except Exception:
        db_session.rollback()
        logger.exception("Could not prune unattributed webhook events")


def record_webhook_event(
    result: str,
    strategy_id: int | None = None,
    action: str | None = None,
    mode: str | None = None,
    payload: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    error: str | None = None,
) -> SmWebhookEvent | None:
    """Audit one inbound webhook, whatever the outcome.

    Called for rejections as well as successes: a webhook that was refused is
    exactly what an operator needs to see when an alert silently stops working.
    """
    try:
        row = SmWebhookEvent(
            strategy_id=strategy_id,
            action=action,
            mode=mode,
            payload=payload,
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
            result=result,
            error=error,
        )
        db_session.add(row)
        db_session.commit()
        if strategy_id is None:
            _prune_unattributed_webhook_events()
        return row
    except Exception:
        db_session.rollback()
        logger.exception("Could not record a webhook event (%s)", result)
        return None


def list_webhook_events(strategy_id: int, limit: int = 200) -> list[dict]:
    try:
        rows = (
            db_session.query(SmWebhookEvent)
            .filter_by(strategy_id=strategy_id)
            .order_by(SmWebhookEvent.received_at.desc())
            .limit(limit)
            .all()
        )
        return [webhook_event_to_dict(r) for r in rows]
    except Exception:
        logger.exception("Could not list webhook events for strategy %s", strategy_id)
        return []
