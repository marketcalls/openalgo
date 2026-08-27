export interface OptionChainResponse {
  status: 'success' | 'error'
  underlying: string
  /** Exact market-data reference resolved by the backend for the underlying quote. */
  underlying_symbol: string
  underlying_exchange: string
  underlying_ltp: number
  underlying_prev_close: number
  expiry_date: string
  /** Expiry instant as epoch seconds, carrying the exchange's cut-off time */
  expiry_ts?: number | null
  /** Server time as epoch seconds, used to correct for client clock skew */
  server_ts?: number
  atm_strike: number
  /** Forward price used for Greeks, present when the server computed them */
  forward_price?: number | null
  greeks_included?: boolean
  chain: OptionStrike[]
  message?: string
}

/** Immutable derivative request identity attached when an option-chain poll starts. */
export interface OptionChainDataIdentity {
  exchange: string
  underlying: string
  expiry: string
}

export interface OptionStrike {
  strike: number
  ce: OptionData | null
  pe: OptionData | null
}

export interface OptionData {
  symbol: string
  label: string
  ltp: number
  bid: number
  ask: number
  bid_qty: number
  ask_qty: number
  open: number
  high: number
  low: number
  prev_close: number
  volume: number
  oi: number
  lotsize: number
  tick_size: number
  /**
   * Greeks. Undefined when not computable for this leg (no quote, expired
   * chain), which the UI renders as a dash rather than a zero. Recomputed
   * client-side on every tick; also returned by the API when with_greeks is set.
   */
  implied_volatility?: number
  delta?: number
  gamma?: number
  theta?: number
  vega?: number
}

export interface OptionChainParams {
  underlying: string
  exchange: string
  expiry_date: string
  strike_count?: number
}

export interface MarketMetrics {
  total_ce_oi: number
  total_pe_oi: number
  total_ce_volume: number
  total_pe_volume: number
  pcr: number
}

export interface OptionChainState {
  data: OptionChainResponse | null
  isLoading: boolean
  isConnected: boolean
  error: string | null
  lastUpdate: Date | null
}

// Column configuration types
export type ColumnKey =
  | 'ce_oi'
  | 'ce_volume'
  | 'ce_bid_qty'
  | 'ce_bid'
  | 'ce_ltp'
  | 'ce_ask'
  | 'ce_ask_qty'
  | 'ce_spread'
  | 'ce_iv'
  | 'ce_delta'
  | 'ce_gamma'
  | 'ce_theta'
  | 'ce_vega'
  | 'strike'
  | 'pe_spread'
  | 'pe_ask_qty'
  | 'pe_ask'
  | 'pe_ltp'
  | 'pe_bid'
  | 'pe_bid_qty'
  | 'pe_volume'
  | 'pe_oi'
  | 'pe_iv'
  | 'pe_delta'
  | 'pe_gamma'
  | 'pe_theta'
  | 'pe_vega'

export type ColumnSide = 'ce' | 'pe' | 'center'

/**
 * Which preset of columns the chain is showing. Both modes draw from the same
 * 27-column pool and each keeps its own visibility and ordering, so a wide
 * screen can mix price and Greek columns in either one.
 */
export type ViewMode = 'price' | 'greeks'

export const VIEW_MODES: { value: ViewMode; label: string }[] = [
  { value: 'price', label: 'Price' },
  { value: 'greeks', label: 'Greeks' },
]

export interface ColumnDefinition {
  key: ColumnKey
  label: string
  side: ColumnSide
  width: string
  align: 'left' | 'center' | 'right'
  defaultVisible: boolean
  formatter?: 'number' | 'price' | 'spread' | 'none' | 'iv' | 'greek' | 'gamma'
  /** Marks the Greek columns, so the config UI can group them separately */
  isGreek?: boolean
}

export const COLUMN_DEFINITIONS: ColumnDefinition[] = [
  // CE columns (left side) - ordered left to right
  {
    key: 'ce_oi',
    label: 'OI',
    side: 'ce',
    width: 'w-20',
    align: 'right',
    defaultVisible: true,
    formatter: 'number',
  },
  {
    key: 'ce_volume',
    label: 'Volume',
    side: 'ce',
    width: 'w-20',
    align: 'right',
    defaultVisible: true,
    formatter: 'number',
  },
  {
    key: 'ce_bid_qty',
    label: 'Bid Qty',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: true,
    formatter: 'number',
  },
  {
    key: 'ce_bid',
    label: 'Bid',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: true,
    formatter: 'price',
  },
  {
    key: 'ce_ltp',
    label: 'LTP',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: true,
    formatter: 'price',
  },
  {
    key: 'ce_ask',
    label: 'Ask',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: true,
    formatter: 'price',
  },
  {
    key: 'ce_ask_qty',
    label: 'Ask Qty',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: true,
    formatter: 'number',
  },
  {
    key: 'ce_spread',
    label: 'Spread',
    side: 'ce',
    width: 'w-14',
    align: 'right',
    defaultVisible: true,
    formatter: 'spread',
  },
  // CE Greeks - ordered outermost (IV) to innermost (Delta), so Delta and LTP
  // sit next to the strike where the eye lands
  {
    key: 'ce_iv',
    label: 'IV',
    side: 'ce',
    width: 'w-14',
    align: 'right',
    defaultVisible: false,
    formatter: 'iv',
    isGreek: true,
  },
  {
    key: 'ce_vega',
    label: 'Vega',
    side: 'ce',
    width: 'w-14',
    align: 'right',
    defaultVisible: false,
    formatter: 'greek',
    isGreek: true,
  },
  {
    key: 'ce_theta',
    label: 'Theta',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: false,
    formatter: 'greek',
    isGreek: true,
  },
  {
    key: 'ce_gamma',
    label: 'Gamma',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: false,
    formatter: 'gamma',
    isGreek: true,
  },
  {
    key: 'ce_delta',
    label: 'Delta',
    side: 'ce',
    width: 'w-16',
    align: 'right',
    defaultVisible: false,
    formatter: 'greek',
    isGreek: true,
  },
  // Center column
  {
    key: 'strike',
    label: 'Strike',
    side: 'center',
    width: 'w-20',
    align: 'center',
    defaultVisible: true,
    formatter: 'none',
  },
  // PE columns (right side) - ordered left to right
  {
    key: 'pe_spread',
    label: 'Spread',
    side: 'pe',
    width: 'w-14',
    align: 'left',
    defaultVisible: true,
    formatter: 'spread',
  },
  {
    key: 'pe_ask_qty',
    label: 'Ask Qty',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: true,
    formatter: 'number',
  },
  {
    key: 'pe_ask',
    label: 'Ask',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: true,
    formatter: 'price',
  },
  {
    key: 'pe_ltp',
    label: 'LTP',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: true,
    formatter: 'price',
  },
  {
    key: 'pe_bid',
    label: 'Bid',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: true,
    formatter: 'price',
  },
  {
    key: 'pe_bid_qty',
    label: 'Bid Qty',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: true,
    formatter: 'number',
  },
  {
    key: 'pe_volume',
    label: 'Volume',
    side: 'pe',
    width: 'w-20',
    align: 'left',
    defaultVisible: true,
    formatter: 'number',
  },
  {
    key: 'pe_oi',
    label: 'OI',
    side: 'pe',
    width: 'w-20',
    align: 'left',
    defaultVisible: true,
    formatter: 'number',
  },
  // PE Greeks - mirrored, so Delta sits nearest the strike as it does on CE
  {
    key: 'pe_delta',
    label: 'Delta',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: false,
    formatter: 'greek',
    isGreek: true,
  },
  {
    key: 'pe_gamma',
    label: 'Gamma',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: false,
    formatter: 'gamma',
    isGreek: true,
  },
  {
    key: 'pe_theta',
    label: 'Theta',
    side: 'pe',
    width: 'w-16',
    align: 'left',
    defaultVisible: false,
    formatter: 'greek',
    isGreek: true,
  },
  {
    key: 'pe_vega',
    label: 'Vega',
    side: 'pe',
    width: 'w-14',
    align: 'left',
    defaultVisible: false,
    formatter: 'greek',
    isGreek: true,
  },
  {
    key: 'pe_iv',
    label: 'IV',
    side: 'pe',
    width: 'w-14',
    align: 'left',
    defaultVisible: false,
    formatter: 'iv',
    isGreek: true,
  },
]

export const ALL_COLUMN_KEYS: ColumnKey[] = COLUMN_DEFINITIONS.map((col) => col.key)

/**
 * A column as a trader thinks of it: one entry covering both sides.
 *
 * The chain is a mirrored table, so Delta means the CE and PE delta columns
 * together. Visibility is toggled through these pairs rather than the
 * underlying `ce_*` / `pe_*` keys, which would otherwise need unchecking twice
 * to disappear from the table.
 *
 * Ordering stays per side and is handled separately by the reorder panel.
 */
export interface LogicalColumn {
  label: string
  isGreek: boolean
  /** The CE and PE keys this entry controls */
  keys: ColumnKey[]
}

export const LOGICAL_COLUMNS: LogicalColumn[] = COLUMN_DEFINITIONS.filter(
  (col) => col.side === 'ce'
).map((col) => {
  const base = col.key.slice(3)
  const peKey = `pe_${base}` as ColumnKey
  return {
    label: col.label,
    isGreek: Boolean(col.isGreek),
    keys: COLUMN_DEFINITIONS.some((c) => c.key === peKey) ? [col.key, peKey] : [col.key],
  }
})

export const DEFAULT_COLUMN_ORDER: ColumnKey[] = ALL_COLUMN_KEYS

export const DEFAULT_VISIBLE_COLUMNS: ColumnKey[] = COLUMN_DEFINITIONS.filter(
  (col) => col.defaultVisible
).map((col) => col.key)

export type BarDataSource = 'oi' | 'volume'
export type BarStyle = 'gradient' | 'solid'

export interface ModePreferences {
  visibleColumns: ColumnKey[]
  columnOrder: ColumnKey[]
}

export interface OptionChainPreferences {
  viewMode: ViewMode
  modes: Record<ViewMode, ModePreferences>
  strikeCount: number
  selectedUnderlying: string
  barDataSource: BarDataSource
  barStyle: BarStyle
}

/**
 * Column order for Price mode: price columns first on each side, Greek columns
 * appended outward. Enabling a Greek here puts it at the far edge rather than
 * displacing the prices.
 */
const PRICE_MODE_ORDER: ColumnKey[] = [
  'ce_oi',
  'ce_volume',
  'ce_bid_qty',
  'ce_bid',
  'ce_ltp',
  'ce_ask',
  'ce_ask_qty',
  'ce_spread',
  'ce_iv',
  'ce_vega',
  'ce_theta',
  'ce_gamma',
  'ce_delta',
  'strike',
  'pe_spread',
  'pe_ask_qty',
  'pe_ask',
  'pe_ltp',
  'pe_bid',
  'pe_bid_qty',
  'pe_volume',
  'pe_oi',
  'pe_delta',
  'pe_gamma',
  'pe_theta',
  'pe_vega',
  'pe_iv',
]

/**
 * Column order for Greeks mode: Greeks first on each side with LTP against the
 * strike, price columns appended outward.
 */
const GREEKS_MODE_ORDER: ColumnKey[] = [
  'ce_iv',
  'ce_vega',
  'ce_theta',
  'ce_gamma',
  'ce_delta',
  'ce_ltp',
  'ce_oi',
  'ce_volume',
  'ce_bid_qty',
  'ce_bid',
  'ce_ask',
  'ce_ask_qty',
  'ce_spread',
  'strike',
  'pe_ltp',
  'pe_delta',
  'pe_gamma',
  'pe_theta',
  'pe_vega',
  'pe_iv',
  'pe_spread',
  'pe_ask_qty',
  'pe_ask',
  'pe_bid',
  'pe_bid_qty',
  'pe_volume',
  'pe_oi',
]

export const DEFAULT_MODE_PREFERENCES: Record<ViewMode, ModePreferences> = {
  price: {
    visibleColumns: DEFAULT_VISIBLE_COLUMNS,
    columnOrder: PRICE_MODE_ORDER,
  },
  greeks: {
    visibleColumns: [
      'ce_iv',
      'ce_vega',
      'ce_theta',
      'ce_gamma',
      'ce_delta',
      'ce_ltp',
      'strike',
      'pe_ltp',
      'pe_delta',
      'pe_gamma',
      'pe_theta',
      'pe_vega',
      'pe_iv',
    ],
    columnOrder: GREEKS_MODE_ORDER,
  },
}

export const DEFAULT_PREFERENCES: OptionChainPreferences = {
  viewMode: 'price',
  modes: DEFAULT_MODE_PREFERENCES,
  strikeCount: 10,
  selectedUnderlying: 'NIFTY',
  barDataSource: 'oi',
  barStyle: 'gradient',
}

export const LOCALSTORAGE_KEY = 'openalgo_option_chain_prefs'
