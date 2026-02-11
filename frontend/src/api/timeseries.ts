import { webClient } from './client'

// Symbol passed to the /data endpoint.
// 'symbol' and 'exchange' are required by the backend.
// 'type' and 'strike' are frontend-only metadata used for CE/PE/FUT classification.
export interface TimeseriesSymbol {
    symbol: string
    exchange: string
    type?: 'CE' | 'PE' | 'FUT'
    strike?: number
}

// Futures info
export interface FuturesInfo {
    symbol: string
    exchange: string
}

// Chain response with symbols for timeseries
export interface TimeseriesChainResponse {
    status: 'success' | 'error'
    message?: string
    underlying?: string
    underlying_ltp?: number
    atm_strike?: number
    lot_size?: number
    expiry_date?: string
    futures?: FuturesInfo | null
    symbols?: TimeseriesSymbol[]
}

// Raw row from backend — only aggregated values, no derived metrics
export interface TimeseriesRawRow {
    timestamp: string
    ce_oi: number
    pe_oi: number
    ce_volume: number
    pe_volume: number
    fut_ltp: number
    fut_oi: number
    fut_volume: number
}

// Enriched row with all derived metrics computed on frontend
export interface TimeseriesRow {
    timestamp: string
    ce_oi: number
    pe_oi: number
    pe_ce_oi: number
    pcr: number
    ce_volume: number
    pe_volume: number
    fut_ltp: number
    fut_oi: number
    fut_volume: number
    ce_oi_day_change: number
    pe_oi_day_change: number
    ce_volume_day_change: number
    pe_volume_day_change: number
    pe_ce_oi_day_change: number
    pcr_day_change: number
    fut_ltp_day_change: number
    fut_oi_day_change: number
    fut_volume_day_change: number
    // Row change (from previous row)
    ce_oi_change: number
    pe_oi_change: number
    ce_volume_change: number
    pe_volume_change: number
    pe_ce_oi_change: number
    pcr_change: number
    fut_ltp_change: number
    fut_oi_change: number
    fut_volume_change: number
}

// Columnar data response (backend returns per-symbol arrays, no metadata)
export interface ColumnarDataResponse {
    status: 'success' | 'error'
    message?: string
    columns: string[]                          // ["oi", "ltp", "volume"]
    timestamps: string[]                       // shared time grid
    symbol_data: Record<string, number[][]>    // sym -> [oi[], ltp[], volume[]]
}

// Shared API responses
export interface UnderlyingsResponse {
    status: 'success' | 'error'
    underlyings: string[]
}

export interface ExpiriesResponse {
    status: 'success' | 'error'
    expiries: string[]
}

export const timeseriesApi = {
    // Get chain symbols for timeseries analysis
    getChain: async (params: {
        underlying: string
        exchange: string
        expiry_date: string
        strike_count: number
    }): Promise<TimeseriesChainResponse> => {
        const response = await webClient.post<TimeseriesChainResponse>(
            '/timeseries/api/chain',
            params
        )
        return response.data
    },

    // Fetch aligned history for any list of symbols (symbol-agnostic)
    getData: async (params: {
        symbols: TimeseriesSymbol[]
        interval: string
        start_date: string
        end_date: string
    }): Promise<ColumnarDataResponse> => {
        const response = await webClient.post<ColumnarDataResponse>(
            '/timeseries/api/data',
            params
        )
        return response.data
    },

    // Shared APIs for underlyings/expiries
    getUnderlyings: async (exchange: string): Promise<UnderlyingsResponse> => {
        const response = await webClient.get<UnderlyingsResponse>(
            `/search/api/underlyings?exchange=${exchange}`
        )
        return response.data
    },

    getExpiries: async (exchange: string, underlying: string): Promise<ExpiriesResponse> => {
        const response = await webClient.get<ExpiriesResponse>(
            `/search/api/expiries?exchange=${exchange}&underlying=${underlying}`
        )
        return response.data
    },
}
