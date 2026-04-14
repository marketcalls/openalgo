// lib/flow/constants.ts
// Constants for Flow workflow editor

// =============================================================================
// EXCHANGE CONSTANTS
// =============================================================================

export const EXCHANGES = [
  { value: 'NSE', label: 'NSE' },
  { value: 'BSE', label: 'BSE' },
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
  { value: 'CDS', label: 'CDS' },
  { value: 'BCD', label: 'BCD' },
  { value: 'MCX', label: 'MCX' },
  { value: 'NSE_INDEX', label: 'NSE_INDEX' },
  { value: 'BSE_INDEX', label: 'BSE_INDEX' },
] as const

export const INDEX_EXCHANGES = [
  { value: 'NSE_INDEX', label: 'NSE_INDEX' },
  { value: 'BSE_INDEX', label: 'BSE_INDEX' },
] as const

// =============================================================================
// PRODUCT & ORDER TYPES
// =============================================================================

export const PRODUCT_TYPES = [
  { value: 'MIS', label: 'MIS', description: 'Intraday (auto square-off)' },
  { value: 'CNC', label: 'CNC', description: 'Cash & Carry for equity delivery' },
  { value: 'NRML', label: 'NRML', description: 'Normal for futures and options' },
] as const

export const PRICE_TYPES = [
  { value: 'MARKET', label: 'Market', description: 'Execute at current market price' },
  { value: 'LIMIT', label: 'Limit', description: 'Execute at specified price or better' },
  { value: 'SL', label: 'Stop Loss Limit', description: 'Stop loss with limit price' },
  { value: 'SL-M', label: 'Stop Loss Market', description: 'Stop loss at market price' },
] as const

export const ORDER_ACTIONS = [
  { value: 'BUY', label: 'BUY', color: 'badge-buy' },
  { value: 'SELL', label: 'SELL', color: 'badge-sell' },
] as const

// =============================================================================
// OPTIONS TRADING CONSTANTS
// =============================================================================

export const OPTION_TYPES = [
  { value: 'CE', label: 'Call (CE)', description: 'Call Option' },
  { value: 'PE', label: 'Put (PE)', description: 'Put Option' },
] as const

export const STRIKE_OFFSETS = [
  { value: 'ATM', label: 'ATM', description: 'At The Money' },
  { value: 'ITM1', label: 'ITM1', description: '1 strike In The Money' },
  { value: 'ITM2', label: 'ITM2', description: '2 strikes In The Money' },
  { value: 'ITM3', label: 'ITM3', description: '3 strikes In The Money' },
  { value: 'ITM4', label: 'ITM4', description: '4 strikes In The Money' },
  { value: 'ITM5', label: 'ITM5', description: '5 strikes In The Money' },
  { value: 'OTM1', label: 'OTM1', description: '1 strike Out of The Money' },
  { value: 'OTM2', label: 'OTM2', description: '2 strikes Out of The Money' },
  { value: 'OTM3', label: 'OTM3', description: '3 strikes Out of The Money' },
  { value: 'OTM4', label: 'OTM4', description: '4 strikes Out of The Money' },
  { value: 'OTM5', label: 'OTM5', description: '5 strikes Out of The Money' },
  { value: 'OTM6', label: 'OTM6', description: '6 strikes Out of The Money' },
  { value: 'OTM7', label: 'OTM7', description: '7 strikes Out of The Money' },
  { value: 'OTM8', label: 'OTM8', description: '8 strikes Out of The Money' },
  { value: 'OTM9', label: 'OTM9', description: '9 strikes Out of The Money' },
  { value: 'OTM10', label: 'OTM10', description: '10 strikes Out of The Money' },
] as const

export const OPTION_STRATEGIES = [
  {
    value: 'iron_condor',
    label: 'Iron Condor',
    description: 'Sell OTM Call & Put, Buy further OTM Call & Put',
  },
  { value: 'straddle', label: 'Straddle', description: 'Buy/Sell ATM Call and Put' },
  { value: 'strangle', label: 'Strangle', description: 'Buy/Sell OTM Call and Put' },
  {
    value: 'bull_call_spread',
    label: 'Bull Call Spread',
    description: 'Buy lower strike Call, Sell higher strike Call',
  },
  {
    value: 'bear_put_spread',
    label: 'Bear Put Spread',
    description: 'Buy higher strike Put, Sell lower strike Put',
  },
  { value: 'custom', label: 'Custom', description: 'Build custom multi-leg strategy' },
] as const

// =============================================================================
// INDEX SYMBOLS
// =============================================================================

export const NSE_INDEX_SYMBOLS = [
  { value: 'NIFTY', label: 'NIFTY 50' },
  { value: 'BANKNIFTY', label: 'Bank NIFTY' },
  { value: 'FINNIFTY', label: 'Fin NIFTY' },
  { value: 'MIDCPNIFTY', label: 'Midcap NIFTY' },
  { value: 'NIFTYNXT50', label: 'NIFTY Next 50' },
] as const

export const BSE_INDEX_SYMBOLS = [
  { value: 'SENSEX', label: 'SENSEX' },
  { value: 'BANKEX', label: 'BANKEX' },
  { value: 'SENSEX50', label: 'SENSEX 50' },
] as const

// Combined index symbols with exchange info (for options trading)
// Lot sizes are fetched dynamically from master contract database
export const INDEX_SYMBOLS = [
  // NSE Indices
  { value: 'NIFTY', label: 'NIFTY', exchange: 'NFO' },
  { value: 'BANKNIFTY', label: 'BANKNIFTY', exchange: 'NFO' },
  { value: 'FINNIFTY', label: 'FINNIFTY', exchange: 'NFO' },
  { value: 'MIDCPNIFTY', label: 'MIDCPNIFTY', exchange: 'NFO' },
  { value: 'NIFTYNXT50', label: 'NIFTYNXT50', exchange: 'NFO' },
  // BSE Indices
  { value: 'SENSEX', label: 'SENSEX', exchange: 'BFO' },
  { value: 'BANKEX', label: 'BANKEX', exchange: 'BFO' },
  { value: 'SENSEX50', label: 'SENSEX50', exchange: 'BFO' },
] as const

// =============================================================================
// EXPIRY TYPES
// =============================================================================

export const EXPIRY_TYPES = [
  { value: 'current_week', label: 'Current Week', description: 'Nearest weekly expiry' },
  { value: 'next_week', label: 'Next Week', description: 'Second weekly expiry' },
  { value: 'current_month', label: 'Current Month', description: 'Last expiry of current month' },
  { value: 'next_month', label: 'Next Month', description: 'Last expiry of next month' },
] as const

// =============================================================================
// SCHEDULE CONSTANTS
// =============================================================================

export const SCHEDULE_TYPES = [
  { value: 'once', label: 'Once', description: 'Execute one time at specified date/time' },
  { value: 'daily', label: 'Daily', description: 'Execute every day at specified time' },
  { value: 'weekly', label: 'Weekly', description: 'Execute on selected days of the week' },
  { value: 'interval', label: 'Interval', description: 'Execute every X minutes' },
] as const

export const DAYS_OF_WEEK = [
  { value: 0, label: 'Mon', fullLabel: 'Monday' },
  { value: 1, label: 'Tue', fullLabel: 'Tuesday' },
  { value: 2, label: 'Wed', fullLabel: 'Wednesday' },
  { value: 3, label: 'Thu', fullLabel: 'Thursday' },
  { value: 4, label: 'Fri', fullLabel: 'Friday' },
  { value: 5, label: 'Sat', fullLabel: 'Saturday' },
  { value: 6, label: 'Sun', fullLabel: 'Sunday' },
] as const

// =============================================================================
// CONDITION OPERATORS
// =============================================================================

export const CONDITION_OPERATORS = [
  { value: '>', label: '>', description: 'Greater than' },
  { value: '<', label: '<', description: 'Less than' },
  { value: '==', label: '=', description: 'Equal to' },
  { value: '>=', label: '>=', description: 'Greater than or equal' },
  { value: '<=', label: '<=', description: 'Less than or equal' },
  { value: '!=', label: '!=', description: 'Not equal to' },
] as const

export const PRICE_ALERT_CONDITIONS = [
  { value: 'above', label: 'Price Above', description: 'Trigger when price goes above' },
  { value: 'below', label: 'Price Below', description: 'Trigger when price goes below' },
  { value: 'crosses_above', label: 'Crosses Above', description: 'Trigger when price crosses above' },
  { value: 'crosses_below', label: 'Crosses Below', description: 'Trigger when price crosses below' },
] as const

export const POSITION_CONDITIONS = [
  { value: 'exists', label: 'Position Exists', description: 'Has an open position' },
  { value: 'not_exists', label: 'No Position', description: 'No open position' },
  { value: 'quantity_above', label: 'Qty Above', description: 'Position quantity above threshold' },
  { value: 'quantity_below', label: 'Qty Below', description: 'Position quantity below threshold' },
  { value: 'pnl_above', label: 'P&L Above', description: 'Position P&L above threshold' },
  { value: 'pnl_below', label: 'P&L Below', description: 'Position P&L below threshold' },
] as const

export const GREEKS = [
  { value: 'delta', label: 'Delta', description: 'Price sensitivity' },
  { value: 'gamma', label: 'Gamma', description: 'Delta sensitivity' },
  { value: 'theta', label: 'Theta', description: 'Time decay' },
  { value: 'vega', label: 'Vega', description: 'Volatility sensitivity' },
  { value: 'iv', label: 'IV', description: 'Implied Volatility' },
] as const

// =============================================================================
// NODE CATEGORIES & DEFINITIONS
// =============================================================================

export const NODE_CATEGORIES = {
  TRIGGERS: 'triggers',
  ACTIONS: 'actions',
  CONDITIONS: 'conditions',
  DATA: 'data',
  UTILITIES: 'utilities',
} as const

export const NODE_DEFINITIONS = {
  // Trigger Nodes
  TRIGGERS: [
    {
      type: 'start',
      label: 'Schedule',
      description: 'Start workflow on schedule',
      category: 'trigger' as const,
    },
    {
      type: 'priceAlert',
      label: 'Price Alert',
      description: 'Trigger on price condition',
      category: 'trigger' as const,
    },
    {
      type: 'webhookTrigger',
      label: 'Webhook',
      description: 'Trigger from external webhook',
      category: 'trigger' as const,
    },
  ],

  // Action Nodes
  ACTIONS: [
    {
      type: 'placeOrder',
      label: 'Place Order',
      description: 'Place a trading order',
      category: 'action' as const,
    },
    {
      type: 'smartOrder',
      label: 'Smart Order',
      description: 'Position-aware order',
      category: 'action' as const,
    },
    {
      type: 'optionsOrder',
      label: 'Options Order',
      description: 'Trade ATM/ITM/OTM options',
      category: 'action' as const,
    },
    {
      type: 'optionsMultiOrder',
      label: 'Options Strategy',
      description: 'Multi-leg options strategy',
      category: 'action' as const,
    },
    {
      type: 'basketOrder',
      label: 'Basket Order',
      description: 'Place multiple orders at once',
      category: 'action' as const,
    },
    {
      type: 'splitOrder',
      label: 'Split Order',
      description: 'Split large order into chunks',
      category: 'action' as const,
    },
    {
      type: 'modifyOrder',
      label: 'Modify Order',
      description: 'Modify an existing order',
      category: 'action' as const,
    },
    {
      type: 'cancelOrder',
      label: 'Cancel Order',
      description: 'Cancel a specific order',
      category: 'action' as const,
    },
    {
      type: 'cancelAllOrders',
      label: 'Cancel All',
      description: 'Cancel all open orders',
      category: 'action' as const,
    },
    {
      type: 'closePositions',
      label: 'Close Positions',
      description: 'Square off all positions',
      category: 'action' as const,
    },
  ],

  // Condition Nodes
  CONDITIONS: [
    {
      type: 'positionCheck',
      label: 'Position Check',
      description: 'Check position status',
      category: 'condition' as const,
    },
    {
      type: 'fundCheck',
      label: 'Fund Check',
      description: 'Check available funds',
      category: 'condition' as const,
    },
    {
      type: 'priceCondition',
      label: 'Price Check',
      description: 'Check price condition',
      category: 'condition' as const,
    },
    {
      type: 'timeWindow',
      label: 'Time Window',
      description: 'Check market hours',
      category: 'condition' as const,
    },
    {
      type: 'timeCondition',
      label: 'Time Condition',
      description: 'Check time condition',
      category: 'condition' as const,
    },
    {
      type: 'andGate',
      label: 'AND Gate',
      description: 'All conditions must be true',
      category: 'condition' as const,
    },
    {
      type: 'orGate',
      label: 'OR Gate',
      description: 'Any condition must be true',
      category: 'condition' as const,
    },
    {
      type: 'notGate',
      label: 'NOT Gate',
      description: 'Invert condition result',
      category: 'condition' as const,
    },
  ],

  // Data Nodes
  DATA: [
    {
      type: 'getQuote',
      label: 'Get Quote',
      description: 'Fetch real-time quote',
      category: 'data' as const,
    },
    {
      type: 'getDepth',
      label: 'Market Depth',
      description: 'Fetch bid/ask depth',
      category: 'data' as const,
    },
    {
      type: 'history',
      label: 'History',
      description: 'Fetch OHLCV data',
      category: 'data' as const,
    },
    {
      type: 'openPosition',
      label: 'Open Position',
      description: 'Get position for symbol',
      category: 'data' as const,
    },
    {
      type: 'orderBook',
      label: 'Order Book',
      description: 'Get all orders',
      category: 'data' as const,
    },
    {
      type: 'tradeBook',
      label: 'Trade Book',
      description: 'Get all trades',
      category: 'data' as const,
    },
    {
      type: 'positionBook',
      label: 'Position Book',
      description: 'Get all positions',
      category: 'data' as const,
    },
    {
      type: 'holdings',
      label: 'Holdings',
      description: 'Get portfolio holdings',
      category: 'data' as const,
    },
    {
      type: 'funds',
      label: 'Funds',
      description: 'Get available funds',
      category: 'data' as const,
    },
  ],

  // Utility Nodes
  UTILITIES: [
    {
      type: 'telegramAlert',
      label: 'Telegram Alert',
      description: 'Send Telegram notification',
      category: 'utility' as const,
    },
    {
      type: 'delay',
      label: 'Delay',
      description: 'Wait for duration',
      category: 'utility' as const,
    },
    {
      type: 'waitUntil',
      label: 'Wait Until',
      description: 'Wait until specific time',
      category: 'utility' as const,
    },
    {
      type: 'log',
      label: 'Log',
      description: 'Log a message',
      category: 'utility' as const,
    },
    {
      type: 'variable',
      label: 'Variable',
      description: 'Set/calculate variable',
      category: 'utility' as const,
    },
    {
      type: 'httpRequest',
      label: 'HTTP Request',
      description: 'Make HTTP request',
      category: 'utility' as const,
    },
  ],
} as const

// =============================================================================
// DEFAULT NODE DATA
// =============================================================================

export const DEFAULT_NODE_DATA = {
  start: {
    scheduleType: 'daily' as const,
    time: '09:15',
    marketHoursOnly: true,
  },
  priceAlert: {
    symbol: '',
    exchange: 'NSE',
    condition: 'above' as const,
    price: 0,
  },
  webhookTrigger: {
    label: '',
    symbol: '',
    exchange: 'NSE',
  },
  placeOrder: {
    symbol: '',
    exchange: 'NSE',
    action: 'BUY' as const,
    quantity: 1,
    priceType: 'MARKET' as const,
    product: 'MIS' as const,
  },
  smartOrder: {
    symbol: '',
    exchange: 'NSE',
    action: 'BUY' as const,
    quantity: 1,
    positionSize: 0,
    priceType: 'MARKET' as const,
    product: 'MIS' as const,
  },
  optionsOrder: {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX' as const,
    expiryDate: '',
    offset: 'ATM',
    optionType: 'CE' as const,
    action: 'BUY' as const,
    quantity: 1,
    priceType: 'MARKET' as const,
    product: 'MIS' as const,
  },
  optionsMultiOrder: {
    strategy: 'straddle' as const,
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX' as const,
    expiryDate: '',
    legs: [],
    priceType: 'MARKET' as const,
    product: 'MIS' as const,
  },
  cancelOrder: {
    orderId: '',
  },
  cancelAllOrders: {},
  closePositions: {
    symbol: '',
    exchange: 'NSE',
    product: 'MIS' as const,
  },
  modifyOrder: {
    orderId: '',
    symbol: '',
    exchange: 'NSE',
    action: 'BUY' as const,
  },
  basketOrder: {
    orders: '',
    product: 'MIS' as const,
    priceType: 'MARKET' as const,
  },
  splitOrder: {
    symbol: '',
    exchange: 'NSE',
    action: 'BUY' as const,
    quantity: 100,
    splitSize: 50,
    priceType: 'MARKET' as const,
    product: 'MIS' as const,
  },
  positionCheck: {
    symbol: '',
    exchange: 'NSE',
    product: 'MIS' as const,
    operator: 'gt' as const,
    threshold: 0,
  },
  fundCheck: {
    operator: 'gt' as const,
    threshold: 10000,
  },
  priceCondition: {
    symbol: '',
    exchange: 'NSE',
    operator: 'gt' as const,
    threshold: 0,
  },
  timeWindow: {
    startTime: '09:15',
    endTime: '15:30',
  },
  timeCondition: {
    targetTime: '09:30',
    operator: '>=' as const,
  },
  andGate: {},
  orGate: {},
  notGate: {},
  getQuote: {
    symbol: '',
    exchange: 'NSE',
    outputVariable: '',
  },
  getDepth: {
    symbol: '',
    exchange: 'NSE',
    outputVariable: '',
  },
  history: {
    symbol: '',
    exchange: 'NSE',
    interval: '5m' as const,
    startDate: '',
    endDate: '',
    outputVariable: '',
  },
  openPosition: {
    symbol: '',
    exchange: 'NSE',
    product: 'MIS' as const,
    outputVariable: '',
  },
  orderBook: {
    outputVariable: '',
  },
  tradeBook: {
    outputVariable: '',
  },
  positionBook: {
    outputVariable: '',
  },
  holdings: {
    outputVariable: '',
  },
  funds: {
    outputVariable: '',
  },
  telegramAlert: {
    message: 'Workflow executed successfully',
  },
  delay: {
    delayValue: 1,
    delayUnit: 'seconds' as const,
  },
  waitUntil: {
    targetTime: '09:30',
  },
  log: {
    message: 'Log message here',
    level: 'info' as const,
  },
  variable: {
    variableName: 'myVar',
    operation: 'set' as const,
    value: '',
  },
  httpRequest: {
    method: 'GET' as const,
    url: '',
    headers: {},
    body: '',
    timeout: 30,
    outputVariable: '',
  },
  symbol: {
    symbol: '',
    exchange: 'NSE',
    outputVariable: '',
  },
  optionSymbol: {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX' as const,
    expiryDate: '',
    offset: 'ATM',
    optionType: 'CE' as const,
    outputVariable: '',
  },
  expiry: {
    symbol: 'NIFTY',
    exchange: 'NFO',
    outputVariable: '',
  },
  intervals: {
    outputVariable: '',
  },
  multiQuotes: {
    symbols: '',
    exchange: 'NSE',
    outputVariable: '',
  },
  optionChain: {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX' as const,
    expiryDate: '',
    strikeCount: 10,
    outputVariable: '',
  },
  syntheticFuture: {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX' as const,
    expiryDate: '',
    outputVariable: '',
  },
  holidays: {
    exchange: 'NSE',
    outputVariable: '',
  },
  timings: {
    exchange: 'NSE',
    outputVariable: '',
  },
  mathExpression: {
    expression: '',
    outputVariable: 'result',
  },
  margin: {
    symbol: '',
    exchange: 'NSE',
    quantity: 1,
    price: 0,
    product: 'MIS' as const,
    action: 'BUY' as const,
    priceType: 'MARKET' as const,
    outputVariable: '',
  },
  group: {},
} as const

// =============================================================================
// Type Exports
// =============================================================================

export type Exchange = (typeof EXCHANGES)[number]['value']
export type ProductType = (typeof PRODUCT_TYPES)[number]['value']
export type PriceType = (typeof PRICE_TYPES)[number]['value']
export type OrderAction = (typeof ORDER_ACTIONS)[number]['value']
export type OptionType = (typeof OPTION_TYPES)[number]['value']
export type ScheduleType = (typeof SCHEDULE_TYPES)[number]['value']
export type NodeCategory = (typeof NODE_CATEGORIES)[keyof typeof NODE_CATEGORIES]
