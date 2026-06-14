// Types for the /scalping keyboard-driven options scalping terminal.
// Order constants mirror OpenAlgo (docs/prompt/order-constants.md).

export type OptionType = 'CE' | 'PE'
export type ScalpingProduct = 'MIS' | 'NRML' | 'CNC'
export type ScalpingAction = 'BUY' | 'SELL'
export type Segment = 'OPTIONS' | 'FUTURES' | 'EQUITY'

// A single tradable instrument (equity share or futures contract) from search.
export interface SearchInstrument {
  symbol: string
  exchange: string
  lotsize: number
  name?: string
}

export interface ScalpingUnderlying {
  underlying: string
  index_exchange: string // NSE_INDEX | BSE_INDEX
  fo_exchange: string // NFO | BFO
}

export interface UnderlyingsResponse {
  status: string
  data: ScalpingUnderlying[]
}

export interface ExpiryResponse {
  status: string
  data: string[] // DDMMMYY, e.g. "28OCT25"
  message?: string
}

export interface OptionLeg {
  symbol: string
  label: string // ATM, ITM1, OTM2, ...
  ltp?: number
  bid?: number
  ask?: number
  lotsize?: number | null
  tick_size?: number | null
  exists?: boolean
}

export interface OptionChainRow {
  strike: number
  ce: OptionLeg
  pe: OptionLeg
}

export interface OptionChainResponse {
  status: string
  underlying: string
  underlying_ltp?: number
  expiry_date: string
  atm_strike?: number
  chain: OptionChainRow[]
  fo_exchange: string
  index_exchange: string
  message?: string
}

// A selected leg ready for subscription/trading.
export interface SelectedLeg {
  symbol: string
  exchange: string // fo_exchange (NFO | BFO)
  optionType: OptionType
  strike: number
  lotsize: number
  tickSize: number
}

export interface ScalpingOrderRequest {
  symbol: string
  exchange: string // NFO | BFO
  action: ScalpingAction
  quantity: number
  product: ScalpingProduct
  lots?: number // sent on manual entry so the lot cap is enforced server-side
}

export interface ScalpingOrderResponse {
  status: string
  orderid?: string
  message?: string
}

// Stop-loss / trailing-SL state persisted per (symbol, exchange, product) leg.
export interface ScalpingSLState {
  symbol: string
  exchange: string
  product: ScalpingProduct
  side: ScalpingAction
  entry_price: number
  quantity: number
  initial_sl: number | null
  trailing_enabled: boolean
  trailing_step: number | null
  highest_price: number | null
  lowest_price: number | null
  current_sl: number | null
  target: number | null
  is_active: boolean
}

export interface SLStatesResponse {
  status: string
  data: ScalpingSLState[]
}

// Derived per-(symbol, exchange, product) row for the 1cliq-style position book.
// Combines the current open position, today's buy/sell trades, realized +
// unrealized P&L, and the active SL. Rows with netQty 0 still appear if there
// were trades today (realized P&L must stay visible until session reset).
export interface ScalpingPositionRow {
  symbol: string
  exchange: string
  product: ScalpingProduct
  side: 'BUY' | 'SELL' | '-'
  netQty: number
  ltp: number
  sl: number | null
  realizedPnl: number
  unrealizedPnl: number
  totalPnl: number
  avgPrice: number
  buyQty: number
  buyAvg: number
  sellQty: number
  sellAvg: number
}
