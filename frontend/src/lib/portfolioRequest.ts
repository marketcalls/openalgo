import type {
  BacktestRequest,
  PortfolioHolding,
  PriceSource,
  RebalanceRule,
} from '@/api/portfolio'

export type BrokerageMode = 'flat' | 'percent'

export interface ChargeState {
  brokerageFlat: number
  brokeragePct: number
  brokerageCap: number
  brokerageMode: BrokerageMode
  stt: number
  exchangeTxn: number
  sebiPerCrore: number
  gst: number
  stampDuty: number
  slippage: number
}

export const DEFAULT_CHARGES: ChargeState = {
  brokerageMode: 'flat',
  brokerageFlat: 0,
  brokeragePct: 0.03,
  brokerageCap: 20,
  stt: 0.1,
  exchangeTxn: 0.00307,
  sebiPerCrore: 10,
  gst: 18,
  stampDuty: 0.015,
  slippage: 0,
}

export interface PortfolioRequestForm {
  apiKey: string
  holdings: PortfolioHolding[]
  startDate: string
  endDate: string
  benchmark: string | null
  benchmarkExchange: string
  rebalance: RebalanceRule
  source: PriceSource
  charges: ChargeState
  costExchange: 'NSE' | 'BSE'
  /** Percentage shown in the form. */
  riskFree: number
}

/** The single wire contract used by both analysis and tearsheet export. */
export function buildPortfolioRequest(form: PortfolioRequestForm): BacktestRequest {
  const { charges } = form
  return {
    apikey: form.apiKey,
    holdings: form.holdings
      .filter((holding) => holding.symbol.trim() !== '')
      .map((holding) => ({
        ...holding,
        symbol: holding.symbol.trim().toUpperCase(),
      })),
    start_date: form.startDate,
    end_date: form.endDate,
    benchmark: form.benchmark,
    benchmark_exchange: form.benchmarkExchange,
    rebalance: form.rebalance,
    cost_model: 'indian_equity',
    cost_exchange: form.costExchange,
    charges: {
      brokerage:
        charges.brokerageMode === 'flat'
          ? { flat: charges.brokerageFlat, rate: 0 }
          : {
              flat: 0,
              rate: charges.brokeragePct / 100,
              cap: charges.brokerageCap,
            },
      stt: { rate: charges.stt / 100 },
      exchange_txn: { rate: charges.exchangeTxn / 100 },
      stamp_duty: { rate: charges.stampDuty / 100 },
      sebi: { rate: charges.sebiPerCrore / 1_00_00_000 },
    },
    gst_rate: charges.gst / 100,
    slippage: charges.slippage / 100,
    risk_free_rate: form.riskFree / 100,
    source: form.source,
  }
}

export function healthGradeTone(
  grade: string | null | undefined
): 'good' | 'bad' | undefined {
  if (grade && ['A', 'B', 'C'].includes(grade)) return 'good'
  if (grade && ['D', 'F'].includes(grade)) return 'bad'
  return undefined
}
