import { describe, expect, it } from 'vitest'
import {
  DEFAULT_CHARGES,
  buildPortfolioRequest,
  healthGradeTone,
} from './portfolioRequest'

describe('buildPortfolioRequest', () => {
  it('builds the complete shared analysis and export contract', () => {
    const request = buildPortfolioRequest({
      apiKey: 'key',
      holdings: [
        { symbol: ' infy ', exchange: 'NSE', weight: 60 },
        { symbol: 'tcs', exchange: 'BSE', weight: 40 },
      ],
      startDate: '2024-01-01',
      endDate: '2024-12-31',
      benchmark: 'SENSEX',
      benchmarkExchange: 'BSE_INDEX',
      rebalance: 'monthly',
      source: 'api',
      costExchange: 'BSE',
      riskFree: 6.5,
      charges: {
        brokerageMode: 'percent',
        brokerageFlat: 0,
        brokeragePct: 0.04,
        brokerageCap: 25,
        stt: 0.12,
        exchangeTxn: 0.004,
        sebiPerCrore: 12,
        gst: 20,
        stampDuty: 0.02,
        slippage: 0.15,
      },
    })

    expect(request).toEqual({
      apikey: 'key',
      holdings: [
        { symbol: 'INFY', exchange: 'NSE', weight: 60 },
        { symbol: 'TCS', exchange: 'BSE', weight: 40 },
      ],
      start_date: '2024-01-01',
      end_date: '2024-12-31',
      benchmark: 'SENSEX',
      benchmark_exchange: 'BSE_INDEX',
      rebalance: 'monthly',
      cost_model: 'indian_equity',
      cost_exchange: 'BSE',
      charges: {
        brokerage: { flat: 0, rate: 0.0004, cap: 25 },
        stt: { rate: 0.0012 },
        exchange_txn: { rate: 0.00004 },
        stamp_duty: { rate: 0.0002 },
        sebi: { rate: 0.0000012 },
      },
      gst_rate: 0.2,
      slippage: 0.0015,
      risk_free_rate: 0.065,
      source: 'api',
    })
  })

  it('defaults delivery brokerage to zero', () => {
    expect(DEFAULT_CHARGES.brokerageFlat).toBe(0)
  })
})

describe('healthGradeTone', () => {
  it.each(['A', 'B', 'C'] as const)('treats %s as healthy', (grade) => {
    expect(healthGradeTone(grade)).toBe('good')
  })

  it.each(['D', 'F'] as const)('treats %s as unhealthy', (grade) => {
    expect(healthGradeTone(grade)).toBe('bad')
  })

  it('does not invent a tone for an unavailable grade', () => {
    expect(healthGradeTone(null)).toBeUndefined()
  })
})
