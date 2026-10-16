// Trade-management tier (opt-in entry point: "openalgo-charts/trade").
// The on-chart order, position and bracket primitives with live P&L, which
// the trade controller reconciles from book snapshots, and the order engine's
// place, modify and cancel path.

export const TRADE_TIER = 'trade' as const;

export type { Order, Position, OrderSide, OrderType, OrderStatus, OrderRole } from './types';
export { isWorking } from './types';
export { unrealizedPnl, unrealizedPnlPercent, breakeven, riskReward, bracketValid } from './pnl';
export { WorkingOrderLine } from './order-line';
export { PositionMarker } from './position';
export { BracketGroup, type BracketState } from './bracket';
export { TradeController, type TradeHost } from './trade-controller';
export {
  FakeBroker,
  type FakeBrokerOptions,
  type FakeAccountSeed,
  type FakeBrokerOperation,
  type FakeBrokerFailure,
  type FakeOrderInfo,
} from './fake-broker';
export {
  OrderEngine,
  isPreflightFailure,
  isBrokerRejection,
  type OrderEngineOptions,
  type OrderFeed,
  type PlaceRequest,
  type PlaceResult,
  type TradeMode,
  type GateFn,
  type IntentState,
  type ModifyPatch,
  type ModifyOptions,
  type MarketOrderOptions,
  type PreflightFailure,
  type BrokerRejection,
  type BrokerOrderUpdate,
  type OrderPreview,
  type PreviewResult,
  type PositionCommandRequest,
  type ClosePositionRequest,
  type ReversePositionRequest,
  type BracketOrderRequest,
  type CommandReceipt,
  type BracketReceipt,
  type CommandResult,
  type TradingCommand,
  type TradingCommandKind,
  type OrderKind,
} from './order-engine';
export {
  checkTradingFeature,
  tradingFeatureLabel,
  ORDER_DURATIONS,
  type OrderDuration,
  type TradingFeature,
  type TradingFeatures,
  type TradingFeatureRequest,
  type TradingFeatureSource,
} from './features';
export {
  AccountManager,
  type AccountManagerOptions,
  type AccountFeed,
  type AccountState,
  type AccountStatus,
  type AccountStateSource,
  type AccountSnapshot,
  type AccountSelectResult,
  type AccountReadResult,
  type AccountHistoryQuery,
  type TradingAccount,
  type Execution,
  type OrderHistoryEntry,
} from './account';
export {
  transition,
  canTransition,
  isTerminal,
  type ClientOrderState,
  type OrderEvent,
} from './order-state-machine';
export {
  validateOrder,
  validateQuantity,
  validatePrice,
  withinPriceBand,
  type OrderConstraints,
  type PriceBand,
  type ValidationResult,
  type ValidationCode,
} from './validation';
export { orderConstraintsForInstrument } from './instrument';
export { checkTradingCapability, assertTradingCapability, TradingCapabilityError } from 'openalgo-charts';
export type { TradingOperation, TradingCapabilities, TradingCapabilityRequest, TradingCapabilitySource, TradingCapabilityResult } from 'openalgo-charts';
export {
  DomLadder,
  ladderCapability,
  buildRows,
  visibleRows,
  DEFAULT_DOM_LADDER_OPTIONS,
  type LadderTier,
  type LadderRow,
  type DomLadderOptions,
} from './dom-ladder';
