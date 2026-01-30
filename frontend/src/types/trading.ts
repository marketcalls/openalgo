export interface Position {
  symbol: string
  exchange: string
  product: 'MIS' | 'NRML' | 'CNC'
  quantity: number
  average_price: number
  ltp: number
  pnl: number
  pnlpercent: number
  today_realized_pnl?: number  // Sandbox: today's realized P&L from closed partial trades
}

export interface Order {
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number
  trigger_price: number
  pricetype: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'MIS' | 'NRML' | 'CNC'
  orderid: string
  order_status: 'complete' | 'rejected' | 'cancelled' | 'open' | 'pending' | 'trigger pending'
  timestamp: string
}

export interface Trade {
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  average_price: number
  trade_value: number
  product: string
  orderid: string
  timestamp: string
}

export interface Holding {
  symbol: string
  exchange: string
  quantity: number
  product: string
  pnl: number
  pnlpercent: number
  ltp?: number
  average_price?: number
}

export interface PortfolioStats {
  totalholdingvalue: number
  totalinvvalue: number
  totalprofitandloss: number
  totalpnlpercentage: number
}

// Alias for consistency
export type HoldingsStats = PortfolioStats

export interface MarginData {
  availablecash: number
  collateral: number
  m2munrealized: number
  m2mrealized: number
  utiliseddebits: number
}

export interface OrderStats {
  total_buy_orders: number
  total_sell_orders: number
  total_completed_orders: number
  total_open_orders: number
  total_rejected_orders: number
}

export interface PlaceOrderRequest {
  apikey: string
  strategy: string
  exchange: string
  symbol: string
  action: 'BUY' | 'SELL'
  quantity: number
  pricetype?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product?: 'MIS' | 'NRML' | 'CNC'
  price?: number
  trigger_price?: number
  disclosed_quantity?: number
}

export interface ApiResponse<T> {
  status: 'success' | 'error' | 'info'
  message?: string
  data?: T
}
