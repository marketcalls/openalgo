// Admin types for Freeze Qty, Holidays, and Market Timings

export interface FreezeQty {
  id: number
  exchange: string
  symbol: string
  freeze_qty: number
}

export interface AddFreezeQtyRequest {
  exchange: string
  symbol: string
  freeze_qty: number
}

export interface UpdateFreezeQtyRequest {
  freeze_qty: number
}

export interface SpecialSessionExchange {
  exchange: string
  start_time: string // HH:MM format for UI, converted to epoch ms before sending
  end_time: string
}

export interface Holiday {
  id: number
  date: string
  day_name: string
  description: string
  holiday_type: 'TRADING_HOLIDAY' | 'SETTLEMENT_HOLIDAY' | 'SPECIAL_SESSION'
  closed_exchanges: string[]
  open_exchanges?: SpecialSessionExchange[]
}

export interface AddHolidayRequest {
  date: string
  description: string
  holiday_type: 'TRADING_HOLIDAY' | 'SETTLEMENT_HOLIDAY' | 'SPECIAL_SESSION'
  closed_exchanges: string[]
  open_exchanges?: Array<{
    exchange: string
    start_time: number // epoch milliseconds
    end_time: number
  }>
}

export interface HolidaysResponse {
  status: string
  data: Holiday[]
  current_year: number
  years: number[]
  exchanges: string[]
}

export interface MarketTiming {
  id: number | null
  exchange: string
  start_time: string
  end_time: string
  start_offset: number
  end_offset: number
}

export interface TodayTiming {
  exchange: string
  start_time: string
  end_time: string
}

export interface UpdateTimingRequest {
  start_time: string
  end_time: string
}

export interface TimingsResponse {
  status: string
  data: MarketTiming[]
  today_timings: TodayTiming[]
  today: string
  exchanges: string[]
}

export interface AdminStats {
  freeze_count: number
  holiday_count: number
}
