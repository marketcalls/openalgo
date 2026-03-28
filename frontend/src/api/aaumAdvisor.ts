/**
 * AAUM Intelligence API client.
 *
 * Uses apiClient (baseURL /api/v1, withCredentials: true — session auth).
 * All 3 UI-facing endpoints: analyze, execute, health.
 *
 * CRITICAL: analyze() accepts AbortSignal for cancellation.
 * Pass one from an AbortController ref to cancel on unmount/re-analyze.
 * This prevents orphaned 30-90s Ollama slots on the AAUM sidecar.
 */
import type { AnalysisResult, ExecuteResult, HealthResult } from '@/types/aaum'
import { AnalysisResultSchema } from '@/types/aaum'
import { apiClient } from './client'

export const aaumApi = {
  /**
   * Run full 12-layer analysis.
   * Takes 30–90 seconds. MUST pass AbortSignal for lifecycle management.
   * Zod validates response — 9 LLM agents can individually fail with partial output.
   */
  analyze: async (symbol: string, signal?: AbortSignal): Promise<AnalysisResult> => {
    const response = await apiClient.post(
      '/aaum/analyze',
      { symbol },
      { signal, timeout: 150_000 }, // 2.5 min = 90s analysis + 60s buffer
    )
    return AnalysisResultSchema.parse(response.data)
  },

  /**
   * Execute trade recommendation.
   * paper=true → safe paper trade (Phase 1 default).
   * paper=false → REAL order via AAUM → OpenAlgo → broker (Phase 2+).
   */
  execute: async (
    symbol: string,
    paper: boolean,
    analysis_id?: string,
  ): Promise<ExecuteResult> => {
    const response = await apiClient.post<ExecuteResult>('/aaum/execute', {
      symbol,
      paper,
      analysis_id,
    })
    return response.data
  },

  /** Sidecar health — called by useQuery every 30s. Timeout: 5s. */
  health: async (): Promise<HealthResult> => {
    const response = await apiClient.get<HealthResult>('/aaum/health')
    return response.data
  },
}
