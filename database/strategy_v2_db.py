"""Strategy v2 — DB schema.

All tables in db/openalgo.db, additive to the v1 schema (which keeps running
through Phase 7 and is removed in Phase 8 per the implementation plan).

Hot-path queries (engine tick dispatch, webhook lookups) use the indexes
declared inline below. The unique partial index `idx_strategy_runs_active`
is the duplicate-signal guard — see plan §6.3.

Sensitive columns (webhook_secret, webhook_hmac_key) are encrypted at rest
via utils.secret_box; ORM accessors decrypt on read.

Pattern follows the existing OpenAlgo DB modules:
  - NullPool for SQLite (matches CLAUDE.md guidance)
  - scoped_session bound to the same engine
  - declarative_base; Base.query for legacy callers
  - init_db() called from app.py at startup; idempotent
"""

import logging
import os
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    DECIMAL,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from utils.secret_box import decrypt_at_rest, encrypt_at_rest

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


# ============================================================================
# Strategies
# ============================================================================


class StrategyV2(Base):
    """A strategy definition. Webhook URL is /strategy/webhook/<webhook_id>."""

    __tablename__ = "strategies_v2"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    webhook_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(String(255), nullable=False, index=True)
    platform = Column(String(50))
    # Phase 9 — segment drives whether 'underlying' is meaningful. CASH
    # strategies operate on individual stocks (per-leg exchange + symbol)
    # and don't need an Index/F&O underlying. INDEX_FO strategies (futures
    # / options on NIFTY, BANKNIFTY, etc.) use the underlying field for
    # leg resolution at arm-time.
    segment = Column(String(10), nullable=False, default="CASH")
    underlying = Column(String(50))
    underlying_exchange = Column(String(15))
    is_intraday = Column(Boolean, default=True)
    start_time = Column(String(5), nullable=False)
    # end_time is required for INTRADAY (HH:MM exit window) but irrelevant
    # for POSITIONAL strategies that use exit_date or run_forever instead.
    # Kept nullable so positional rows can omit it. Existing intraday rows
    # always have a value because the form enforces it.
    end_time = Column(String(5))
    squareoff_time = Column(String(5))
    # Phase 9 — positional-only fields. Mutually exclusive: either
    # exit_date is set (auto-flat at end of that calendar day in IST),
    # or run_forever=True (no auto-flat — manual close only). Validation
    # at the marshmallow layer.
    exit_date = Column(String(10))   # ISO date YYYY-MM-DD (string for SQLite portability)
    run_forever = Column(Boolean, default=False)
    state = Column(String(15), nullable=False, default="DRAFT")
    is_active = Column(Boolean, default=False, index=True)
    mode = Column(String(10), nullable=False, default="live")
    # Phase 11 — webhook dispatch direction. The ingestion service
    # interprets the payload's "action" field against this mode:
    #   LONG  : BUY=enter long, SELL=close long
    #   SHORT : SELL=enter short, BUY=close short
    #   BOTH  : BUY/SELL with position_size>0 opens that direction;
    #           position_size=0 closes the opposite-direction position
    trading_mode = Column(String(10), nullable=False, default="LONG")

    # Webhook security — see plan §8.4. Sensitive columns encrypted at rest.
    webhook_signing_method = Column(String(20), nullable=False, default="NONE")
    _webhook_secret = Column("webhook_secret", String(256))
    _webhook_hmac_key = Column("webhook_hmac_key", String(384))
    webhook_replay_window_seconds = Column(Integer, default=0)
    webhook_ip_allowlist = Column(Text)  # JSON-encoded list of CIDRs

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    legs = relationship("StrategyLeg", back_populates="strategy", cascade="all, delete-orphan")
    risk_config = relationship(
        "StrategyRiskConfig",
        back_populates="strategy",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("state IN ('DRAFT','ARMED','DISABLED','ARCHIVED')", name="ck_strat_state"),
        CheckConstraint("mode IN ('live','sandbox')", name="ck_strat_mode"),
        CheckConstraint(
            "webhook_signing_method IN ('NONE','BODY_SECRET','HMAC_SHA256','BOTH')",
            name="ck_strat_signing",
        ),
        CheckConstraint(
            "segment IN ('CASH','INDEX_FO','STOCK_FO')",
            name="ck_strat_segment",
        ),
        CheckConstraint(
            "trading_mode IN ('LONG','SHORT','BOTH')",
            name="ck_strat_trading_mode",
        ),
    )

    # --- Encrypted accessors -------------------------------------------------
    @property
    def webhook_secret(self) -> Optional[str]:
        return decrypt_at_rest(self._webhook_secret)

    @webhook_secret.setter
    def webhook_secret(self, value: Optional[str]) -> None:
        self._webhook_secret = encrypt_at_rest(value)

    @property
    def webhook_hmac_key(self) -> Optional[str]:
        return decrypt_at_rest(self._webhook_hmac_key)

    @webhook_hmac_key.setter
    def webhook_hmac_key(self, value: Optional[str]) -> None:
        self._webhook_hmac_key = encrypt_at_rest(value)


class StrategyLeg(Base):
    """One leg of a strategy. Segment-aware via conditional NULLs + CHECK.
    Tick-size, lot-size, and freeze_qty are cached at arm-time so the RMS
    tick loop never hits symbol_service."""

    __tablename__ = "strategy_legs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(
        Integer, ForeignKey("strategies_v2.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leg_index = Column(Integer, nullable=False)
    segment = Column(String(5), nullable=False)
    position = Column(String(1), nullable=False)
    product = Column(String(10), nullable=False)

    # CASH-only
    symbol_cash = Column(String(50))
    # Phase 9 — per-leg exchange for CASH legs. Lets a single strategy
    # mix NSE and BSE stocks, or include an MCX commodity equivalent in
    # the same basket. Defaults to NSE on rows that pre-date the column.
    exchange_cash = Column(String(15))
    qty = Column(Integer)

    # FUT + OPT
    expiry_type = Column(String(20))
    lots = Column(Integer)

    # OPT-only
    option_type = Column(String(2))
    strike_criteria = Column(String(20))
    strike_value = Column(DECIMAL(12, 4))

    # Per-leg risk (each pair stored independently — pts or pct)
    target_enabled = Column(Boolean, default=False)
    target_value = Column(DECIMAL(12, 4))
    target_unit = Column(String(3))

    sl_enabled = Column(Boolean, default=False)
    sl_value = Column(DECIMAL(12, 4))
    sl_unit = Column(String(3))

    trail_enabled = Column(Boolean, default=False)
    trail_x = Column(DECIMAL(12, 4))
    trail_y = Column(DECIMAL(12, 4))
    trail_unit = Column(String(3))

    momentum_enabled = Column(Boolean, default=False)
    momentum_value = Column(DECIMAL(12, 4))
    momentum_unit = Column(String(3))
    momentum_config = Column(Text)

    # Cached at arm-time
    resolved_symbol = Column(String(50))
    resolved_exchange = Column(String(15))
    lot_size_cache = Column(Integer)
    tick_size_cache = Column(DECIMAL(12, 4))
    freeze_qty_cache = Column(Integer)
    resolved_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    strategy = relationship("StrategyV2", back_populates="legs")

    __table_args__ = (
        CheckConstraint("segment IN ('CASH','FUT','OPT')", name="ck_leg_segment"),
        CheckConstraint("position IN ('B','S')", name="ck_leg_position"),
        CheckConstraint(
            "(segment = 'CASH' AND symbol_cash IS NOT NULL AND qty IS NOT NULL) "
            "OR (segment = 'FUT' AND lots IS NOT NULL AND expiry_type IS NOT NULL) "
            "OR (segment = 'OPT' AND lots IS NOT NULL AND expiry_type IS NOT NULL "
            "    AND option_type IS NOT NULL AND strike_criteria IS NOT NULL)",
            name="ck_leg_segment_fields",
        ),
    )


class StrategyRiskConfig(Base):
    """Strategy-level (overall) RMS configuration. Abs ₹ only — strategies
    don't carry capital, so % is meaningless at this scope. Per-leg risk
    on StrategyLeg still supports pct since it's relative to leg entry."""

    __tablename__ = "strategy_risk_config"

    strategy_id = Column(
        Integer,
        ForeignKey("strategies_v2.id", ondelete="CASCADE"),
        primary_key=True,
    )

    overall_sl_enabled = Column(Boolean, default=False)
    overall_sl_abs = Column(DECIMAL(16, 4))

    overall_target_enabled = Column(Boolean, default=False)
    overall_target_abs = Column(DECIMAL(16, 4))

    lock_profit_enabled = Column(Boolean, default=False)
    lock_at_abs = Column(DECIMAL(16, 4))
    lock_min_abs = Column(DECIMAL(16, 4))

    trail_to_entry_enabled = Column(Boolean, default=False)
    trail_to_entry_threshold = Column(DECIMAL(12, 4), default=0)
    trail_to_entry_unit = Column(String(3), default="pct")

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    strategy = relationship("StrategyV2", back_populates="risk_config")


# ============================================================================
# Runs
# ============================================================================


class StrategyRun(Base):
    """One execution lifecycle of a strategy — signal received to all-flat."""

    __tablename__ = "strategy_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("strategies_v2.id"), nullable=False, index=True)
    # Phase 13 — when set, this run is scoped to a single leg (CASH per-
    # symbol routing). When NULL, the run is strategy-level (F&O pack —
    # all legs fire together). The unique partial index below enforces
    # at most one active run per (strategy_id, leg_id_or_zero).
    leg_id = Column(Integer)
    state = Column(String(20), nullable=False, index=True)
    mode = Column(String(10), nullable=False)
    signal_payload = Column(Text)
    signal_source = Column(String(20))

    triggered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    entered_at = Column(DateTime(timezone=True))
    exited_at = Column(DateTime(timezone=True))
    exit_reason = Column(String(30))

    peak_mtm = Column(DECIMAL(16, 4), default=0)
    trough_mtm = Column(DECIMAL(16, 4), default=0)
    profit_locked = Column(Boolean, default=False)
    realized_pnl = Column(DECIMAL(16, 4), default=0)
    max_unrealized_pnl = Column(DECIMAL(16, 4), default=0)
    max_drawdown = Column(DECIMAL(16, 4), default=0)

    __table_args__ = (
        CheckConstraint(
            "state IN ('ARMED','ENTERING','IN_TRADE','EXITING','CLOSED',"
            "'ENTRY_FAILED','EXIT_FAILED','ERRORED','STOPPED')",
            name="ck_run_state",
        ),
        CheckConstraint("mode IN ('live','sandbox')", name="ck_run_mode"),
        # Phase 13 — per-leg active-run scoping. F&O packs use leg_id=NULL
        # which IFNULL collapses to 0; CASH legs use the matched leg.id.
        # Result: at most one active run per (strategy, pack-or-leg).
        Index(
            "idx_strategy_runs_active_per_leg",
            text("strategy_id"),
            text("IFNULL(leg_id, 0)"),
            unique=True,
            sqlite_where=text(
                "state IN ('ARMED','ENTERING','IN_TRADE','EXITING')"
            ),
        ),
    )


# ============================================================================
# Strategy-scoped orderbook / tradebook / positionbook
# ============================================================================


class StrategyOrder(Base):
    """One row per order placement attempt. Columns 1:1 with the global
    /orderbook response shape so the same React table component can render
    both views."""

    __tablename__ = "strategy_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("strategy_runs.id"), nullable=False, index=True)
    leg_id = Column(Integer, ForeignKey("strategy_legs.id"))

    # /orderbook-shape columns
    action = Column(String(10), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(15), nullable=False)
    orderid = Column(String(50))
    product = Column(String(10), nullable=False)
    quantity = Column(String(20), nullable=False)
    price = Column(DECIMAL(12, 4), default=0)
    pricetype = Column(String(10), nullable=False)
    order_status = Column(String(20), default="pending", index=True)
    trigger_price = Column(DECIMAL(12, 4), default=0)
    timestamp = Column(String(30))  # IST display string from broker

    # Strategy-only metadata
    source = Column(String(30), nullable=False)
    mode = Column(String(10), nullable=False)
    rms_event_id = Column(Integer)
    placed_at = Column(DateTime(timezone=True), server_default=func.now())
    last_status_update_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("mode IN ('live','sandbox')", name="ck_order_mode"),
    )


class StrategyTrade(Base):
    """One row per fill confirmation. Columns 1:1 with /tradebook shape."""

    __tablename__ = "strategy_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("strategy_orders.id"), nullable=False)
    strategy_id = Column(Integer, nullable=False)
    run_id = Column(Integer, nullable=False, index=True)
    leg_id = Column(Integer, index=True)

    action = Column(String(10), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(15), nullable=False)
    orderid = Column(String(50))
    product = Column(String(10))
    quantity = Column(DECIMAL(12, 2), nullable=False)
    average_price = Column(DECIMAL(12, 4), nullable=False)
    trade_value = Column(DECIMAL(16, 4), nullable=False)
    timestamp = Column(String(30))  # IST 'HH:MM:SS' from broker
    broker_tradeid = Column(String(50))

    traded_at = Column(DateTime(timezone=True), server_default=func.now())


class StrategyPosition(Base):
    """Net position per leg per run, derived from orders+trades. Same /positionbook
    shape on the display columns; engine-internal decimal columns kept separate."""

    __tablename__ = "strategy_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, nullable=False)
    run_id = Column(Integer, nullable=False, index=True)
    leg_id = Column(Integer, nullable=False)

    # /positionbook columns
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(15), nullable=False)
    product = Column(String(10), nullable=False)
    quantity = Column(String(20))
    average_price = Column(String(20))
    ltp = Column(String(20))
    pnl = Column(String(20))

    # Engine-internal (decimal)
    net_qty = Column(Integer, nullable=False, default=0)
    avg_entry = Column(DECIMAL(12, 4))
    ltp_decimal = Column(DECIMAL(12, 4))
    unrealized_pnl = Column(DECIMAL(16, 4), default=0)
    realized_pnl = Column(DECIMAL(16, 4), default=0)

    # RMS live state
    current_sl_price = Column(DECIMAL(12, 4))
    current_target_price = Column(DECIMAL(12, 4))
    last_trail_anchor = Column(DECIMAL(12, 4))
    trail_advances_count = Column(Integer, default=0)
    peak_favorable_price = Column(DECIMAL(12, 4))
    trail_to_entry_armed = Column(Boolean, default=False)

    leg_state = Column(String(20), default="PENDING_ENTRY")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", "leg_id", name="uq_position_run_leg"),
        CheckConstraint(
            "leg_state IN ('PENDING_ENTRY','OPEN','EXITING_LEG','CLOSED','ENTRY_REJECTED')",
            name="ck_position_leg_state",
        ),
        Index("idx_strategy_positions_symbol", "symbol", "exchange"),
    )


# ============================================================================
# Audit + telemetry
# ============================================================================


class StrategyEvent(Base):
    """Append-only audit log. Single writer is subscribers/strategy_audit_subscriber.
    Engine NEVER inserts rows here directly — see plan §13 D21.

    Each row carries prev_hash (SHA-256 of previous row's payload + prev_hash)
    forming a tamper-evident chain. GET /strategy/api/v2/audit/verify/<run_id>
    walks the chain and reports the first divergence."""

    __tablename__ = "strategy_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, nullable=False)
    run_id = Column(Integer, index=True)
    leg_id = Column(Integer)
    ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    type = Column(String(40), nullable=False)
    payload = Column(Text)
    prev_hash = Column(String(64))  # SHA-256 hex of previous (payload + prev_hash)
    row_hash = Column(String(64))   # SHA-256 hex of this row's (payload + prev_hash)


class StrategyPnlSnapshot(Base):
    """1Hz time-series for P&L charts. Off when run is not IN_TRADE."""

    __tablename__ = "strategy_pnl_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, nullable=False)
    run_id = Column(Integer, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    agg_mtm = Column(DECIMAL(16, 4), nullable=False)
    peak_mtm = Column(DECIMAL(16, 4), nullable=False)
    drawdown = Column(DECIMAL(16, 4), nullable=False)
    leg_mtms = Column(Text)  # JSON: {leg_id: mtm}

    __table_args__ = (
        Index("idx_strategy_pnl_run_ts", "run_id", "ts"),
    )


# ============================================================================
# Account
# ============================================================================


class AccountRiskConfig(Base):
    """Single-user platform — one row per user_id."""

    __tablename__ = "account_risk_config"

    user_id = Column(String(255), primary_key=True)
    max_concurrent_runs = Column(Integer, default=5)
    max_daily_loss_abs = Column(DECIMAL(16, 2))
    cooldown_after_loss_minutes = Column(Integer, default=0)
    max_runs_per_strategy_per_day = Column(Integer, default=50)
    min_seconds_between_runs = Column(Integer, default=0)
    is_locked_out = Column(Boolean, default=False)
    lockout_until = Column(DateTime(timezone=True))
    lockout_reason = Column(String(80))
    auto_clear_at = Column(String(5))  # HH:MM IST or NULL = manual only
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AccountState(Base):
    """Denormalized live state for fast preflight. Maintained by the engine."""

    __tablename__ = "account_state"

    user_id = Column(String(255), primary_key=True)
    active_run_count = Column(Integer, default=0)
    realized_pnl_today_live = Column(DECIMAL(16, 4), default=0)
    realized_pnl_today_sandbox = Column(DECIMAL(16, 4), default=0)
    unrealized_pnl_aggregate = Column(DECIMAL(16, 4), default=0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ============================================================================
# Init
# ============================================================================


def init_db() -> None:
    """Create v2 tables if they don't exist. Idempotent — safe to call on every
    app start. v1 tables (strategies, strategy_symbol_mappings) are untouched
    here; they're handled by database/strategy_db.py until Phase 8 cleanup."""
    logger.info("Initializing Strategy v2 DB tables")
    Base.metadata.create_all(bind=engine)
