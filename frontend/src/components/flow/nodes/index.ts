/**
 * Node Components Index
 * Export all workflow node components
 */

// Logic Gate Nodes
import { AndGateNode } from './AndGateNode'
import { BarOffsetNode } from './BarOffsetNode'
import { BasketOrderNode } from './BasketOrderNode'
import { CalendarNode } from './CalendarNode'
import { CancelAllOrdersNode } from './CancelAllOrdersNode'
import { CancelOrderNode } from './CancelOrderNode'
import { ClosePositionsNode } from './ClosePositionsNode'
import { DelayNode } from './DelayNode'
import { ExpiryNode } from './ExpiryNode'
import { FundCheckNode } from './FundCheckNode'
import { FundsNode } from './FundsNode'
import { GetDepthNode } from './GetDepthNode'
import { GetOrderStatusNode } from './GetOrderStatusNode'
// Data Nodes
import { GetQuoteNode } from './GetQuoteNode'
import { GroupNode } from './GroupNode'
import { HistoryNode } from './HistoryNode'
// Risk Management Nodes
import { HoldingsNode } from './HoldingsNode'
import { HolidaysNode } from './HolidaysNode'
import { HttpRequestNode } from './HttpRequestNode'
import { IndicatorNode } from './IndicatorNode'
import { IntervalsNode } from './IntervalsNode'
import { LogNode } from './LogNode'
import { MarginNode } from './MarginNode'
import { MathExpressionNode } from './MathExpressionNode'
import { ModifyOrderNode } from './ModifyOrderNode'
import { MultiQuotesNode } from './MultiQuotesNode'
import { NotGateNode } from './NotGateNode'
import { OpenPositionNode } from './OpenPositionNode'
import { OptionChainNode } from './OptionChainNode'
import { OptionSymbolNode } from './OptionSymbolNode'
import { OptionsMultiOrderNode } from './OptionsMultiOrderNode'
import { OptionsOrderNode } from './OptionsOrderNode'
import { OrderBookNode } from './OrderBookNode'
import { OrderUpdateTriggerNode } from './OrderUpdateTriggerNode'
import { OrGateNode } from './OrGateNode'
// Action Nodes
import { PlaceOrderNode } from './PlaceOrderNode'
import { PositionBookNode } from './PositionBookNode'
// Condition Nodes
import { PositionCheckNode } from './PositionCheckNode'
import { PriceAlertNode } from './PriceAlertNode'
import { PriceConditionNode } from './PriceConditionNode'
import { PriorPeriodOhlcNode } from './PriorPeriodOhlcNode'
import { SmartOrderNode } from './SmartOrderNode'
import { SplitOrderNode } from './SplitOrderNode'
// Trigger Nodes
import { StartNode } from './StartNode'
import { StrategyPnlNode } from './StrategyPnlNode'
import { SubscribeDepthNode } from './SubscribeDepthNode'
// WebSocket Streaming Nodes
import { SubscribeLTPNode } from './SubscribeLTPNode'
import { SubscribeQuoteNode } from './SubscribeQuoteNode'
import { SymbolNode } from './SymbolNode'
import { SyntheticFutureNode } from './SyntheticFutureNode'
// Utility Nodes
import { TelegramAlertNode } from './TelegramAlertNode'
import { TimeConditionNode } from './TimeConditionNode'
import { TimeWindowNode } from './TimeWindowNode'
import { TimingsNode } from './TimingsNode'
import { TradeBookNode } from './TradeBookNode'
import { UnsubscribeNode } from './UnsubscribeNode'
import { VarConditionNode } from './VarConditionNode'
import { VariableNode } from './VariableNode'
import { WaitUntilNode } from './WaitUntilNode'
import { WebhookTriggerNode } from './WebhookTriggerNode'
import { WhatsappAlertNode } from './WhatsappAlertNode'

// Base Components
export { BaseNode, NodeBadge, NodeDataRow, NodeInfoRow } from './BaseNode'

// Re-export individual nodes
export {
  // Triggers
  StartNode,
  PriceAlertNode,
  WebhookTriggerNode,
  HttpRequestNode,
  OrderUpdateTriggerNode,
  // Actions
  PlaceOrderNode,
  SmartOrderNode,
  OptionsOrderNode,
  OptionsMultiOrderNode,
  CancelAllOrdersNode,
  ClosePositionsNode,
  CancelOrderNode,
  ModifyOrderNode,
  BasketOrderNode,
  SplitOrderNode,
  // Conditions
  PositionCheckNode,
  FundCheckNode,
  TimeWindowNode,
  TimeConditionNode,
  PriceConditionNode,
  VarConditionNode,
  // Logic Gates
  AndGateNode,
  OrGateNode,
  NotGateNode,
  // Data
  GetQuoteNode,
  GetDepthNode,
  GetOrderStatusNode,
  HistoryNode,
  IndicatorNode,
  PriorPeriodOhlcNode,
  StrategyPnlNode,
  BarOffsetNode,
  OpenPositionNode,
  ExpiryNode,
  IntervalsNode,
  MultiQuotesNode,
  SymbolNode,
  OptionSymbolNode,
  OrderBookNode,
  TradeBookNode,
  PositionBookNode,
  SyntheticFutureNode,
  OptionChainNode,
  // WebSocket Streaming
  SubscribeLTPNode,
  SubscribeQuoteNode,
  SubscribeDepthNode,
  UnsubscribeNode,
  // Risk Management
  HoldingsNode,
  FundsNode,
  MarginNode,
  // Utilities
  TelegramAlertNode,
  WhatsappAlertNode,
  DelayNode,
  WaitUntilNode,
  GroupNode,
  VariableNode,
  MathExpressionNode,
  LogNode,
  HolidaysNode,
  TimingsNode,
  CalendarNode,
}

/**
 * Node type registry for ReactFlow
 * Maps node type strings to their components
 */
export const nodeTypes = {
  // Triggers
  start: StartNode,
  priceAlert: PriceAlertNode,
  webhookTrigger: WebhookTriggerNode,
  httpRequest: HttpRequestNode,
  orderUpdateTrigger: OrderUpdateTriggerNode,

  // Actions
  placeOrder: PlaceOrderNode,
  smartOrder: SmartOrderNode,
  optionsOrder: OptionsOrderNode,
  optionsMultiOrder: OptionsMultiOrderNode,
  cancelAllOrders: CancelAllOrdersNode,
  closePositions: ClosePositionsNode,
  cancelOrder: CancelOrderNode,
  modifyOrder: ModifyOrderNode,
  basketOrder: BasketOrderNode,
  splitOrder: SplitOrderNode,

  // Conditions
  positionCheck: PositionCheckNode,
  fundCheck: FundCheckNode,
  timeWindow: TimeWindowNode,
  timeCondition: TimeConditionNode,
  priceCondition: PriceConditionNode,
  varCondition: VarConditionNode,

  // Logic Gates
  andGate: AndGateNode,
  orGate: OrGateNode,
  notGate: NotGateNode,

  // Data
  getQuote: GetQuoteNode,
  getDepth: GetDepthNode,
  getOrderStatus: GetOrderStatusNode,
  history: HistoryNode,
  indicator: IndicatorNode,
  priorPeriodOhlc: PriorPeriodOhlcNode,
  strategyPnl: StrategyPnlNode,
  barOffset: BarOffsetNode,
  openPosition: OpenPositionNode,
  expiry: ExpiryNode,
  intervals: IntervalsNode,
  multiQuotes: MultiQuotesNode,
  symbol: SymbolNode,
  optionSymbol: OptionSymbolNode,
  orderBook: OrderBookNode,
  tradeBook: TradeBookNode,
  positionBook: PositionBookNode,
  syntheticFuture: SyntheticFutureNode,
  optionChain: OptionChainNode,

  // WebSocket Streaming
  subscribeLtp: SubscribeLTPNode,
  subscribeQuote: SubscribeQuoteNode,
  subscribeDepth: SubscribeDepthNode,
  unsubscribe: UnsubscribeNode,

  // Risk Management
  holdings: HoldingsNode,
  funds: FundsNode,
  margin: MarginNode,

  // Utilities
  telegramAlert: TelegramAlertNode,
  whatsappAlert: WhatsappAlertNode,
  delay: DelayNode,
  waitUntil: WaitUntilNode,
  group: GroupNode,
  variable: VariableNode,
  mathExpression: MathExpressionNode,
  log: LogNode,
  holidays: HolidaysNode,
  timings: TimingsNode,
  calendar: CalendarNode,
} as const
