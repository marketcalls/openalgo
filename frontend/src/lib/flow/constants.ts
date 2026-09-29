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

/**
 * Segments that trade contracts carried on margin rather than cash-settled
 * holdings. A position in one of these is normally taken NRML, so that is what
 * a node defaults to when its author never picked a product. Index
 * pseudo-exchanges are absent because no order is ever placed on them.
 *
 * The backend keeps the same rule in services/flow_node_contracts.py; both
 * sides must agree or the panel would promise a product the run does not send.
 */
export const DERIVATIVE_EXCHANGES = new Set<string>([
  'NFO',
  'BFO',
  'CDS',
  'BCD',
  'MCX',
  'NCDEX',
  'NCO',
])

/**
 * The product a node on `exchange` uses when its author picked none.
 *
 * A *default*, never an override: once a product is chosen it is stored on the
 * node and wins, so a deliberately intraday NFO order stays MIS.
 */
export function defaultProductForExchange(exchange: string | undefined | null): 'MIS' | 'NRML' {
  return DERIVATIVE_EXCHANGES.has((exchange || '').trim().toUpperCase()) ? 'NRML' : 'MIS'
}

/** Options nodes trade an option whatever their underlying's exchange reads. */
export const OPTION_NODE_PRODUCT = 'NRML' as const

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

/**
 * How far out the offset dropdowns count, in either direction.
 *
 * Matched to OPTION_STRIKE_WINDOW in blueprints/flow.py, which is the number
 * of strikes either side of ATM the chain endpoint returns. The two controls
 * sit next to each other on the same leg - pick "Offset" or pick "Strike" -
 * and offering an offset further out than the strike picker will show you is
 * offering a contract this panel cannot then confirm exists.
 *
 * Deliberately narrower than the executor's own limit, which is ITM1-ITM50 and
 * OTM1-OTM50 (OPTION_OFFSET_PATTERN in services/flow_node_contracts.py,
 * mirrored by OFFSET_PATTERN in ./customLegs.ts). A leg already storing
 * something beyond this window is still valid and still runs; strikeOffsetOptions
 * keeps it selectable rather than blanking the control. The dropdowns used to
 * stop at ITM5 and OTM10 with no such fallback, which is how an imported OTM12
 * leg rendered empty and lost its strike to the next value picked.
 */
export const MAX_STRIKE_OFFSET = 25

const strikeOffset = (kind: 'ITM' | 'OTM', n: number) => ({
  value: `${kind}${n}`,
  label: `${kind}${n}`,
  description: `${n} ${n === 1 ? 'strike' : 'strikes'} ${
    kind === 'ITM' ? 'In The Money' : 'Out of The Money'
  }`,
})

const strikeOffsetRange = (kind: 'ITM' | 'OTM') =>
  Array.from({ length: MAX_STRIKE_OFFSET }, (_, i) => strikeOffset(kind, i + 1))

export const STRIKE_OFFSETS: ReadonlyArray<{
  value: string
  label: string
  description: string
}> = [
  { value: 'ATM', label: 'ATM', description: 'At The Money' },
  ...strikeOffsetRange('ITM'),
  ...strikeOffsetRange('OTM'),
]

/**
 * The offset list with ``current`` guaranteed to be in it.
 *
 * A stored value the list does not carry renders as an empty control, and the
 * next thing the author picks silently replaces a strike they never chose.
 * That is the same reason the leg editor's expiry keeps an unlisted date
 * selectable. Anything reaches this - a legacy value, a hand-written offset, an
 * offset past the window that the executor still accepts - so it is shown
 * as-is rather than corrected.
 */
export function strikeOffsetOptions(current: unknown) {
  const value = typeof current === 'string' ? current.trim() : ''
  if (!value || STRIKE_OFFSETS.some((offset) => offset.value === value)) return STRIKE_OFFSETS
  return [{ value, label: value, description: 'Stored on this node' }, ...STRIKE_OFFSETS]
}

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
  // MCX commodities. Options trade on MCX itself, so the underlying exchange
  // and the option exchange are the same value.
  { value: 'GOLD', label: 'GOLD', exchange: 'MCX' },
  { value: 'GOLDM', label: 'GOLDM', exchange: 'MCX' },
  { value: 'SILVER', label: 'SILVER', exchange: 'MCX' },
  { value: 'SILVERM', label: 'SILVERM', exchange: 'MCX' },
  { value: 'CRUDEOIL', label: 'CRUDEOIL', exchange: 'MCX' },
  { value: 'CRUDEOILM', label: 'CRUDEOILM', exchange: 'MCX' },
  { value: 'NATURALGAS', label: 'NATURALGAS', exchange: 'MCX' },
  { value: 'NATGASMINI', label: 'NATGASMINI', exchange: 'MCX' },
  { value: 'COPPER', label: 'COPPER', exchange: 'MCX' },
  { value: 'ZINC', label: 'ZINC', exchange: 'MCX' },
  { value: 'MCXBULLDEX', label: 'MCXBULLDEX', exchange: 'MCX' },
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

// Scalar parameters each indicator accepts, so the Indicator node's config
// panel can render real fields instead of asking for hand-written JSON. The
// `name` keys are the exact kwargs services/indicator_service.compute_indicator
// forwards to openalgo.ta, and the defaults are the ta signatures' own (with
// indicator_service._REQUIRED_PARAM_DEFAULTS filling the few params that have
// no signature default). Generated the same way as INDICATOR_CATALOG above -
// re-derive it from the real signatures if the pinned `openalgo` SDK changes,
// do not hand-edit.
export type IndicatorParamType = 'int' | 'float' | 'bool' | 'string'

export interface IndicatorParam {
  name: string
  label: string
  type: IndicatorParamType
  default: number | string | boolean
  choices?: readonly string[]
}

export const INDICATOR_PARAMS: Record<string, readonly IndicatorParam[]> = {
  accelerator_oscillator: [{ name: 'period', label: 'Period', type: 'int', default: 5 }],
  adl: [],
  adx: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  adxr: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  alligator: [
    { name: 'jaw_period', label: 'Jaw Period', type: 'int', default: 13 },
    { name: 'jaw_shift', label: 'Jaw Shift', type: 'int', default: 8 },
    { name: 'teeth_period', label: 'Teeth Period', type: 'int', default: 8 },
    { name: 'teeth_shift', label: 'Teeth Shift', type: 'int', default: 5 },
    { name: 'lips_period', label: 'Lips Period', type: 'int', default: 5 },
    { name: 'lips_shift', label: 'Lips Shift', type: 'int', default: 3 },
  ],
  alma: [
    { name: 'period', label: 'Period', type: 'int', default: 21 },
    { name: 'offset', label: 'Offset', type: 'float', default: 0.85 },
    { name: 'sigma', label: 'Sigma', type: 'float', default: 6.0 },
  ],
  apo: [
    { name: 'fast_period', label: 'Fast Period', type: 'int', default: 12 },
    { name: 'slow_period', label: 'Slow Period', type: 'int', default: 26 },
    { name: 'ma_type', label: 'MA Type', type: 'string', default: 'SMA', choices: ['SMA', 'EMA'] },
  ],
  aroon: [{ name: 'period', label: 'Period', type: 'int', default: 25 }],
  aroon_oscillator: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  atr: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  avgprice: [],
  awesome_oscillator: [
    { name: 'fast_period', label: 'Fast Period', type: 'int', default: 5 },
    { name: 'slow_period', label: 'Slow Period', type: 'int', default: 34 },
  ],
  bbands: [
    { name: 'period', label: 'Period', type: 'int', default: 20 },
    { name: 'std_dev', label: 'Std Dev', type: 'float', default: 2.0 },
  ],
  bbpercent: [
    { name: 'period', label: 'Period', type: 'int', default: 20 },
    { name: 'std_dev', label: 'Std Dev', type: 'float', default: 2.0 },
  ],
  bbwidth: [
    { name: 'period', label: 'Period', type: 'int', default: 20 },
    { name: 'std_dev', label: 'Std Dev', type: 'float', default: 2.0 },
  ],
  bop: [],
  cci: [{ name: 'period', label: 'Period', type: 'int', default: 20 }],
  chaikin: [
    { name: 'ema_period', label: 'EMA Period', type: 'int', default: 10 },
    { name: 'roc_period', label: 'ROC Period', type: 'int', default: 10 },
  ],
  chandelier_exit: [
    { name: 'period', label: 'Period', type: 'int', default: 22 },
    { name: 'multiplier', label: 'Multiplier', type: 'float', default: 3.0 },
  ],
  change: [{ name: 'length', label: 'Length', type: 'int', default: 1 }],
  cho: [
    { name: 'fast_period', label: 'Fast Period', type: 'int', default: 3 },
    { name: 'slow_period', label: 'Slow Period', type: 'int', default: 10 },
  ],
  chop: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  ckstop: [
    { name: 'p', label: 'ATR Length', type: 'int', default: 10 },
    { name: 'x', label: 'ATR Coefficient', type: 'float', default: 1.0 },
    { name: 'q', label: 'Stop Length', type: 'int', default: 9 },
  ],
  cmf: [{ name: 'period', label: 'Period', type: 'int', default: 20 }],
  cmo: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  coppock: [
    { name: 'wma_length', label: 'WMA Length', type: 'int', default: 10 },
    { name: 'long_roc_length', label: 'Long ROC Length', type: 'int', default: 14 },
    { name: 'short_roc_length', label: 'Short ROC Length', type: 'int', default: 11 },
  ],
  crsi: [
    { name: 'lenrsi', label: 'RSI Length', type: 'int', default: 3 },
    { name: 'lenupdown', label: 'Up/Down Length', type: 'int', default: 2 },
    { name: 'lenroc', label: 'ROC Length', type: 'int', default: 100 },
  ],
  dema: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  dmi: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  donchian: [{ name: 'period', label: 'Period', type: 'int', default: 20 }],
  dpo: [
    { name: 'period', label: 'Period', type: 'int', default: 21 },
    { name: 'is_centered', label: 'Is Centered', type: 'bool', default: false },
  ],
  dx: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  elderray: [{ name: 'period', label: 'Period', type: 'int', default: 13 }],
  ema: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  emv: [
    { name: 'length', label: 'Length', type: 'int', default: 14 },
    { name: 'divisor', label: 'Divisor', type: 'int', default: 10000 },
  ],
  falling: [{ name: 'length', label: 'Length', type: 'int', default: 1 }],
  fisher: [{ name: 'length', label: 'Length', type: 'int', default: 9 }],
  force_index: [{ name: 'length', label: 'Length', type: 'int', default: 13 }],
  fractals: [{ name: 'periods', label: 'Periods', type: 'int', default: 2 }],
  frama: [{ name: 'period', label: 'Period', type: 'int', default: 26 }],
  gator_oscillator: [
    { name: 'jaw_period', label: 'Jaw Period', type: 'int', default: 13 },
    { name: 'teeth_period', label: 'Teeth Period', type: 'int', default: 8 },
    { name: 'lips_period', label: 'Lips Period', type: 'int', default: 5 },
  ],
  highest: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  hma: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  hv: [
    { name: 'length', label: 'Length', type: 'int', default: 10 },
    { name: 'annual', label: 'Annual Periods', type: 'int', default: 365 },
    { name: 'per', label: 'Timeframe Periods', type: 'int', default: 1 },
  ],
  ichimoku: [
    { name: 'conversion_periods', label: 'Conversion Periods', type: 'int', default: 9 },
    { name: 'base_periods', label: 'Base Periods', type: 'int', default: 26 },
    { name: 'lagging_span2_periods', label: 'Lagging Span B Periods', type: 'int', default: 52 },
    { name: 'displacement', label: 'Displacement', type: 'int', default: 26 },
  ],
  kama: [
    { name: 'length', label: 'Length', type: 'int', default: 14 },
    { name: 'fast_length', label: 'Fast Length', type: 'int', default: 2 },
    { name: 'slow_length', label: 'Slow Length', type: 'int', default: 30 },
  ],
  keltner: [
    { name: 'ema_period', label: 'EMA Period', type: 'int', default: 20 },
    { name: 'atr_period', label: 'ATR Period', type: 'int', default: 10 },
    { name: 'multiplier', label: 'Multiplier', type: 'float', default: 2.0 },
  ],
  kst: [
    { name: 'roclen1', label: 'ROC Length 1', type: 'int', default: 10 },
    { name: 'roclen2', label: 'ROC Length 2', type: 'int', default: 15 },
    { name: 'roclen3', label: 'ROC Length 3', type: 'int', default: 20 },
    { name: 'roclen4', label: 'ROC Length 4', type: 'int', default: 30 },
    { name: 'smalen1', label: 'SMA Length 1', type: 'int', default: 10 },
    { name: 'smalen2', label: 'SMA Length 2', type: 'int', default: 10 },
    { name: 'smalen3', label: 'SMA Length 3', type: 'int', default: 10 },
    { name: 'smalen4', label: 'SMA Length 4', type: 'int', default: 15 },
    { name: 'siglen', label: 'Signal Length', type: 'int', default: 9 },
  ],
  kvo: [
    { name: 'trig_len', label: 'Trigger Length', type: 'int', default: 13 },
    { name: 'fast_x', label: 'Fast X', type: 'int', default: 34 },
    { name: 'slow_x', label: 'Slow X', type: 'int', default: 55 },
  ],
  linreg: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  linregangle: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  linregintercept: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  lowest: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  lrslope: [
    { name: 'period', label: 'Period', type: 'int', default: 100 },
    { name: 'interval', label: 'Interval', type: 'int', default: 1 },
  ],
  ma_envelopes: [
    { name: 'period', label: 'Period', type: 'int', default: 20 },
    { name: 'percentage', label: 'Percentage', type: 'float', default: 2.5 },
    { name: 'ma_type', label: 'MA Type', type: 'string', default: 'SMA', choices: ['SMA', 'EMA'] },
  ],
  macd: [
    { name: 'fast_period', label: 'Fast Period', type: 'int', default: 12 },
    { name: 'slow_period', label: 'Slow Period', type: 'int', default: 26 },
    { name: 'signal_period', label: 'Signal Period', type: 'int', default: 9 },
  ],
  massindex: [{ name: 'length', label: 'Length', type: 'int', default: 10 }],
  mcginley: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  median: [{ name: 'period', label: 'Period', type: 'int', default: 3 }],
  medprice: [],
  mfi: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  midpoint: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  midprice: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  minus_dm: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  mode: [
    { name: 'period', label: 'Period', type: 'int', default: 20 },
    { name: 'bins', label: 'Bins', type: 'int', default: 10 },
  ],
  mom: [{ name: 'period', label: 'Period', type: 'int', default: 10 }],
  natr: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  nvi: [],
  nvi_with_ema: [{ name: 'ema_length', label: 'EMA Length', type: 'int', default: 255 }],
  obv: [],
  obv_smoothed: [
    {
      name: 'ma_type',
      label: 'MA Type',
      type: 'string',
      default: 'None',
      choices: ['None', 'SMA', 'SMA + Bollinger Bands', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA'],
    },
    { name: 'ma_length', label: 'MA Length', type: 'int', default: 20 },
    { name: 'bb_length', label: 'BB Length', type: 'int', default: 20 },
    { name: 'bb_mult', label: 'BB Mult', type: 'float', default: 2.0 },
  ],
  pivot_points: [],
  plus_dm: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  po: [
    { name: 'fast_period', label: 'Fast Period', type: 'int', default: 10 },
    { name: 'slow_period', label: 'Slow Period', type: 'int', default: 20 },
    { name: 'ma_type', label: 'MA Type', type: 'string', default: 'SMA', choices: ['SMA', 'EMA'] },
  ],
  ppo: [
    { name: 'fast_period', label: 'Fast Period', type: 'int', default: 12 },
    { name: 'slow_period', label: 'Slow Period', type: 'int', default: 26 },
    { name: 'signal_period', label: 'Signal Period', type: 'int', default: 9 },
  ],
  psar: [
    { name: 'acceleration', label: 'Acceleration', type: 'float', default: 0.02 },
    { name: 'maximum', label: 'Maximum', type: 'float', default: 0.2 },
  ],
  pvi: [{ name: 'initial_value', label: 'Initial Value', type: 'float', default: 100.0 }],
  pvi_with_signal: [
    { name: 'initial_value', label: 'Initial Value', type: 'float', default: 100.0 },
    {
      name: 'signal_type',
      label: 'Signal Type',
      type: 'string',
      default: 'EMA',
      choices: ['EMA', 'SMA'],
    },
    { name: 'signal_length', label: 'Signal Length', type: 'int', default: 255 },
  ],
  pvt: [],
  rising: [{ name: 'length', label: 'Length', type: 'int', default: 1 }],
  roc: [{ name: 'length', label: 'Length', type: 'int', default: 14 }],
  rocp: [{ name: 'period', label: 'Period', type: 'int', default: 10 }],
  rocr: [{ name: 'period', label: 'Period', type: 'int', default: 10 }],
  rocr100: [{ name: 'period', label: 'Period', type: 'int', default: 10 }],
  rsi: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  rvi: [{ name: 'period', label: 'Period', type: 'int', default: 10 }],
  rvol: [{ name: 'period', label: 'Period', type: 'int', default: 20 }],
  rwi: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  sma: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  starc: [
    { name: 'ma_period', label: 'MA Period', type: 'int', default: 5 },
    { name: 'atr_period', label: 'ATR Period', type: 'int', default: 15 },
    { name: 'multiplier', label: 'Multiplier', type: 'float', default: 1.33 },
  ],
  stc: [
    { name: 'fast_length', label: 'Fast Length', type: 'int', default: 23 },
    { name: 'slow_length', label: 'Slow Length', type: 'int', default: 50 },
    { name: 'cycle_length', label: 'Cycle Length', type: 'int', default: 10 },
    { name: 'd1_length', label: 'D1 Length', type: 'int', default: 3 },
    { name: 'd2_length', label: 'D2 Length', type: 'int', default: 3 },
  ],
  stdev: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  stochastic: [
    { name: 'k_period', label: 'K Period', type: 'int', default: 14 },
    { name: 'smooth_k', label: 'Smooth K', type: 'int', default: 3 },
    { name: 'd_period', label: 'D Period', type: 'int', default: 3 },
  ],
  stochf: [
    { name: 'fastk_period', label: 'Fast K Period', type: 'int', default: 5 },
    { name: 'fastd_period', label: 'Fast D Period', type: 'int', default: 3 },
  ],
  stochrsi: [
    { name: 'rsi_period', label: 'RSI Period', type: 'int', default: 14 },
    { name: 'stoch_period', label: 'Stoch Period', type: 'int', default: 14 },
    { name: 'k_period', label: 'K Period', type: 'int', default: 3 },
    { name: 'd_period', label: 'D Period', type: 'int', default: 3 },
  ],
  supertrend: [
    { name: 'period', label: 'Period', type: 'int', default: 10 },
    { name: 'multiplier', label: 'Multiplier', type: 'float', default: 3.0 },
  ],
  t3: [
    { name: 'period', label: 'Period', type: 'int', default: 21 },
    { name: 'v_factor', label: 'Volume Factor', type: 'float', default: 0.7 },
  ],
  tema: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  trima: [{ name: 'period', label: 'Period', type: 'int', default: 20 }],
  trix: [{ name: 'length', label: 'Length', type: 'int', default: 18 }],
  true_range: [],
  tsf: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  tsi: [
    { name: 'long_period', label: 'Long Period', type: 'int', default: 25 },
    { name: 'short_period', label: 'Short Period', type: 'int', default: 13 },
    { name: 'signal_period', label: 'Signal Period', type: 'int', default: 13 },
  ],
  typprice: [],
  ultimate_oscillator: [
    { name: 'period1', label: 'Period 1', type: 'int', default: 7 },
    { name: 'period2', label: 'Period 2', type: 'int', default: 14 },
    { name: 'period3', label: 'Period 3', type: 'int', default: 28 },
  ],
  uo_oscillator: [
    { name: 'period1', label: 'Period 1', type: 'int', default: 7 },
    { name: 'period2', label: 'Period 2', type: 'int', default: 14 },
    { name: 'period3', label: 'Period 3', type: 'int', default: 28 },
  ],
  variance: [
    { name: 'lookback', label: 'Lookback', type: 'int', default: 20 },
    { name: 'mode', label: 'Mode', type: 'string', default: 'PR', choices: ['PR', 'LR'] },
    { name: 'ema_period', label: 'EMA Period', type: 'int', default: 20 },
    { name: 'filter_lookback', label: 'Filter Lookback', type: 'int', default: 20 },
    { name: 'ema_length', label: 'EMA Length', type: 'int', default: 14 },
    { name: 'return_components', label: 'Return Components', type: 'bool', default: false },
  ],
  vidya: [
    { name: 'period', label: 'Period', type: 'int', default: 14 },
    { name: 'alpha', label: 'Alpha', type: 'float', default: 0.2 },
  ],
  volosc: [
    { name: 'short_length', label: 'Short Length', type: 'int', default: 5 },
    { name: 'long_length', label: 'Long Length', type: 'int', default: 10 },
    { name: 'check_volume_validity', label: 'Check Volume Validity', type: 'bool', default: true },
  ],
  vroc: [{ name: 'period', label: 'Period', type: 'int', default: 25 }],
  vwap: [
    {
      name: 'anchor',
      label: 'Anchor',
      type: 'string',
      default: 'Session',
      choices: [
        'Session',
        'Week',
        'Month',
        'Quarter',
        'Year',
        '12M',
        '6M',
        '3M',
        'D',
        '4H',
        '1H',
        '30m',
        '15m',
        '5m',
        '1m',
      ],
    },
    {
      name: 'source',
      label: 'Source',
      type: 'string',
      default: 'hlc3',
      choices: ['hlc3', 'hl2', 'ohlc4', 'close'],
    },
    { name: 'stdev_mult_1', label: 'Stdev Mult 1', type: 'float', default: 1.0 },
    { name: 'stdev_mult_2', label: 'Stdev Mult 2', type: 'float', default: 2.0 },
    { name: 'stdev_mult_3', label: 'Stdev Mult 3', type: 'float', default: 3.0 },
    { name: 'percent_mult_1', label: 'Percent Mult 1', type: 'float', default: 0.236 },
    { name: 'percent_mult_2', label: 'Percent Mult 2', type: 'float', default: 0.382 },
    { name: 'percent_mult_3', label: 'Percent Mult 3', type: 'float', default: 0.618 },
  ],
  vwma: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  wclprice: [],
  williams_r: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  wma: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
  zlema: [{ name: 'period', label: 'Period', type: 'int', default: 14 }],
}

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
    // The scheduler has always read these; only the switch had a default, so a
    // workflow inherited the exchange's full session unless someone edited the
    // JSON by hand. 15:15 leaves room to square off before the 15:30 close.
    marketHoursOnly: true,
    marketHoursStart: '09:15',
    marketHoursEnd: '15:15',
    marketHoursExchange: 'NSE',
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
    // No symbol or exchange: the request carries them. Downstream nodes read
    // `{{webhook.symbol}}` and friends, so a copy stored on the trigger would
    // be a second source of truth that the executor never looks at.
    label: '',
  },
  placeOrder: {
    symbol: '',
    exchange: 'NSE',
    action: 'BUY' as const,
    quantity: 1,
    priceType: 'MARKET' as const,
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
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
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
    price: 0,
    triggerPrice: 0,
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
    // An option is a derivative contract whatever its underlying's exchange
    // reads, so this defaults to NRML rather than following that field.
    product: 'NRML' as const,
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
    // An option is a derivative contract whatever its underlying's exchange
    // reads, so this defaults to NRML rather than following that field.
    product: 'NRML' as const,
  },
  cancelOrder: {
    orderId: '',
  },
  cancelAllOrders: {},
  closePositions: {
    symbol: '',
    exchange: 'NSE',
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
  },
  modifyOrder: {
    // Only the order id. symbol/exchange/action/product/priceType are read back
    // from the live order by the executor, and anything present here is treated
    // as a deliberate override -- so shipping exchange 'NSE' and action 'BUY' as
    // defaults sent them to the broker on every modify, converting a live NFO
    // SELL order into an NSE BUY. The backend lookup alone could not prevent
    // this, because it cannot tell a default apart from an intended value.
    orderId: '',
  },
  basketOrder: {
    orders: '',
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
    priceType: 'MARKET' as const,
    price: 0,
    triggerPrice: 0,
  },
  splitOrder: {
    symbol: '',
    exchange: 'NSE',
    action: 'BUY' as const,
    quantity: 100,
    splitSize: 50,
    priceType: 'MARKET' as const,
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
    price: 0,
    triggerPrice: 0,
  },
  positionCheck: {
    symbol: '',
    exchange: 'NSE',
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
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
    // The panel only shows this as a grey placeholder, so a node saved
    // without typing here stored nothing and {{ind.latest.value}} never
    // resolved -- the run failed with no indication which field was blank.
    outputVariable: 'ind',
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
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
    outputVariable: '',
  },
  // The config panel renders this name as its input's fallback value, so the
  // box looks filled while the saved node keeps an empty string and
  // store_output writes nothing. Every downstream {{...}} reference then
  // resolves to its own literal text. Persist what the user is shown.
  orderBook: {
    outputVariable: 'orders',
  },
  // The config panel renders this name as its input's fallback value, so the
  // box looks filled while the saved node keeps an empty string and
  // store_output writes nothing. Every downstream {{...}} reference then
  // resolves to its own literal text. Persist what the user is shown.
  tradeBook: {
    outputVariable: 'trades',
  },
  // The config panel renders this name as its input's fallback value, so the
  // box looks filled while the saved node keeps an empty string and
  // store_output writes nothing. Every downstream {{...}} reference then
  // resolves to its own literal text. Persist what the user is shown.
  positionBook: {
    outputVariable: 'positions',
  },
  // The config panel renders this name as its input's fallback value, so the
  // box looks filled while the saved node keeps an empty string and
  // store_output writes nothing. Every downstream {{...}} reference then
  // resolves to its own literal text. Persist what the user is shown.
  holdings: {
    outputVariable: 'holdings',
  },
  // The config panel renders this name as its input's fallback value, so the
  // box looks filled while the saved node keeps an empty string and
  // store_output writes nothing. Every downstream {{...}} reference then
  // resolves to its own literal text. Persist what the user is shown.
  funds: {
    outputVariable: 'funds',
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
    // A JSON string, matching the panel's textarea and the executor's
    // parser. The `{}` default rendered as the literal [object Object].
    headers: '',
    body: '',
    // Milliseconds, as the panel's own label and bounds already said.
    timeout: 30000,
    outputVariable: 'response',
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
    // See the note on orderBook: a displayed fallback that is not persisted
    // leaves the variable undefined at run time.
    outputVariable: 'quotes',
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
    outputVariable: 'holidays',
  },
  timings: {
    // The calendar service takes a date (YYYY-MM-DD). Blank = today.
    date: '',
    outputVariable: 'timings',
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
    // No product: an untouched node follows its exchange, so switching it to a
    // derivative segment shows -- and sends -- NRML while cash stays MIS. A
    // product the author actually picks is stored and wins.
    action: 'BUY' as const,
    priceType: 'MARKET' as const,
    outputVariable: 'marginResult',
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
