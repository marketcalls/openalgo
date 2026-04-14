import type { Node as ReactFlowNode, Edge as ReactFlowEdge } from '@xyflow/react'

// =============================================================================
// TRIGGER NODE DATA TYPES
// =============================================================================

/** Schedule Trigger - Start workflow on schedule */
export interface StartNodeData {
  label?: string
  scheduleType: 'once' | 'daily' | 'weekly' | 'interval'
  time: string
  days?: number[]
  executeAt?: string
  intervalMinutes?: number  // Legacy - kept for backward compatibility
  intervalValue?: number    // New - interval value (e.g., 1, 5, 10)
  intervalUnit?: 'seconds' | 'minutes' | 'hours'  // New - interval unit
  marketHoursOnly?: boolean
}

/** Price Alert Trigger - Start when price condition met */
export interface PriceAlertNodeData {
  label?: string
  symbol: string
  exchange: string
  condition: 'above' | 'below' | 'crosses_above' | 'crosses_below'
  price: number
  ltp?: number  // Live LTP from quotes API
  enabled?: boolean
}

/** Webhook Trigger - Start from external webhook */
export interface WebhookNodeData {
  label?: string
  symbol?: string
  exchange?: string
  webhookId?: string
  webhookUrl?: string
  webhookUrlWithSymbol?: string
}

/** Position Trigger - Start when position changes */
export interface PositionTriggerNodeData {
  label?: string
  symbol: string
  exchange: string
  product: string
  condition: 'opened' | 'closed' | 'quantity_changed' | 'pnl_above' | 'pnl_below'
  threshold?: number
}

// =============================================================================
// ACTION NODE DATA TYPES
// =============================================================================

/** Place Order - Basic order placement */
export interface PlaceOrderNodeData {
  label?: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  priceType: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'MIS' | 'CNC' | 'NRML'
  price?: number
  triggerPrice?: number
  disclosedQuantity?: number
  ltp?: number
}

/** Smart Order - Position-aware ordering */
export interface SmartOrderNodeData {
  label?: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  positionSize: number
  priceType: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'MIS' | 'CNC' | 'NRML'
  price?: number
  triggerPrice?: number
  ltp?: number
}

/** Options Order - ATM/ITM/OTM options trading */
export interface OptionsOrderNodeData {
  label?: string
  underlying: string
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string
  offset: string // ATM, ITM1-10, OTM1-10
  optionType: 'CE' | 'PE'
  action: 'BUY' | 'SELL'
  quantity: number
  priceType: 'MARKET' | 'LIMIT'
  product: 'MIS' | 'NRML'
  splitSize?: number
  price?: number
  ltp?: number
}

/** Options Multi-Order - Multi-leg strategies */
export interface OptionsMultiOrderNodeData {
  label?: string
  strategy: 'iron_condor' | 'straddle' | 'strangle' | 'bull_call_spread' | 'bear_put_spread' | 'custom'
  underlying: string
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string
  legs: Array<{
    offset: string
    optionType: 'CE' | 'PE'
    action: 'BUY' | 'SELL'
    quantity: number
    expiryDate?: string // For calendar spreads
  }>
  priceType: 'MARKET' | 'LIMIT'
  product: 'MIS' | 'NRML'
}

/** Basket Order - Multiple orders at once */
export interface BasketOrderNodeData {
  label?: string
  strategy?: string
  orders: Array<{
    symbol: string
    exchange: string
    action: 'BUY' | 'SELL'
    quantity: number
    priceType: 'MARKET' | 'LIMIT'
    product: 'MIS' | 'CNC' | 'NRML'
    price?: number
  }>
}

/** Split Order - Large order splitting */
export interface SplitOrderNodeData {
  label?: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  splitSize: number
  priceType: 'MARKET' | 'LIMIT'
  product: 'MIS' | 'CNC' | 'NRML'
  price?: number
  delayMs?: number
}

/** Modify Order - Modify existing order */
export interface ModifyOrderNodeData {
  label?: string
  orderId: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  newQuantity?: number
  priceType?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product?: 'MIS' | 'CNC' | 'NRML'
  newPrice?: number
  newTriggerPrice?: number
}

/** Cancel Order - Cancel specific order */
export interface CancelOrderNodeData {
  label?: string
  orderId: string
}

/** Cancel All Orders - Cancel all open orders */
export interface CancelAllOrdersNodeData {
  label?: string
  // No specific fields needed
}

/** Close Positions - Square off positions */
export interface ClosePositionsNodeData {
  label?: string
  exchange?: string // Optional filter
  product?: string // Optional filter
}

// =============================================================================
// CONDITION NODE DATA TYPES
// =============================================================================

/** Condition Node - If/Else branching */
export interface ConditionNodeData {
  label?: string
  conditions: Array<{
    variable: string // e.g., 'ltp', 'position', 'pnl', 'time'
    operator: '>' | '<' | '==' | '>=' | '<=' | '!='
    value: string | number
  }>
  logic: 'AND' | 'OR'
}

/** Position Check - Check position before action */
export interface PositionCheckNodeData {
  label?: string
  symbol: string
  exchange: string
  product: 'MIS' | 'CNC' | 'NRML'
  condition: 'exists' | 'not_exists' | 'quantity_above' | 'quantity_below' | 'pnl_above' | 'pnl_below'
  threshold?: number
}

/** Fund Check - Check available funds */
export interface FundCheckNodeData {
  label?: string
  minAvailable: number
}

/** Time Window - Check if within time range */
export interface TimeWindowNodeData {
  label?: string
  startTime: string
  endTime: string
  days?: number[]
  invertCondition?: boolean
}

/** Time Condition - Check if time equals/passes specific time (Entry/Exit) */
export interface TimeConditionNodeData {
  label?: string
  conditionType: 'entry' | 'exit' | 'custom'
  targetTime: string
  operator: '==' | '>=' | '<=' | '>' | '<'
}

/** Greeks Condition - Check option greeks */
export interface GreeksConditionNodeData {
  label?: string
  symbol: string
  exchange: string
  greek: 'delta' | 'gamma' | 'theta' | 'vega' | 'iv'
  operator: '>' | '<' | '==' | '>=' | '<=' | '!='
  value: number
}

/** Price Condition - Check price condition */
export interface PriceConditionNodeData {
  label?: string
  symbol: string
  exchange: string
  field: 'ltp' | 'open' | 'high' | 'low' | 'prev_close' | 'change_percent'
  operator: '>' | '<' | '==' | '>=' | '<=' | '!='
  value: number
}

// =============================================================================
// DATA NODE DATA TYPES
// =============================================================================

/** Get Quote - Fetch real-time quote */
export interface GetQuoteNodeData {
  label?: string
  symbol: string
  exchange: string
  outputVariable?: string
}

/** Get Multi-Quotes - Fetch multiple quotes */
export interface GetMultiQuotesNodeData {
  label?: string
  symbols: Array<{
    symbol: string
    exchange: string
  }>
  outputVariable?: string
}

/** Get Option Chain - Fetch option chain */
export interface GetOptionChainNodeData {
  label?: string
  underlying: string
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string
  strikeCount?: number
  outputVariable?: string
}

/** Get Positions - Fetch current positions */
export interface GetPositionsNodeData {
  label?: string
  outputVariable?: string
}

/** Get Holdings - Fetch holdings */
export interface GetHoldingsNodeData {
  label?: string
  outputVariable?: string
}

/** Get Order Status - Check order status */
export interface GetOrderStatusNodeData {
  label?: string
  orderId: string
  waitForCompletion?: boolean
  outputVariable?: string
}

/** Calculate Greeks - Calculate option greeks */
export interface CalculateGreeksNodeData {
  label?: string
  symbol: string
  exchange: string
  underlyingSymbol: string
  underlyingExchange: string
  interestRate?: number
  outputVariable?: string
}

/** Get Market Depth - Fetch bid/ask depth */
export interface GetDepthNodeData {
  label?: string
  symbol: string
  exchange: string
  outputVariable?: string
}

/** Get History - Fetch historical OHLCV data */
export interface HistoryNodeData {
  label?: string
  symbol: string
  exchange: string
  interval: '1m' | '5m' | '15m' | '30m' | '1h' | '1d'
  days: number
  outputVariable?: string
}

/** Get Open Position - Fetch current position for a symbol */
export interface OpenPositionNodeData {
  label?: string
  symbol: string
  exchange: string
  product: 'MIS' | 'CNC' | 'NRML'
  outputVariable?: string
}

/** Get Expiry Dates - Fetch expiry dates for F&O */
export interface ExpiryNodeData {
  label?: string
  symbol: string
  exchange: string
  outputVariable?: string
}

/** Get Intervals - Fetch available intervals for historical data */
export interface IntervalsNodeData {
  label?: string
  outputVariable?: string
}

/** Symbol Node - Get symbol info (lotsize, tick_size, expiry, etc.) */
export interface SymbolNodeData {
  label?: string
  symbol: string  // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string
}

/** OptionSymbol Node - Resolve option symbol from underlying */
export interface OptionSymbolNodeData {
  label?: string
  underlying: string  // NIFTY, BANKNIFTY, etc. - can use {{variable}}
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string  // Format: 30DEC25 - can use {{variable}}
  offset: string  // ATM, ITM1-10, OTM1-10 - can use {{variable}}
  optionType: 'CE' | 'PE'
  outputVariable?: string
}

/** OrderBook Node - Get order book */
export interface OrderBookNodeData {
  label?: string
  outputVariable?: string
}

/** TradeBook Node - Get trade book */
export interface TradeBookNodeData {
  label?: string
  outputVariable?: string
}

/** PositionBook Node - Get all positions */
export interface PositionBookNodeData {
  label?: string
  outputVariable?: string
}

/** SyntheticFuture Node - Calculate synthetic future price */
export interface SyntheticFutureNodeData {
  label?: string
  underlying: string  // NIFTY, BANKNIFTY, etc.
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string  // Format: 25NOV25
  outputVariable?: string
}

/** OptionChain Node - Get option chain data */
export interface OptionChainNodeData {
  label?: string
  underlying: string  // NIFTY, BANKNIFTY, etc.
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string  // Format: 30DEC25
  strikeCount?: number  // Optional: limit strikes around ATM
  outputVariable?: string
}

/** Holidays Node - Get market holidays */
export interface HolidaysNodeData {
  label?: string
  year?: number  // Optional: defaults to current year
  outputVariable?: string
}

/** Timings Node - Get market timings */
export interface TimingsNodeData {
  label?: string
  date?: string  // Optional: YYYY-MM-DD format, defaults to today
  outputVariable?: string
}

// =============================================================================
// WEBSOCKET NODE DATA TYPES (Real-time streaming)
// =============================================================================

/** Subscribe LTP Node - Real-time LTP streaming */
export interface SubscribeLTPNodeData {
  label?: string
  symbol: string  // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string  // Variable to store live LTP
}

/** Subscribe Quote Node - Real-time Quote streaming (OHLC + volume) */
export interface SubscribeQuoteNodeData {
  label?: string
  symbol: string  // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string  // Variable to store live quote data
}

/** Subscribe Depth Node - Real-time Depth streaming (order book) */
export interface SubscribeDepthNodeData {
  label?: string
  symbol: string  // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string  // Variable to store live depth data
}

/** Unsubscribe Node - Stop real-time streaming */
export interface UnsubscribeNodeData {
  label?: string
  symbol?: string  // Symbol to unsubscribe, or empty for all
  exchange?: string
  streamType: 'ltp' | 'quote' | 'depth' | 'all'
}

// =============================================================================
// RISK MANAGEMENT NODE DATA TYPES
// =============================================================================

/** Holdings Node - Get portfolio holdings */
export interface HoldingsNodeData {
  label?: string
  outputVariable?: string
}

/** Funds Node - Get account funds */
export interface FundsNodeData {
  label?: string
  outputVariable?: string
}

/** Margin Node - Calculate margin requirements */
export interface MarginNodeData {
  label?: string
  positions: Array<{
    symbol: string
    exchange: string
    action: 'BUY' | 'SELL'
    quantity: number
    product: 'MIS' | 'CNC' | 'NRML'
    priceType: 'MARKET' | 'LIMIT'
  }>
  outputVariable?: string
}

// =============================================================================
// UTILITY NODE DATA TYPES
// =============================================================================

/** Telegram Alert - Send notification */
export interface TelegramAlertNodeData {
  label?: string
  message: string
  username?: string
}

/** Delay Node - Wait for duration */
export interface DelayNodeData {
  label?: string
  delayMs?: number  // Legacy: milliseconds
  delayValue?: number  // New: value
  delayUnit?: 'seconds' | 'minutes' | 'hours'  // New: unit
}

/** Wait Until Node - Pause until specific time */
export interface WaitUntilNodeData {
  label?: string
  targetTime: string
  checkIntervalMs?: number
}

/** Log Node - Log message */
export interface LogNodeData {
  label?: string
  message: string
  level: 'info' | 'warn' | 'error'
}

/** Variable Node - Store/calculate values */
export interface VariableNodeData {
  label?: string
  variableName: string
  operation: 'set' | 'get' | 'add' | 'subtract' | 'multiply' | 'divide' | 'parse_json' | 'stringify' | 'increment' | 'decrement' | 'append'
  value: string | number | object
  sourceVariable?: string // For operations that read from another variable
  jsonPath?: string // For accessing nested JSON properties like "data.ltp"
}

/** Math Expression Node - Evaluate mathematical expressions */
export interface MathExpressionNodeData {
  label?: string
  expression: string // e.g., "({{ltp}} * {{lotSize}}) + {{brokerage}}"
  outputVariable: string // Variable to store result
}

/** Loop Node - Iterate over items */
export interface LoopNodeData {
  label?: string
  items: string[] | number
  itemVariable: string
}

// =============================================================================
// UNION TYPES
// =============================================================================

/** All Trigger Node Data Types */
export type TriggerNodeData =
  | StartNodeData
  | PriceAlertNodeData
  | WebhookNodeData
  | PositionTriggerNodeData

/** All Action Node Data Types */
export type ActionNodeData =
  | PlaceOrderNodeData
  | SmartOrderNodeData
  | OptionsOrderNodeData
  | OptionsMultiOrderNodeData
  | BasketOrderNodeData
  | SplitOrderNodeData
  | ModifyOrderNodeData
  | CancelOrderNodeData
  | CancelAllOrdersNodeData
  | ClosePositionsNodeData

/** All Condition Node Data Types */
export type ConditionNodeDataTypes =
  | ConditionNodeData
  | PositionCheckNodeData
  | FundCheckNodeData
  | TimeWindowNodeData
  | TimeConditionNodeData
  | GreeksConditionNodeData
  | PriceConditionNodeData

/** All Data Node Data Types */
export type DataNodeData =
  | GetQuoteNodeData
  | GetMultiQuotesNodeData
  | GetOptionChainNodeData
  | GetPositionsNodeData
  | GetHoldingsNodeData
  | GetOrderStatusNodeData
  | CalculateGreeksNodeData
  | GetDepthNodeData
  | HistoryNodeData
  | OpenPositionNodeData
  | ExpiryNodeData
  | IntervalsNodeData
  | SymbolNodeData
  | OptionSymbolNodeData
  | OrderBookNodeData
  | TradeBookNodeData
  | PositionBookNodeData
  | SyntheticFutureNodeData
  | OptionChainNodeData
  | HolidaysNodeData
  | TimingsNodeData
  | SubscribeLTPNodeData
  | SubscribeQuoteNodeData
  | SubscribeDepthNodeData
  | UnsubscribeNodeData
  | HoldingsNodeData
  | FundsNodeData
  | MarginNodeData

/** All Utility Node Data Types */
export type UtilityNodeData =
  | TelegramAlertNodeData
  | DelayNodeData
  | WaitUntilNodeData
  | LogNodeData
  | VariableNodeData
  | MathExpressionNodeData
  | LoopNodeData

/** Union of all node data types */
export type NodeData =
  | TriggerNodeData
  | ActionNodeData
  | ConditionNodeDataTypes
  | DataNodeData
  | UtilityNodeData

// =============================================================================
// TYPED NODE DEFINITIONS
// Using Node type directly instead of custom typed nodes to avoid type constraints
// =============================================================================

/** Generic custom node type - using any to avoid type constraints */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type CustomNode = ReactFlowNode<any>

/** Custom edge type */
export type CustomEdge = ReactFlowEdge

// =============================================================================
// NODE TYPE CONSTANTS
// =============================================================================

export const NODE_TYPES = {
  // Triggers
  START: 'start',
  PRICE_ALERT: 'priceAlert',
  WEBHOOK: 'webhook',
  POSITION_TRIGGER: 'positionTrigger',
  // Actions
  PLACE_ORDER: 'placeOrder',
  SMART_ORDER: 'smartOrder',
  OPTIONS_ORDER: 'optionsOrder',
  OPTIONS_MULTI_ORDER: 'optionsMultiOrder',
  BASKET_ORDER: 'basketOrder',
  SPLIT_ORDER: 'splitOrder',
  MODIFY_ORDER: 'modifyOrder',
  CANCEL_ORDER: 'cancelOrder',
  CANCEL_ALL_ORDERS: 'cancelAllOrders',
  CLOSE_POSITIONS: 'closePositions',
  // Conditions
  CONDITION: 'condition',
  POSITION_CHECK: 'positionCheck',
  FUND_CHECK: 'fundCheck',
  TIME_WINDOW: 'timeWindow',
  TIME_CONDITION: 'timeCondition',
  GREEKS_CONDITION: 'greeksCondition',
  PRICE_CONDITION: 'priceCondition',
  // Data
  GET_QUOTE: 'getQuote',
  GET_MULTI_QUOTES: 'getMultiQuotes',
  GET_OPTION_CHAIN: 'getOptionChain',
  GET_POSITIONS: 'getPositions',
  GET_HOLDINGS: 'getHoldings',
  GET_ORDER_STATUS: 'getOrderStatus',
  CALCULATE_GREEKS: 'calculateGreeks',
  GET_DEPTH: 'getDepth',
  HISTORY: 'history',
  OPEN_POSITION: 'openPosition',
  EXPIRY: 'expiry',
  INTERVALS: 'intervals',
  SYMBOL: 'symbol',
  OPTION_SYMBOL: 'optionSymbol',
  ORDER_BOOK: 'orderBook',
  TRADE_BOOK: 'tradeBook',
  POSITION_BOOK: 'positionBook',
  SYNTHETIC_FUTURE: 'syntheticFuture',
  OPTION_CHAIN: 'optionChain',
  HOLIDAYS: 'holidays',
  TIMINGS: 'timings',
  // WebSocket (Real-time)
  SUBSCRIBE_LTP: 'subscribeLtp',
  SUBSCRIBE_QUOTE: 'subscribeQuote',
  SUBSCRIBE_DEPTH: 'subscribeDepth',
  UNSUBSCRIBE: 'unsubscribe',
  // Risk Management
  HOLDINGS: 'holdings',
  FUNDS: 'funds',
  MARGIN: 'margin',
  // Utilities
  TELEGRAM_ALERT: 'telegramAlert',
  DELAY: 'delay',
  WAIT_UNTIL: 'waitUntil',
  LOG: 'log',
  VARIABLE: 'variable',
  LOOP: 'loop',
} as const

export type NodeType = (typeof NODE_TYPES)[keyof typeof NODE_TYPES]

// =============================================================================
// STORE STATE TYPES
// =============================================================================

/** Workflow Store State */
export interface WorkflowState {
  id: number | null
  name: string
  description: string
  nodes: CustomNode[]
  edges: CustomEdge[]
  selectedNodeId: string | null
  isModified: boolean
  variables: Record<string, unknown>
}

/** Settings State */
export interface SettingsState {
  openalgo_host: string
  openalgo_ws_url: string
  is_configured: boolean
  has_api_key: boolean
}

// =============================================================================
// EXECUTION CONTEXT
// =============================================================================

/** Execution context passed between nodes */
export interface ExecutionContext {
  variables: Record<string, unknown>
  previousResult?: unknown
  logs: Array<{
    time: string
    message: string
    level: 'info' | 'warn' | 'error'
  }>
}
