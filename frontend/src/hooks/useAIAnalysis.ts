// frontend/src/hooks/useAIAnalysis.ts
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { aiAnalysisApi } from '@/api/ai-analysis'
import type { AIAnalysisResult, ScanResult, AIAgentStatus } from '@/types/ai-analysis'

/** Fetch AI analysis for a single symbol */
export function useAIAnalysis(
  symbol: string,
  exchange: string = 'NSE',
  interval: string = '1d',
  enabled: boolean = true,
) {
  const apiKey = useAuthStore((s) => s.apiKey)

  return useQuery<AIAnalysisResult | null>({
    queryKey: ['ai-analysis', symbol, exchange, interval],
    queryFn: async () => {
      if (!apiKey) return null
      const response = await aiAnalysisApi.analyzeSymbol(apiKey, symbol, exchange, interval)
      if (response.status === 'error') throw new Error(response.message || 'Analysis failed')
      return response.data ?? null
    },
    enabled: enabled && !!apiKey && !!symbol,
    staleTime: 60_000, // 1 minute (matches existing pattern)
    refetchOnWindowFocus: true,
  })
}

/** Scan multiple symbols */
export function useAIScan(
  symbols: string[],
  exchange: string = 'NSE',
  interval: string = '1d',
  enabled: boolean = true,
) {
  const apiKey = useAuthStore((s) => s.apiKey)

  return useQuery<ScanResult[]>({
    queryKey: ['ai-scan', symbols, exchange, interval],
    queryFn: async () => {
      if (!apiKey) return []
      const response = await aiAnalysisApi.scanSymbols(apiKey, symbols, exchange, interval)
      if (response.status === 'error') throw new Error(response.message || 'Scan failed')
      return response.data ?? []
    },
    enabled: enabled && !!apiKey && symbols.length > 0,
    staleTime: 60_000,
  })
}

/** Check AI agent status */
export function useAIStatus() {
  return useQuery<AIAgentStatus | null>({
    queryKey: ['ai-status'],
    queryFn: async () => {
      const response = await aiAnalysisApi.getStatus()
      return response.data ?? null
    },
    staleTime: 300_000, // 5 minutes
  })
}
