import { apiClient } from './client'
import type {
  FibonacciData, HarmonicData, ElliottWaveData,
  SmartMoneyData, HedgeStrategyData, StrategyDecisionData,
  MultiTimeframeData, PatternsData, SupportResistanceData,
  NewsSentimentData, DailyReportData, ResearchReportData,
  RLSignalData, PortfolioCVaRData,
} from '@/types/strategy-analysis'

const post = async <T>(path: string, body: Record<string, unknown>): Promise<T> => {
  const { data } = await apiClient.post(path, body)
  // Backend wraps in { status: "success", data: {...} }
  return (data?.data ?? data) as T
}

export const strategyApi = {
  fibonacci: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<FibonacciData>('/api/v1/agent/fibonacci', { apikey, symbol, exchange, interval }),

  harmonic: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<HarmonicData>('/api/v1/agent/harmonic', { apikey, symbol, exchange, interval }),

  elliottWave: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<ElliottWaveData>('/api/v1/agent/elliott-wave', { apikey, symbol, exchange, interval }),

  smartMoney: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<SmartMoneyData>('/api/v1/agent/smart-money-detail', { apikey, symbol, exchange, interval }),

  hedgeStrategy: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<HedgeStrategyData>('/api/v1/agent/hedge-strategy', { apikey, symbol, exchange, interval }),

  strategyDecision: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<StrategyDecisionData>('/api/v1/agent/strategy-decision', { apikey, symbol, exchange, interval }),

  multiTimeframe: (apikey: string, symbol: string, exchange: string) =>
    post<MultiTimeframeData>('/api/v1/agent/multi-timeframe', { apikey, symbol, exchange }),

  patterns: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<PatternsData>('/api/v1/agent/patterns', { apikey, symbol, exchange, interval }),

  supportResistance: (apikey: string, symbol: string, exchange: string, interval: string) =>
    post<SupportResistanceData>('/api/v1/agent/support-resistance', { apikey, symbol, exchange, interval }),

  newsSentiment: (apikey: string, symbol: string, exchange: string) =>
    post<NewsSentimentData>('/api/v1/agent/news-sentiment', { apikey, symbol, exchange }),

  dailyReport: (apikey: string, exchange: string, symbols?: string[]) =>
    post<DailyReportData>('/api/v1/agent/daily-report', { apikey, exchange, symbols }),

  research: (apikey: string, symbol: string, exchange: string, question?: string) =>
    post<ResearchReportData>('/api/v1/agent/research', { apikey, symbol, exchange, question }),

  rlSignal: (apikey: string, symbol: string, exchange: string, algo = 'ppo') =>
    post<RLSignalData>('/api/v1/agent/rl-signal', { apikey, symbol, exchange, algo }),

  portfolioCVaR: (apikey: string, symbols: string[], exchange = 'NSE') =>
    post<PortfolioCVaRData>('/api/v1/agent/portfolio-cvar', { apikey, symbols, exchange }),
}
