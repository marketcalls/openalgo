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
  { value: 'NCDEX', label: 'NCDEX' },
  { value: 'NCO', label: 'NCO' },
  { value: 'NSE_INDEX', label: 'NSE_INDEX' },
  { value: 'BSE_INDEX', label: 'BSE_INDEX' },
  { value: 'MCX_INDEX', label: 'MCX_INDEX' },
  { value: 'GLOBAL_INDEX', label: 'GLOBAL_INDEX' },
  { value: 'CRYPTO', label: 'CRYPTO' },
] as const

export const INDEX_EXCHANGES = [
  { value: 'NSE_INDEX', label: 'NSE_INDEX' },
  { value: 'BSE_INDEX', label: 'BSE_INDEX' },
  { value: 'MCX_INDEX', label: 'MCX_INDEX' },
  { value: 'GLOBAL_INDEX', label: 'GLOBAL_INDEX' },
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
  {
    value: 'crosses_above',
    label: 'Crosses Above',
    description: 'Trigger when price crosses above',
  },
  {
    value: 'crosses_below',
    label: 'Crosses Below',
    description: 'Trigger when price crosses below',
  },
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

// Every openalgo.ta function the Indicator node's backend
// (services/indicator_service.py:list_supported_indicators) can run.
// Keep this list in sync with that function - it is generated from the
// real `ta` module signatures, not hand-maintained, so re-derive it the
// same way if the pinned `openalgo` SDK version changes.
export const INDICATOR_CATEGORIES = [
  'Trend',
  'Momentum',
  'Volatility',
  'Volume',
  'Oscillators',
  'Statistical',
  'Hybrid',
  'Price Transform',
  'Utility',
] as const

export const INDICATOR_CATALOG = [
  { value: 'alligator', label: 'Alligator', category: 'Trend' },
  { value: 'alma', label: 'ALMA', category: 'Trend' },
  { value: 'ckstop', label: 'Ckstop', category: 'Trend' },
  { value: 'dema', label: 'DEMA', category: 'Trend' },
  { value: 'ema', label: 'EMA', category: 'Trend' },
  { value: 'frama', label: 'FRAMA', category: 'Trend' },
  { value: 'hma', label: 'HMA', category: 'Trend' },
  { value: 'ichimoku', label: 'Ichimoku', category: 'Trend' },
  { value: 'kama', label: 'KAMA', category: 'Trend' },
  { value: 'ma_envelopes', label: 'Ma Envelopes', category: 'Trend' },
  { value: 'mcginley', label: 'Mcginley', category: 'Trend' },
  { value: 'sma', label: 'SMA', category: 'Trend' },
  { value: 'supertrend', label: 'Supertrend', category: 'Trend' },
  { value: 't3', label: 'T3', category: 'Trend' },
  { value: 'tema', label: 'TEMA', category: 'Trend' },
  { value: 'trima', label: 'TRIMA', category: 'Trend' },
  { value: 'vidya', label: 'VIDYA', category: 'Trend' },
  { value: 'vwma', label: 'VWMA', category: 'Trend' },
  { value: 'wma', label: 'WMA', category: 'Trend' },
  { value: 'zlema', label: 'ZLEMA', category: 'Trend' },
  { value: 'apo', label: 'APO', category: 'Momentum' },
  { value: 'bop', label: 'BOP', category: 'Momentum' },
  { value: 'cci', label: 'CCI', category: 'Momentum' },
  { value: 'cmo', label: 'CMO', category: 'Momentum' },
  { value: 'crsi', label: 'CRSI', category: 'Momentum' },
  { value: 'dpo', label: 'DPO', category: 'Momentum' },
  { value: 'elderray', label: 'Elderray', category: 'Momentum' },
  { value: 'fisher', label: 'Fisher', category: 'Momentum' },
  { value: 'macd', label: 'MACD', category: 'Momentum' },
  { value: 'mom', label: 'MOM', category: 'Momentum' },
  { value: 'po', label: 'PO', category: 'Momentum' },
  { value: 'ppo', label: 'PPO', category: 'Momentum' },
  { value: 'rsi', label: 'RSI', category: 'Momentum' },
  { value: 'stochastic', label: 'Stochastic', category: 'Momentum' },
  { value: 'stochf', label: 'Stochf', category: 'Momentum' },
  { value: 'stochrsi', label: 'Stochrsi', category: 'Momentum' },
  { value: 'trix', label: 'TRIX', category: 'Momentum' },
  { value: 'williams_r', label: 'Williams R', category: 'Momentum' },
  { value: 'atr', label: 'ATR', category: 'Volatility' },
  { value: 'bbands', label: 'Bbands', category: 'Volatility' },
  { value: 'bbpercent', label: 'Bbpercent', category: 'Volatility' },
  { value: 'bbwidth', label: 'Bbwidth', category: 'Volatility' },
  { value: 'chaikin', label: 'Chaikin', category: 'Volatility' },
  { value: 'chandelier_exit', label: 'Chandelier Exit', category: 'Volatility' },
  { value: 'donchian', label: 'Donchian', category: 'Volatility' },
  { value: 'hv', label: 'HV', category: 'Volatility' },
  { value: 'keltner', label: 'Keltner', category: 'Volatility' },
  { value: 'massindex', label: 'Massindex', category: 'Volatility' },
  { value: 'natr', label: 'NATR', category: 'Volatility' },
  { value: 'rvi', label: 'RVI', category: 'Volatility' },
  { value: 'starc', label: 'STARC', category: 'Volatility' },
  { value: 'true_range', label: 'True Range', category: 'Volatility' },
  { value: 'ultimate_oscillator', label: 'Ultimate Oscillator', category: 'Volatility' },
  { value: 'uo_oscillator', label: 'Uo Oscillator', category: 'Volatility' },
  { value: 'adl', label: 'ADL', category: 'Volume' },
  { value: 'cmf', label: 'CMF', category: 'Volume' },
  { value: 'emv', label: 'EMV', category: 'Volume' },
  { value: 'force_index', label: 'Force Index', category: 'Volume' },
  { value: 'kvo', label: 'KVO', category: 'Volume' },
  { value: 'mfi', label: 'MFI', category: 'Volume' },
  { value: 'nvi', label: 'NVI', category: 'Volume' },
  { value: 'nvi_with_ema', label: 'Nvi With Ema', category: 'Volume' },
  { value: 'obv', label: 'OBV', category: 'Volume' },
  { value: 'obv_smoothed', label: 'Obv Smoothed', category: 'Volume' },
  { value: 'pvi', label: 'PVI', category: 'Volume' },
  { value: 'pvi_with_signal', label: 'Pvi With Signal', category: 'Volume' },
  { value: 'pvt', label: 'PVT', category: 'Volume' },
  { value: 'rvol', label: 'RVOL', category: 'Volume' },
  { value: 'volosc', label: 'Volosc', category: 'Volume' },
  { value: 'vroc', label: 'VROC', category: 'Volume' },
  { value: 'vwap', label: 'VWAP', category: 'Volume' },
  { value: 'accelerator_oscillator', label: 'Accelerator Oscillator', category: 'Oscillators' },
  { value: 'aroon_oscillator', label: 'Aroon Oscillator', category: 'Oscillators' },
  { value: 'awesome_oscillator', label: 'Awesome Oscillator', category: 'Oscillators' },
  { value: 'cho', label: 'CHO', category: 'Oscillators' },
  { value: 'chop', label: 'CHOP', category: 'Oscillators' },
  { value: 'coppock', label: 'Coppock', category: 'Oscillators' },
  { value: 'gator_oscillator', label: 'Gator Oscillator', category: 'Oscillators' },
  { value: 'kst', label: 'KST', category: 'Oscillators' },
  { value: 'roc', label: 'ROC', category: 'Oscillators' },
  { value: 'rocp', label: 'ROCP', category: 'Oscillators' },
  { value: 'rocr', label: 'ROCR', category: 'Oscillators' },
  { value: 'rocr100', label: 'Rocr100', category: 'Oscillators' },
  { value: 'stc', label: 'STC', category: 'Oscillators' },
  { value: 'tsi', label: 'TSI', category: 'Oscillators' },
  { value: 'linreg', label: 'Linreg', category: 'Statistical' },
  { value: 'linregangle', label: 'Linregangle', category: 'Statistical' },
  { value: 'linregintercept', label: 'Linregintercept', category: 'Statistical' },
  { value: 'lrslope', label: 'Lrslope', category: 'Statistical' },
  { value: 'median', label: 'Median', category: 'Statistical' },
  { value: 'mode', label: 'MODE', category: 'Statistical' },
  { value: 'tsf', label: 'TSF', category: 'Statistical' },
  { value: 'variance', label: 'Variance', category: 'Statistical' },
  { value: 'adx', label: 'ADX', category: 'Hybrid' },
  { value: 'adxr', label: 'ADXR', category: 'Hybrid' },
  { value: 'aroon', label: 'AROON', category: 'Hybrid' },
  { value: 'dmi', label: 'DMI', category: 'Hybrid' },
  { value: 'dx', label: 'DX', category: 'Hybrid' },
  { value: 'fractals', label: 'Fractals', category: 'Hybrid' },
  { value: 'minus_dm', label: 'Minus Dm', category: 'Hybrid' },
  { value: 'pivot_points', label: 'Pivot Points', category: 'Hybrid' },
  { value: 'plus_dm', label: 'Plus Dm', category: 'Hybrid' },
  { value: 'psar', label: 'PSAR', category: 'Hybrid' },
  { value: 'rwi', label: 'RWI', category: 'Hybrid' },
  { value: 'avgprice', label: 'Avgprice', category: 'Price Transform' },
  { value: 'medprice', label: 'Medprice', category: 'Price Transform' },
  { value: 'midpoint', label: 'Midpoint', category: 'Price Transform' },
  { value: 'midprice', label: 'Midprice', category: 'Price Transform' },
  { value: 'typprice', label: 'Typprice', category: 'Price Transform' },
  { value: 'wclprice', label: 'Wclprice', category: 'Price Transform' },
  { value: 'change', label: 'Change', category: 'Utility' },
  { value: 'falling', label: 'Falling', category: 'Utility' },
  { value: 'highest', label: 'Highest', category: 'Utility' },
  { value: 'lowest', label: 'Lowest', category: 'Utility' },
  { value: 'rising', label: 'Rising', category: 'Utility' },
  { value: 'stdev', label: 'STDEV', category: 'Utility' },
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
    {
      type: 'orderUpdateTrigger',
      label: 'Order Update',
      description: 'Trigger on order status change',
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
    {
      type: 'varCondition',
      label: 'Var Condition',
      description: 'Compare any two values',
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
      type: 'indicator',
      label: 'Indicator',
      description: 'Run any technical indicator',
      category: 'data' as const,
    },
    {
      type: 'strategyPnl',
      label: 'Strategy P&L',
      description: 'Realized/unrealized P&L for a strategy',
      category: 'data' as const,
    },
    {
      type: 'priorPeriodOhlc',
      label: 'Prior Period OHLC',
      description: 'Previous hour/day/week/month candle',
      category: 'data' as const,
    },
    {
      type: 'barOffset',
      label: 'Bar Offset',
      description: 'OHLCV N bars back',
      category: 'data' as const,
    },
    {
      type: 'openPosition',
      label: 'Open Position',
      description: 'Get position for symbol',
      category: 'data' as const,
    },
    {
      type: 'getOrderStatus',
      label: 'Order Status',
      description: 'Check order status',
      category: 'data' as const,
    },
    {
      type: 'expiry',
      label: 'Expiry Dates',
      description: 'F&O expiry dates',
      category: 'data' as const,
    },
    {
      type: 'intervals',
      label: 'Intervals',
      description: 'Broker-supported timeframes',
      category: 'data' as const,
    },
    {
      type: 'multiQuotes',
      label: 'Multi Quotes',
      description: 'Quotes for several symbols',
      category: 'data' as const,
    },
    {
      type: 'symbol',
      label: 'Symbol Info',
      description: 'Lot size, tick size, token',
      category: 'data' as const,
    },
    {
      type: 'optionSymbol',
      label: 'Option Symbol',
      description: 'Resolve an ATM-relative strike',
      category: 'data' as const,
    },
    {
      type: 'syntheticFuture',
      label: 'Synthetic Future',
      description: 'Synthetic future price',
      category: 'data' as const,
    },
    {
      type: 'optionChain',
      label: 'Option Chain',
      description: 'Strikes with CE and PE',
      category: 'data' as const,
    },
    {
      type: 'margin',
      label: 'Margin',
      description: 'Margin required for a position or basket',
      category: 'data' as const,
    },
    {
      type: 'holidays',
      label: 'Holidays',
      description: 'Exchange holiday list for a year',
      category: 'data' as const,
    },
    {
      type: 'timings',
      label: 'Market Timings',
      description: 'Market open and close for a date',
      category: 'data' as const,
    },
    {
      type: 'calendar',
      label: 'Calendar',
      description: 'New day, week, month or quarter',
      category: 'data' as const,
    },
    {
      type: 'subscribeLtp',
      label: 'Subscribe LTP',
      description: 'Stream last traded price',
      category: 'streaming' as const,
    },
    {
      type: 'subscribeQuote',
      label: 'Subscribe Quote',
      description: 'Stream full quote',
      category: 'streaming' as const,
    },
    {
      type: 'subscribeDepth',
      label: 'Subscribe Depth',
      description: 'Stream market depth',
      category: 'streaming' as const,
    },
    {
      type: 'unsubscribe',
      label: 'Unsubscribe',
      description: 'Stop a stream',
      category: 'streaming' as const,
    },
    {
      type: 'mathExpression',
      label: 'Math Expression',
      description: 'Arithmetic over variables',
      category: 'utility' as const,
    },
    {
      type: 'group',
      label: 'Group',
      description: 'Visual grouping only',
      category: 'utility' as const,
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
      type: 'whatsappAlert',
      label: 'WhatsApp Alert',
      description: 'Send WhatsApp notification',
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
    // Both are honored at activation; defaults match the panel's own.
    trigger: 'once' as const,
    expiration: 'none' as const,
  },
  orderUpdateTrigger: {
    orderId: '',
    symbol: '',
    // Empty, not 'NSE': the UI presents this filter as optional, so defaulting
    // it to a real exchange would silently stop an order-ID-only watch from
    // matching fills on any other segment (NFO, MCX, ...).
    exchange: '',
    status: 'complete' as const,
    trigger: 'once' as const,
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
    price: 0,
    triggerPrice: 0,
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
  getOrderStatus: {
    orderId: '',
    waitForCompletion: false,
    outputVariable: 'orderStatus',
  },
  subscribeLtp: {
    symbol: '',
    exchange: 'NSE' as const,
    outputVariable: 'ltp',
  },
  subscribeQuote: {
    symbol: '',
    exchange: 'NSE' as const,
    outputVariable: 'quote',
  },
  subscribeDepth: {
    symbol: '',
    exchange: 'NSE' as const,
    outputVariable: 'depth',
  },
  unsubscribe: {
    symbol: '',
    exchange: 'NSE' as const,
    streamType: 'all' as const,
  },
  optionsOrder: {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX' as const,
    expiryType: 'current_week' as const,
    offset: 'ATM',
    optionType: 'CE' as const,
    action: 'BUY' as const,
    quantity: 1,
    priceType: 'MARKET' as const,
    product: 'MIS' as const,
    price: 0,
    triggerPrice: 0,
  },
  optionsMultiOrder: {
    strategy: 'straddle' as const,
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX' as const,
    // The executor resolves an expiry *type*; expiryDate was never read here.
    expiryType: 'current_week' as const,
    legs: [],
    action: 'SELL' as const,
    quantity: 1,
    strangleWidth: 'OTM2' as const,
    priceType: 'MARKET' as const,
    price: 0,
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
    condition: 'exists' as const,
    threshold: 0,
  },
  fundCheck: {
    // The executor reads minAvailable. Shipping operator/threshold left a new
    // node with no minAvailable at all, so the guard defaulted to 0 and passed
    // on any balance - a fund check that never checked.
    minAvailable: 10000,
  },
  priceCondition: {
    symbol: '',
    exchange: 'NSE',
    field: 'ltp' as const,
    operator: '>' as const,
    value: 0,
  },
  varCondition: {
    leftValue: '',
    operator: '>' as const,
    rightValue: '0',
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
    // The panel exposes Days; startDate/endDate stay available for an explicit
    // range and take precedence when both are set.
    days: 30,
    startDate: '',
    endDate: '',
    outputVariable: '',
  },
  indicator: {
    symbol: '',
    exchange: 'NSE',
    interval: 'D',
    source: 'api' as const,
    indicatorName: 'rsi',
    params: '{"period": 14}',
    lookbackBars: 100,
    tailBars: 5,
    offsetBars: 0,
    sourceSeries: '',
    sourceField: '',
    outputVariable: '',
  },
  strategyPnl: {
    strategy: '',
    outputVariable: '',
  },
  priorPeriodOhlc: {
    symbol: '',
    exchange: 'NSE',
    period: 'previous_day' as const,
    source: 'api' as const,
    outputVariable: '',
  },
  barOffset: {
    symbol: '',
    exchange: 'NSE',
    interval: 'D',
    source: 'api' as const,
    offsetBars: 0,
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
  whatsappAlert: {
    to: '',
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
    // Persisted, not just shown: an empty default meant the panel displayed
    // "intervals" while the node stored its result nowhere.
    outputVariable: 'intervals',
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
    // The calendar service takes a year, not an exchange. Blank = current year.
    year: undefined as number | undefined,
    outputVariable: '',
  },
  timings: {
    // The calendar service takes a date (YYYY-MM-DD). Blank = today.
    date: '',
    outputVariable: '',
  },
  calendar: {
    // Blank = the current trading session date.
    date: '',
    outputVariable: 'cal',
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
