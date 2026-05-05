"""Events emitted by the Strategy v2 engine.

These events are published via utils.event_bus.bus.publish(...) and consumed by:
  - subscribers/strategy_audit_subscriber.py  → writes strategy_events DB rows
  - subscribers/socketio_subscriber.py        → emits room-scoped UI updates
  - subscribers/log_subscriber.py             → structured log lines
  - subscribers/telegram_subscriber.py        → user alerts on loud topics

Tick-rate UI updates (strategy_pnl_tick, strategy_leg_update) do NOT go
through this bus — they originate directly from realtime_broadcaster.py to
avoid saturating the 10-worker event-bus thread pool.

All timestamps in payload fields are UTC epoch ms; subscribers translate to
IST display strings via utils.ist_time as needed.
"""

from dataclasses import dataclass, field

from utils.event_bus import Event


# -----------------------------------------------------------------------------
# Webhook ingestion
# -----------------------------------------------------------------------------

@dataclass
class StrategySignalReceivedEvent(Event):
    """Webhook arrived and authenticated successfully (URL + signing method ok)."""
    topic: str = "strategy.signal_received"
    strategy_id: int = 0
    webhook_id: str = ""
    payload: dict = field(default_factory=dict)
    source_ip: str = ""
    signing_method: str = ""        # 'NONE'|'BODY_SECRET'|'HMAC_SHA256'|'BOTH'


@dataclass
class StrategySignalRejectedEvent(Event):
    """Webhook rejected before any state change. Reasons include
    INVALID_SIGNATURE, IP_NOT_ALLOWED, REPLAY_PROTECTION, ALREADY_RUNNING,
    ACCOUNT_LOCKED, RATE_LIMITED, BANNED."""
    topic: str = "strategy.signal_rejected"
    strategy_id: int = 0
    webhook_id: str = ""
    reason: str = ""
    source_ip: str = ""


@dataclass
class WebhookSecretRotatedEvent(Event):
    """A strategy's webhook secret or HMAC key was rotated. Old credentials no
    longer valid for new requests."""
    topic: str = "strategy.webhook_secret_rotated"
    strategy_id: int = 0
    method: str = ""                # method that was rotated


@dataclass
class WebhookBannedEvent(Event):
    """Adaptive ban triggered: too many signature failures within the rolling
    window. webhook_id is in the penalty box for ban_duration_seconds."""
    topic: str = "strategy.webhook_banned"
    strategy_id: int = 0
    webhook_id: str = ""
    failures: int = 0
    ban_duration_seconds: int = 0
    source_ip: str = ""


# -----------------------------------------------------------------------------
# Run lifecycle
# -----------------------------------------------------------------------------

@dataclass
class StrategyRunStartedEvent(Event):
    """Run row created and engine has begun resolving legs / placing entries."""
    topic: str = "strategy.run_started"
    strategy_id: int = 0
    run_id: int = 0
    mode: str = "live"              # 'live' | 'sandbox'
    signal_payload: dict = field(default_factory=dict)


@dataclass
class StrategyStateChangedEvent(Event):
    """Run state transition. Published by the state machine on every successful
    transition."""
    topic: str = "strategy.state_changed"
    strategy_id: int = 0
    run_id: int = 0
    old_state: str = ""
    new_state: str = ""
    reason: str = ""


@dataclass
class StrategyRunClosedEvent(Event):
    """Run reached a terminal state (CLOSED, ENTRY_FAILED, EXIT_FAILED,
    ERRORED, STOPPED). exit_reason explains how it got there."""
    topic: str = "strategy.run_closed"
    strategy_id: int = 0
    run_id: int = 0
    exit_reason: str = ""           # TARGET|SL|OVERALL_*|PROFIT_LOCK|SQUAREOFF|MANUAL|...
    realized_pnl: float = 0.0
    max_unrealized_pnl: float = 0.0
    max_drawdown: float = 0.0


# -----------------------------------------------------------------------------
# Leg lifecycle
# -----------------------------------------------------------------------------

@dataclass
class StrategyLegResolvedEvent(Event):
    """Leg resolver computed the concrete symbol for a leg. Tick-size and lot-
    size cached on the leg row at this point."""
    topic: str = "strategy.leg_resolved"
    strategy_id: int = 0
    run_id: int = 0
    leg_id: int = 0
    resolved_symbol: str = ""
    resolved_exchange: str = ""
    tick_size: float = 0.0
    lot_size: int = 0


@dataclass
class StrategyLegFilledEvent(Event):
    """Broker confirmed a fill for one of this run's entry orders. The
    position_tracker updates strategy_positions accordingly."""
    topic: str = "strategy.leg_filled"
    strategy_id: int = 0
    run_id: int = 0
    leg_id: int = 0
    avg_price: float = 0.0
    qty: int = 0
    orderid: str = ""


# -----------------------------------------------------------------------------
# RMS triggers
# -----------------------------------------------------------------------------

@dataclass
class StrategyRmsTriggeredEvent(Event):
    """An RMS rule fired for a leg or for the strategy as a whole. The exit
    flow is initiated by the engine elsewhere; this event is the audit /
    notification trail."""
    topic: str = "strategy.rms_triggered"
    strategy_id: int = 0
    run_id: int = 0
    leg_id: int = 0                 # 0 for strategy-level rules
    rule: str = ""                  # LEG_SL|LEG_TARGET|TRAIL|OVERALL_SL|OVERALL_TARGET|PROFIT_LOCK|TRAIL_TO_ENTRY
    ltp: float = 0.0
    threshold: float = 0.0
    new_sl: float = 0.0             # populated for trail / trail-to-entry events


@dataclass
class StrategyTrailAdvancedEvent(Event):
    """A trail-SL ratchet advanced one or more notches due to favorable price
    movement. Separate event from RMS_TRIGGERED so dashboards can show a
    distinct 'trail moved' indicator without tripping exit messaging."""
    topic: str = "strategy.trail_advanced"
    strategy_id: int = 0
    run_id: int = 0
    leg_id: int = 0
    advances: int = 0
    new_sl: float = 0.0
    ltp: float = 0.0


# -----------------------------------------------------------------------------
# Exit + failure
# -----------------------------------------------------------------------------

@dataclass
class StrategyExitTriggeredEvent(Event):
    """Engine has decided to flatten the run (or a single leg). Exit orders are
    being placed. State is EXITING by the time this fires."""
    topic: str = "strategy.exit_triggered"
    strategy_id: int = 0
    run_id: int = 0
    reason: str = ""
    legs_exited: int = 0
    exit_orders: list = field(default_factory=list)


@dataclass
class StrategyEnterFailedEvent(Event):
    """One or more entry orders rejected or the leg resolver failed. Run
    transitions to ENTRY_FAILED."""
    topic: str = "strategy.enter_failed"
    strategy_id: int = 0
    run_id: int = 0
    details: dict = field(default_factory=dict)


@dataclass
class StrategyExitFailedEvent(Event):
    """Exit orders were rejected or partial; reconciler timed out waiting for
    flat positions. Run transitions to EXIT_FAILED — operator intervention
    required. Triggers Telegram alert."""
    topic: str = "strategy.exit_failed"
    strategy_id: int = 0
    run_id: int = 0
    details: dict = field(default_factory=dict)


@dataclass
class StrategyEngineErrorEvent(Event):
    """Unexpected exception in the engine for this run. Run is marked ERRORED
    and dropped from the dispatch loop; other runs continue. Triggers
    Telegram alert."""
    topic: str = "strategy.engine_error"
    strategy_id: int = 0
    run_id: int = 0
    error_type: str = ""
    message: str = ""
    traceback: str = ""
