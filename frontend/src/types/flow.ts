import type { Edge as ReactFlowEdge, Node as ReactFlowNode } from '@xyflow/react'
import type { nodeTypes } from '@/components/flow/nodes'

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
  intervalMinutes?: number // Legacy - kept for backward compatibility
  intervalValue?: number // New - interval value (e.g., 1, 5, 10)
  intervalUnit?: 'seconds' | 'minutes' | 'hours' // New - interval unit
  marketHoursOnly?: boolean
}

/** Price Alert Trigger - Start when price condition met */
export interface PriceAlertNodeData {
  label?: string
  symbol: string
  exchange: string
  condition: 'above' | 'below' | 'crosses_above' | 'crosses_below'
  price: number
  ltp?: number // Live LTP from quotes API
  enabled?: boolean
}

/** Order Update Trigger - Start when a live/sandbox order changes status */
export interface OrderUpdateTriggerNodeData {
  label?: string
  orderId?: string
  symbol?: string
  exchange?: string
  status: 'any' | 'open' | 'trigger pending' | 'complete' | 'rejected' | 'cancelled'
  trigger: 'once' | 'every_time'
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
  priceType: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'MIS' | 'NRML'
  splitSize?: number
  price?: number
  triggerPrice?: number
  ltp?: number
}

/** Options Multi-Order - Multi-leg strategies */
export interface OptionsMultiOrderNodeData {
  label?: string
  strategy:
    | 'iron_condor'
    | 'straddle'
    | 'strangle'
    | 'bull_call_spread'
    | 'bear_put_spread'
    | 'custom'
  underlying: string
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string
  legs: Array<{
    /** How the leg picks its strike. Absent means OFFSET, for legacy legs. */
    strikeMode?: 'OFFSET' | 'STRIKE'
    /** Required unless the leg names an absolute `strike`. */
    offset?: string | number
    /** An absolute strike, used as given rather than resolved from the LTP. */
    strike?: string | number
    /** Overrides the node expiry with an exact date, in DDMMMYY. */
    expiry?: string
    /** Overrides the node expiry with a relative type, e.g. `next_month`. */
    expiryType?: string
    optionType: 'CE' | 'PE'
    action: 'BUY' | 'SELL'
    quantity: number | string
    product?: 'MIS' | 'NRML'
    priceType?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
    price?: number | string
    triggerPrice?: number | string
    splitSize?: number | string
  }>
  priceType: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'MIS' | 'NRML'
  price?: number
  triggerPrice?: number
}

export interface BasketOrderItem {
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number | string
  product?: 'MIS' | 'CNC' | 'NRML'
  pricetype?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  priceType?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  price?: number | string
  triggerprice?: number | string
  triggerPrice?: number | string
}

/** Basket Order - Multiple orders at once */
export interface BasketOrderNodeData {
  label?: string
  /** Basket label. The node used to render `strategy`, which nothing writes. */
  basketName?: string
  /**
   * Editor-authored baskets use newline-delimited
   * `SYMBOL,EXCHANGE,ACTION,QTY` rows. Imported workflows may retain a richer
   * per-order list with product and price overrides.
   */
  orders: string | BasketOrderItem[]
  product?: 'MIS' | 'CNC' | 'NRML'
  priceType?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  price?: number
  triggerPrice?: number
}

/** Split Order - Large order splitting */
export interface SplitOrderNodeData {
  label?: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  splitSize: number
  priceType: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'MIS' | 'CNC' | 'NRML'
  price?: number
  triggerPrice?: number
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
  /**
   * Set a symbol to close just that position; leave it blank to square off
   * everything. exchange and product only narrow a symbol-scoped close - on
   * their own they filter nothing, which is what the old "Optional filter"
   * comments implied and the executor never honoured.
   */
  symbol?: string
  exchange?: string
  product?: string
}

// =============================================================================
// CONDITION NODE DATA TYPES
// =============================================================================

/** Position Check - Check position before action */
export interface PositionCheckNodeData {
  label?: string
  symbol: string
  exchange: string
  product: 'MIS' | 'CNC' | 'NRML'
  condition:
    | 'exists'
    | 'not_exists'
    | 'quantity_above'
    | 'quantity_below'
    | 'pnl_above'
    | 'pnl_below'
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

/** Var Condition - Compare any two interpolated values (a workflow variable,
 * an indicator output like {{rsi.latest.value}}, a prior-period level, or a
 * literal). Generic counterpart to Price Condition, which always re-fetches
 * a live quote field. */
export interface VarConditionNodeData {
  label?: string
  leftValue: string
  operator: '>' | '<' | '==' | '>=' | '<=' | '!='
  rightValue: string
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

/** Get Order Status - Check order status */
export interface GetOrderStatusNodeData {
  label?: string
  orderId: string
  waitForCompletion?: boolean
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

/** Indicator - Run any openalgo.ta indicator over a symbol's history, or
 * nest on top of another Indicator node's output series. */
export interface IndicatorNodeData {
  label?: string
  symbol: string
  exchange: string
  /** Free text, not a fixed enum - any interval the connected broker's
   * /api/v1/intervals reports (use the Intervals node to discover them),
   * or a Historify custom interval (2m, 4m, W, M, Q) when source="db". */
  interval: string
  source: 'api' | 'db'
  indicatorName: string
  /** JSON object literal of extra kwargs, e.g. '{"period": 14}'. */
  params: string
  lookbackBars: number
  /** Length of the returned `series` array (fixed length so
   * {{ind.series[N]}} can address a specific historical bar - Flow JSON
   * interpolation only supports positive array indices). */
  tailBars: number
  /** Read the value N closed bars back (0 = latest). Exposed as
   * {{ind.at_offset.value}} / {{ind.at_offset.out0}} - prefer this over
   * reverse-indexing `series`, whose offsets shift with tailBars. */
  offsetBars?: number
  /** Field to pull from each sourceSeries row. Blank = auto (value, then
   * out0, then close) so a raw History array works directly. */
  sourceField?: string
  /** Optional - set to {{otherIndicator.series}} to compute this indicator
   * over another Indicator node's output instead of fetching fresh
   * history. Only single-series indicators (SMA, EMA, RSI, WMA, stdev,
   * highest/lowest, ...) can be nested this way. */
  sourceSeries?: string
  outputVariable?: string
}

/** Strategy P&L - realized / unrealized / total for one strategy, so a
 * workflow can exit on its own performance instead of the whole account's. */
export interface StrategyPnlNodeData {
  label?: string
  /** Blank = this workflow's own name, which is also the tag its order nodes apply. */
  strategy?: string
  outputVariable?: string
}

/** Prior Period OHLC - last fully-closed hour/day/week/month candle
 * (e.g. previous day's high/low for a PDH/PDL breakout strategy) without
 * the workflow author computing a relative date. */
export interface PriorPeriodOhlcNodeData {
  label?: string
  symbol: string
  exchange: string
  period: 'previous_hour' | 'previous_day' | 'previous_week' | 'previous_month'
  source: 'api' | 'db'
  outputVariable?: string
}

/** Bar Offset - OHLCV of the Nth closed bar back at any interval
 * (offsetBars=0 is the last CLOSED bar, 1 is one before that, ...). Covers
 * "N bars/hours/days back" style lookback without a node per unit. */
export interface BarOffsetNodeData {
  label?: string
  symbol: string
  exchange: string
  interval: string
  source: 'api' | 'db'
  offsetBars: number
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
  instrumenttype?: 'options' | 'futures'
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
  symbol: string // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string
}

/** OptionSymbol Node - Resolve option symbol from underlying */
export interface OptionSymbolNodeData {
  label?: string
  underlying: string // NIFTY, BANKNIFTY, etc. - can use {{variable}}
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string // Format: 30DEC25 - can use {{variable}}
  offset: string // ATM, ITM1-10, OTM1-10 - can use {{variable}}
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
  underlying: string // NIFTY, BANKNIFTY, etc.
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string // Format: 25NOV25
  outputVariable?: string
}

/** OptionChain Node - Get option chain data */
export interface OptionChainNodeData {
  label?: string
  underlying: string // NIFTY, BANKNIFTY, etc.
  exchange: 'NSE_INDEX' | 'BSE_INDEX'
  expiryDate: string // Format: 30DEC25
  strikeCount?: number // Optional: limit strikes around ATM
  outputVariable?: string
}

/** Holidays Node - Get market holidays */
export interface HolidaysNodeData {
  label?: string
  year?: number // Optional: defaults to current year
  outputVariable?: string
}

/** Timings Node - Get market timings */
export interface CalendarNodeData {
  label?: string
  date?: string // Optional: YYYY-MM-DD, defaults to the trading session date
  outputVariable?: string
}

export interface TimingsNodeData {
  label?: string
  date?: string // Optional: YYYY-MM-DD format, defaults to today
  outputVariable?: string
}

// =============================================================================
// WEBSOCKET NODE DATA TYPES (Real-time streaming)
// =============================================================================

/** Subscribe LTP Node - Real-time LTP streaming */
export interface SubscribeLTPNodeData {
  label?: string
  symbol: string // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string // Variable to store live LTP
}

/** Subscribe Quote Node - Real-time Quote streaming (OHLC + volume) */
export interface SubscribeQuoteNodeData {
  label?: string
  symbol: string // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string // Variable to store live quote data
}

/** Subscribe Depth Node - Real-time Depth streaming (order book) */
export interface SubscribeDepthNodeData {
  label?: string
  symbol: string // Can use {{variable}} interpolation
  exchange: string
  outputVariable?: string // Variable to store live depth data
}

/** Unsubscribe Node - Stop real-time streaming */
export interface UnsubscribeNodeData {
  label?: string
  symbol?: string // Symbol to unsubscribe, or empty for all
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
}

/** WhatsApp Alert - Send a WhatsApp text message via the paired bot device */
export interface WhatsappAlertNodeData {
  label?: string
  /** Phone digits (e.g. "919876543210"); empty sends to the paired device's
   * own number (self). */
  to?: string
  message: string
}

/** Delay Node - Wait for duration */
export interface DelayNodeData {
  label?: string
  delayMs?: number // Legacy: milliseconds
  delayValue?: number // New: value
  delayUnit?: 'seconds' | 'minutes' | 'hours' // New: unit
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
  operation:
    | 'set'
    | 'get'
    | 'add'
    | 'subtract'
    | 'multiply'
    | 'divide'
    | 'parse_json'
    | 'stringify'
    | 'increment'
    | 'decrement'
    | 'append'
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

/** Webhook Trigger - Start workflow from an inbound HTTP POST */
export interface WebhookTriggerNodeData {
  label?: string
  symbol?: string
  exchange?: string
}

/** Multi Quotes - Quotes for several symbols at once */
export interface MultiQuotesNodeData {
  label?: string
  /** Comma-separated symbols. */
  symbols: string
  exchange?: string
  outputVariable?: string
}

/** HTTP Request - Call an external endpoint */
export interface HttpRequestNodeData {
  label?: string
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  url: string
  /** JSON string, e.g. '{"Authorization": "Bearer {{token}}"}'. */
  headers?: string
  body?: string
  /** Milliseconds, capped at 60000 by the executor. */
  timeout?: number
  outputVariable?: string
}

/** Logic gates - combine the boolean results of their inputs. No fields. */
export interface GateNodeData {
  label?: string
}

/** Group - visual container. No fields. */
export interface GroupNodeData {
  label?: string
}

// =============================================================================
// UNION TYPES
// =============================================================================

/** All Trigger Node Data Types */
export type TriggerNodeData =
  | StartNodeData
  | PriceAlertNodeData
  | WebhookTriggerNodeData
  | OrderUpdateTriggerNodeData

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
  | PositionCheckNodeData
  | FundCheckNodeData
  | TimeWindowNodeData
  | TimeConditionNodeData
  | PriceConditionNodeData
  | VarConditionNodeData
  | GateNodeData

/** All Data Node Data Types */
export type DataNodeData =
  | GetQuoteNodeData
  | MultiQuotesNodeData
  | OptionChainNodeData
  | PositionBookNodeData
  | HoldingsNodeData
  | GetOrderStatusNodeData
  | GetDepthNodeData
  | HistoryNodeData
  | IndicatorNodeData
  | PriorPeriodOhlcNodeData
  | StrategyPnlNodeData
  | BarOffsetNodeData
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
  | WhatsappAlertNodeData
  | DelayNodeData
  | WaitUntilNodeData
  | LogNodeData
  | VariableNodeData
  | MathExpressionNodeData
  | HttpRequestNodeData
  | GroupNodeData

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

/**
 * Every node type the editor can render, derived from the ReactFlow registry.
 *
 * This was a hand-maintained NODE_TYPES object, and it had drifted badly: 16 of
 * the 61 live types were missing (andGate, httpRequest, indicator, varCondition,
 * webhookTrigger and others) while 10 entries named components that no longer
 * exist (condition, loop, getOptionChain, webhook, ...). Deriving it from the
 * registry means the two cannot disagree again.
 */
export type NodeType = keyof typeof nodeTypes

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
