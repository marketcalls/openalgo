export interface OptionChainResponse {
  status: 'success' | 'error'
  underlying: string
  underlying_ltp: number
  underlying_prev_close: number
  expiry_date: string
  atm_strike: number
  chain: OptionStrike[]
  message?: string
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
  | 'strike'
  | 'pe_spread'
  | 'pe_ask_qty'
  | 'pe_ask'
  | 'pe_ltp'
  | 'pe_bid'
  | 'pe_bid_qty'
  | 'pe_volume'
  | 'pe_oi'

export type ColumnSide = 'ce' | 'pe' | 'center'

export interface ColumnDefinition {
  key: ColumnKey
  label: string
  side: ColumnSide
  width: string
  align: 'left' | 'center' | 'right'
  defaultVisible: boolean
  formatter?: 'number' | 'price' | 'spread' | 'none'
}

export const COLUMN_DEFINITIONS: ColumnDefinition[] = [
  // CE columns (left side) - ordered left to right
  { key: 'ce_oi', label: 'OI', side: 'ce', width: 'w-20', align: 'right', defaultVisible: true, formatter: 'number' },
  { key: 'ce_volume', label: 'Volume', side: 'ce', width: 'w-20', align: 'right', defaultVisible: true, formatter: 'number' },
  { key: 'ce_bid_qty', label: 'Bid Qty', side: 'ce', width: 'w-16', align: 'right', defaultVisible: true, formatter: 'number' },
  { key: 'ce_bid', label: 'Bid', side: 'ce', width: 'w-16', align: 'right', defaultVisible: true, formatter: 'price' },
  { key: 'ce_ltp', label: 'LTP', side: 'ce', width: 'w-16', align: 'right', defaultVisible: true, formatter: 'price' },
  { key: 'ce_ask', label: 'Ask', side: 'ce', width: 'w-16', align: 'right', defaultVisible: true, formatter: 'price' },
  { key: 'ce_ask_qty', label: 'Ask Qty', side: 'ce', width: 'w-16', align: 'right', defaultVisible: true, formatter: 'number' },
  { key: 'ce_spread', label: 'Spread', side: 'ce', width: 'w-14', align: 'right', defaultVisible: true, formatter: 'spread' },
  // Center column
  { key: 'strike', label: 'Strike', side: 'center', width: 'w-20', align: 'center', defaultVisible: true, formatter: 'none' },
  // PE columns (right side) - ordered left to right
  { key: 'pe_spread', label: 'Spread', side: 'pe', width: 'w-14', align: 'left', defaultVisible: true, formatter: 'spread' },
  { key: 'pe_ask_qty', label: 'Ask Qty', side: 'pe', width: 'w-16', align: 'left', defaultVisible: true, formatter: 'number' },
  { key: 'pe_ask', label: 'Ask', side: 'pe', width: 'w-16', align: 'left', defaultVisible: true, formatter: 'price' },
  { key: 'pe_ltp', label: 'LTP', side: 'pe', width: 'w-16', align: 'left', defaultVisible: true, formatter: 'price' },
  { key: 'pe_bid', label: 'Bid', side: 'pe', width: 'w-16', align: 'left', defaultVisible: true, formatter: 'price' },
  { key: 'pe_bid_qty', label: 'Bid Qty', side: 'pe', width: 'w-16', align: 'left', defaultVisible: true, formatter: 'number' },
  { key: 'pe_volume', label: 'Volume', side: 'pe', width: 'w-20', align: 'left', defaultVisible: true, formatter: 'number' },
  { key: 'pe_oi', label: 'OI', side: 'pe', width: 'w-20', align: 'left', defaultVisible: true, formatter: 'number' },
]

export const DEFAULT_COLUMN_ORDER: ColumnKey[] = COLUMN_DEFINITIONS.map(col => col.key)

export const DEFAULT_VISIBLE_COLUMNS: ColumnKey[] = COLUMN_DEFINITIONS
  .filter(col => col.defaultVisible)
  .map(col => col.key)

export type BarDataSource = 'oi' | 'volume'
export type BarStyle = 'gradient' | 'solid'

export interface OptionChainPreferences {
  visibleColumns: ColumnKey[]
  columnOrder: ColumnKey[]
  strikeCount: number
  selectedUnderlying: string
  barDataSource: BarDataSource
  barStyle: BarStyle
}

export const DEFAULT_PREFERENCES: OptionChainPreferences = {
  visibleColumns: DEFAULT_VISIBLE_COLUMNS,
  columnOrder: DEFAULT_COLUMN_ORDER,
  strikeCount: 10,
  selectedUnderlying: 'NIFTY',
  barDataSource: 'oi',
  barStyle: 'gradient',
}

export const LOCALSTORAGE_KEY = 'openalgo_option_chain_prefs'
