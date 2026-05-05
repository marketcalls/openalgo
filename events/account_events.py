"""Account-scope events: account-level RMS lockouts and the broker order-update
bridge.

`AccountLockedEvent` and `AccountUnlockedEvent` cover the kill-switch-style
trip that fires when cumulative daily loss across all strategies breaches the
configured cap.

`BrokerOrderUpdateEvent` is the bridge from services/strategy/order_update_channel.py
(broker WS push or REST poll fallback) into the engine. The engine subscribes
to this topic and reconciles strategy_orders / strategy_trades / strategy_positions
for runs that own the orderid.
"""

from dataclasses import dataclass, field

from utils.event_bus import Event


@dataclass
class AccountLockedEvent(Event):
    """Account-level RMS tripped. New webhooks are rejected with 429 until the
    lockout clears (manual or scheduled auto-clear)."""
    topic: str = "account.locked"
    user_id: str = ""
    reason: str = ""                # e.g. 'DAILY_LOSS_CAP', 'MANUAL'
    until_ts_utc: int = 0           # 0 means 'until cleared manually'
    cumulative_loss: float = 0.0


@dataclass
class AccountUnlockedEvent(Event):
    """Account lockout cleared — either by user action or by the scheduled
    auto-clear time on account_risk_config."""
    topic: str = "account.unlocked"
    user_id: str = ""
    cleared_by: str = ""            # 'manual' | 'auto_next_session'


@dataclass
class BrokerOrderUpdateEvent(Event):
    """Bridge from the broker order-update channel (WS push or poll fallback)
    to the engine. Carries the broker's own status string mapped to OpenAlgo's
    canonical set: open|complete|cancelled|rejected|trigger_pending.

    The engine subscribes to this topic and updates:
      - strategy_orders.order_status (matched by orderid)
      - strategy_trades              (one row per fill if status=='complete')
      - strategy_positions           (recomputed from trades)
    """
    topic: str = "broker.order_update"
    orderid: str = ""
    status: str = ""
    filled_qty: int = 0
    average_price: float = 0.0
    raw: dict = field(default_factory=dict)
