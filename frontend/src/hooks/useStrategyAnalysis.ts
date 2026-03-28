import { useQuery } from '@tanstack/react-query'
import { strategyApi } from '@/api/strategy-analysis'
import { useApiKey } from './useAIAnalysis'

export function useFibonacci(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['strategy-fibonacci', symbol, exchange, interval],
    queryFn: () => strategyApi.fibonacci(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useHarmonic(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['strategy-harmonic', symbol, exchange, interval],
    queryFn: () => strategyApi.harmonic(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useElliottWave(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['strategy-elliott', symbol, exchange, interval],
    queryFn: () => strategyApi.elliottWave(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useSmartMoneyDetail(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['strategy-smc', symbol, exchange, interval],
    queryFn: () => strategyApi.smartMoney(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useHedgeStrategy(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['strategy-hedge', symbol, exchange, interval],
    queryFn: () => strategyApi.hedgeStrategy(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useStrategyDecision(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['strategy-decision', symbol, exchange, interval],
    queryFn: () => strategyApi.strategyDecision(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useMultiTimeframe(symbol: string, exchange: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['multi-timeframe', symbol, exchange],
    queryFn: () => strategyApi.multiTimeframe(apikey!, symbol, exchange),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function usePatterns(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['patterns', symbol, exchange, interval],
    queryFn: () => strategyApi.patterns(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useSupportResistance(symbol: string, exchange: string, interval: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['support-resistance', symbol, exchange, interval],
    queryFn: () => strategyApi.supportResistance(apikey!, symbol, exchange, interval),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
  })
}

export function useNewsSentiment(symbol: string, exchange: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['news-sentiment', symbol, exchange],
    queryFn: () => strategyApi.newsSentiment(apikey!, symbol, exchange),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 120_000, // 2 min cache — news doesn't change every second
  })
}

export function useDailyReport(exchange: string, symbols?: string[], enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['daily-report', exchange, symbols],
    queryFn: () => strategyApi.dailyReport(apikey!, exchange, symbols),
    enabled: enabled && !!apikey,
    staleTime: 300_000,
  })
}

export function useResearch(symbol: string, exchange: string, question: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['research', symbol, exchange, question],
    queryFn: () => strategyApi.research(apikey!, symbol, exchange, question),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 120_000,
  })
}

export function useRLSignal(symbol: string, exchange: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['rl-signal', symbol, exchange],
    queryFn: () => strategyApi.rlSignal(apikey!, symbol, exchange),
    enabled: enabled && !!apikey && !!symbol,
    staleTime: 60_000,
    retry: false,
  })
}

export function usePortfolioCVaR(symbols: string[], exchange: string, enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['portfolio-cvar', symbols.join(','), exchange],
    queryFn: () => strategyApi.portfolioCVaR(apikey!, symbols, exchange),
    enabled: enabled && !!apikey && symbols.length >= 2,
    staleTime: 5 * 60_000,
    retry: false,
  })
}
