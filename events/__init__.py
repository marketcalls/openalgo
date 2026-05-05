"""Event types for the OpenAlgo event bus."""

from events.account_events import (
    AccountLockedEvent,
    AccountUnlockedEvent,
    BrokerOrderUpdateEvent,
)
from events.analyzer_events import AnalyzerErrorEvent
from events.base import OrderEvent
from events.batch_events import (
    BasketCompletedEvent,
    MultiOrderCompletedEvent,
    OptionsOrderCompletedEvent,
    SplitCompletedEvent,
)
from events.order_events import (
    GTTCancelFailedEvent,
    GTTCancelledEvent,
    GTTExpiredEvent,
    GTTFailedEvent,
    GTTModifiedEvent,
    GTTModifyFailedEvent,
    GTTPlacedEvent,
    GTTTriggeredEvent,
    OrderCancelFailedEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderModifiedEvent,
    OrderModifyFailedEvent,
    OrderPlacedEvent,
    SmartOrderNoActionEvent,
)
from events.position_events import AllOrdersCancelledEvent, PositionClosedEvent
from events.sandbox_events import (
    SandboxAutoSquareOffEvent,
    SandboxOrderFilledEvent,
    SandboxT1SettlementEvent,
)
from events.strategy_events import (
    StrategyEngineErrorEvent,
    StrategyEnterFailedEvent,
    StrategyExitFailedEvent,
    StrategyExitTriggeredEvent,
    StrategyLegFilledEvent,
    StrategyLegResolvedEvent,
    StrategyRmsTriggeredEvent,
    StrategyRunClosedEvent,
    StrategyRunStartedEvent,
    StrategySignalReceivedEvent,
    StrategySignalRejectedEvent,
    StrategyStateChangedEvent,
    StrategyTrailAdvancedEvent,
    WebhookBannedEvent,
    WebhookSecretRotatedEvent,
)

__all__ = [
    "OrderEvent",
    "OrderPlacedEvent",
    "OrderFailedEvent",
    "SmartOrderNoActionEvent",
    "OrderModifiedEvent",
    "OrderModifyFailedEvent",
    "OrderCancelledEvent",
    "OrderCancelFailedEvent",
    "BasketCompletedEvent",
    "SplitCompletedEvent",
    "OptionsOrderCompletedEvent",
    "MultiOrderCompletedEvent",
    "PositionClosedEvent",
    "AllOrdersCancelledEvent",
    "AnalyzerErrorEvent",
    "SandboxOrderFilledEvent",
    "SandboxAutoSquareOffEvent",
    "SandboxT1SettlementEvent",
    "GTTPlacedEvent",
    "GTTFailedEvent",
    "GTTModifiedEvent",
    "GTTModifyFailedEvent",
    "GTTCancelledEvent",
    "GTTCancelFailedEvent",
    "GTTTriggeredEvent",
    "GTTExpiredEvent",
    # Strategy v2
    "StrategySignalReceivedEvent",
    "StrategySignalRejectedEvent",
    "StrategyRunStartedEvent",
    "StrategyStateChangedEvent",
    "StrategyLegResolvedEvent",
    "StrategyLegFilledEvent",
    "StrategyRmsTriggeredEvent",
    "StrategyTrailAdvancedEvent",
    "StrategyExitTriggeredEvent",
    "StrategyEnterFailedEvent",
    "StrategyExitFailedEvent",
    "StrategyRunClosedEvent",
    "StrategyEngineErrorEvent",
    "WebhookSecretRotatedEvent",
    "WebhookBannedEvent",
    # Account
    "AccountLockedEvent",
    "AccountUnlockedEvent",
    "BrokerOrderUpdateEvent",
]
