// Sandbox charges: the /sandbox/commissions and /sandbox/calculator pages.
//
// Talks to the session-authenticated sandbox blueprint. The server owns the
// arithmetic (sandbox/charges.py): the page sends a brokerage plan and reads
// back what trades were charged, and never works a charge out itself.

import axios from 'axios'

import { webClient } from './client'

/**
 * Which rate card the account is shown. The server decides it from the broker
 * the browser is logged in to, and sends that market's segments alone: an
 * Indian broker is never shown the crypto calculator, nor the other way round.
 */
export type ChargeMarket = 'indian' | 'crypto'

/** The six lines a fill is charged, and their sum. */
export interface ChargeBreakdown {
  brokerage: number
  /** STT, or CTT on commodities. */
  stt: number
  exchange_charges: number
  sebi_charges: number
  stamp_duty: number
  gst: number
  total_charges: number
}

/** The statutory rates of one segment, each a percentage as published. */
export interface StatutoryRates {
  /** "STT", "CTT", or empty when neither applies. */
  stt_label: string
  stt_buy: string
  stt_sell: string
  stamp_buy: string
  sebi: string
  gst: string
  /**
   * Exchange transaction charge by exchange code. Empty for crypto. Look a
   * rate up by code and take the order from the segment's `exchanges`: the
   * keys of an object arrive sorted, which is not the order to show them in.
   */
  exchange_txn: Record<string, string>
}

export interface ChargeSegment {
  key: string
  label: string
  /** The heading the segment is filed under. */
  group: string
  /** Which orders fall in the segment. */
  applies_to: string
  /** Brokerage per executed order. "0" means not used. */
  flat: string
  /** Brokerage as a percentage of the trade value. "0" means not used. */
  percent: string
  default_flat: string
  default_percent: string
  /** The exchanges the segment trades on, the main one first. */
  exchanges: string[]
  statutory: StatutoryRates
}

export interface ChargeSettings {
  /** Off means sandbox trades are free. */
  enabled: boolean
  /** The market of the broker logged in to. The segments are that market's. */
  market: ChargeMarket
  segments: ChargeSegment[]
  limits: { flat_max: string; percent_max: string }
  /** The date the statutory schedule was last checked. */
  statutory_as_of: string
}

/** What the page sends: the switch, and a plan for each segment it names. */
export interface ChargeSettingsChange {
  enabled?: boolean
  segments?: Record<string, { flat: string; percent: string }>
}

export interface EstimateRequest {
  segment: string
  exchange: string
  buy_price: string
  sell_price: string
  quantity: string
  /** The plan to price it under. Left out, the saved plan is used. */
  flat?: string
  percent?: string
}

export interface Estimate {
  segment: string
  exchange: string
  brokerage_plan: string
  stt_label: string
  turnover: number
  /** The buy and the sell together, each line worked once on the two. */
  total: ChargeBreakdown
  gross_pnl: number
  net_pnl: number
  points_to_breakeven: number
}

interface ReportBucket extends ChargeBreakdown {
  trades: number
  turnover: number
}

export interface SegmentCosts extends ReportBucket {
  segment: string
  label: string
}

export interface DayCosts extends ReportBucket {
  date: string
}

export interface TradeCosts extends ChargeBreakdown {
  tradeid: string
  orderid: string
  timestamp: string
  symbol: string
  exchange: string
  product: string
  action: string
  quantity: number
  price: number
  turnover: number
  segment: string
  segment_label: string
  strategy: string
}

export interface CostReport {
  from: string
  to: string
  totals: ReportBucket
  by_segment: SegmentCosts[]
  by_day: DayCosts[]
  /** The most recent trades in the range. The totals cover all of them. */
  trades: TradeCosts[]
  trades_listed: number
  trades_total: number
}

interface Envelope<T> {
  status: string
  message?: string
  data?: T
}

export const CHARGE_SETTINGS_KEY = ['sandbox-charges', 'settings'] as const
export const costReportKey = (from: string, to: string) =>
  ['sandbox-charges', 'report', from, to] as const

/**
 * The sentence to show for a failed request: the server's own when it sent
 * one, since every refusal it makes is written for the trader.
 */
export function chargesErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const message = (error.response?.data as Envelope<unknown> | undefined)?.message
    if (typeof message === 'string' && message) return message
  }
  return fallback
}

/** Where the report's CSV is downloaded from, for the same range. */
export function costReportExportUrl(from: string, to: string): string {
  const query = new URLSearchParams({ from, to })
  return `/sandbox/commissions/export?${query.toString()}`
}

export const sandboxChargesApi = {
  settings: async (): Promise<ChargeSettings> => {
    const response = await webClient.get<Envelope<ChargeSettings>>(
      '/sandbox/commissions/api/settings'
    )
    return response.data.data as ChargeSettings
  },

  /** Save the switch and the plan together. Resolves with what is now stored. */
  save: async (
    change: ChargeSettingsChange
  ): Promise<{ settings: ChargeSettings; message: string }> => {
    const response = await webClient.post<Envelope<ChargeSettings>>(
      '/sandbox/commissions/api/settings',
      change
    )
    return {
      settings: response.data.data as ChargeSettings,
      message: response.data.message ?? 'Charges saved.',
    }
  },

  /** Put the plan back to its defaults. Trades and funds are not touched. */
  reset: async (): Promise<{ settings: ChargeSettings; message: string }> => {
    const response = await webClient.post<Envelope<ChargeSettings>>(
      '/sandbox/commissions/api/reset'
    )
    return {
      settings: response.data.data as ChargeSettings,
      message: response.data.message ?? 'Charges are back to the defaults.',
    }
  },

  estimate: async (request: EstimateRequest): Promise<Estimate> => {
    const response = await webClient.post<Envelope<Estimate>>(
      '/sandbox/calculator/api/estimate',
      request
    )
    return response.data.data as Estimate
  },

  report: async (from: string, to: string): Promise<CostReport> => {
    const response = await webClient.get<Envelope<CostReport>>('/sandbox/commissions/api/report', {
      params: { from, to },
    })
    return response.data.data as CostReport
  },
}
