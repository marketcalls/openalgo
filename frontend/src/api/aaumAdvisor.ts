import {
  AnalysisResultSchema,
  type AnalysisResult,
  type ConfigResult,
  type ExecuteResult,
  type HealthResult,
} from '@/types/aaum'
import { apiClient } from './client'

/**
 * AAUM Intelligence API client.
 * All endpoints use apiClient (Flask RESTX namespace, session auth).
 *
 * - analyze: Long-running (30-90s), read-only + Zod validation
 * - execute: Triggers order via AAUM -> OpenAlgo placeorder
 * - health: Lightweight probe of Colab + local backends
 * - configure: Set AAUM URL at runtime (no restart)
 *
 * CRITICAL: analyze() accepts AbortSignal for cancellation on unmount.
 */
export const aaumApi = {
  /**
   * Run full 12-layer analysis.
   * Takes 30-90 seconds. MUST pass AbortSignal for lifecycle management.
   * Response is Zod-validated (9 LLM agents can individually fail).
   */
  analyze: async (symbol: string, signal?: AbortSignal): Promise<AnalysisResult> => {
    const response = await apiClient.post(
      '/aaum/analyze',
      { symbol },
      { signal, timeout: 600_000 }, // 10 min timeout (9 agents + data collection)
    )
    // Runtime validation — catches malformed agent outputs
    return AnalysisResultSchema.parse(response.data)
  },

  /**
   * Execute trade recommendation.
   * Uses apiClient — goes through Flask RESTX namespace.
   * The AAUM sidecar calls placeorder with its own API key.
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

  /**
   * Health check for AAUM backend.
   * Probes both Colab tunnel and localhost, returns reachability of each.
   * Used for the status badge in the toolbar.
   */
  health: async (): Promise<HealthResult> => {
    const response = await apiClient.get<HealthResult>('/aaum/health')
    return response.data
  },

  /**
   * Configure AAUM backend URL at runtime (no Flask restart needed).
   * Use this to point at a new Colab/ngrok tunnel URL.
   */
  configure: async (url: string): Promise<ConfigResult> => {
    const response = await apiClient.post<ConfigResult>('/aaum/config', { url })
    return response.data
  },
}
