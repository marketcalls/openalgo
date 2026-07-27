/**
 * Node Components Index
 * Export all workflow node components
 */

// Trigger Nodes
import { StartNode } from './StartNode'
import { PriceAlertNode } from './PriceAlertNode'
import { WebhookTriggerNode } from './WebhookTriggerNode'
import { HttpRequestNode } from './HttpRequestNode'

// Action Nodes
import { PlaceOrderNode } from './PlaceOrderNode'
import { SmartOrderNode } from './SmartOrderNode'
import { OptionsOrderNode } from './OptionsOrderNode'
import { OptionsMultiOrderNode } from './OptionsMultiOrderNode'
import { CancelAllOrdersNode } from './CancelAllOrdersNode'
import { ClosePositionsNode } from './ClosePositionsNode'
import { CancelOrderNode } from './CancelOrderNode'
import { ModifyOrderNode } from './ModifyOrderNode'
import { BasketOrderNode } from './BasketOrderNode'
import { SplitOrderNode } from './SplitOrderNode'

// Condition Nodes
import { PositionCheckNode } from './PositionCheckNode'
import { FundCheckNode } from './FundCheckNode'
import { TimeWindowNode } from './TimeWindowNode'
import { TimeConditionNode } from './TimeConditionNode'
import { PriceConditionNode } from './PriceConditionNode'

// Logic Gate Nodes
import { AndGateNode } from './AndGateNode'
import { OrGateNode } from './OrGateNode'
import { NotGateNode } from './NotGateNode'

// Data Nodes
import { GetQuoteNode } from './GetQuoteNode'
import { GetDepthNode } from './GetDepthNode'
import { GetOrderStatusNode } from './GetOrderStatusNode'
import { HistoryNode } from './HistoryNode'
import { OpenPositionNode } from './OpenPositionNode'
import { ExpiryNode } from './ExpiryNode'
import { IntervalsNode } from './IntervalsNode'
import { MultiQuotesNode } from './MultiQuotesNode'
import { SymbolNode } from './SymbolNode'
import { OptionSymbolNode } from './OptionSymbolNode'
import { OrderBookNode } from './OrderBookNode'
import { TradeBookNode } from './TradeBookNode'
import { PositionBookNode } from './PositionBookNode'
import { SyntheticFutureNode } from './SyntheticFutureNode'
import { OptionChainNode } from './OptionChainNode'
import { HolidaysNode } from './HolidaysNode'
import { TimingsNode } from './TimingsNode'

// WebSocket Streaming Nodes
import { SubscribeLTPNode } from './SubscribeLTPNode'
import { SubscribeQuoteNode } from './SubscribeQuoteNode'
import { SubscribeDepthNode } from './SubscribeDepthNode'
import { UnsubscribeNode } from './UnsubscribeNode'

// Risk Management Nodes
import { HoldingsNode } from './HoldingsNode'
import { FundsNode } from './FundsNode'
import { MarginNode } from './MarginNode'

// Utility Nodes
import { TelegramAlertNode } from './TelegramAlertNode'
import { DelayNode } from './DelayNode'
import { WaitUntilNode } from './WaitUntilNode'
import { GroupNode } from './GroupNode'
import { VariableNode } from './VariableNode'
import { MathExpressionNode } from './MathExpressionNode'
import { LogNode } from './LogNode'

// Base Components
export { BaseNode, NodeDataRow, NodeBadge, NodeInfoRow } from './BaseNode'

// Re-export individual nodes
export {
  // Triggers
  StartNode,
  PriceAlertNode,
  WebhookTriggerNode,
  HttpRequestNode,
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
  // Logic Gates
  AndGateNode,
  OrGateNode,
  NotGateNode,
  // Data
  GetQuoteNode,
  GetDepthNode,
  GetOrderStatusNode,
  HistoryNode,
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
  DelayNode,
  WaitUntilNode,
  GroupNode,
  VariableNode,
  MathExpressionNode,
  LogNode,
  HolidaysNode,
  TimingsNode,
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

  // Logic Gates
  andGate: AndGateNode,
  orGate: OrGateNode,
  notGate: NotGateNode,

  // Data
  getQuote: GetQuoteNode,
  getDepth: GetDepthNode,
  getOrderStatus: GetOrderStatusNode,
  history: HistoryNode,
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
  delay: DelayNode,
  waitUntil: WaitUntilNode,
  group: GroupNode,
  variable: VariableNode,
  mathExpression: MathExpressionNode,
  log: LogNode,
  holidays: HolidaysNode,
  timings: TimingsNode,
} as const
