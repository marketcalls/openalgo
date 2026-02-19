import type { BuilderBasics, BuilderLeg, BuilderRiskConfig } from '@/types/strategy-builder'
import { webClient } from './client'

interface SaveBuilderPayload {
  basics: BuilderBasics
  legs: Omit<BuilderLeg, 'id'>[]
  riskConfig: BuilderRiskConfig
  preset: string | null
}

interface SaveResponse {
  status: 'success' | 'error'
  message?: string
  data?: { strategy_id: number; webhook_id: string }
}

interface ExecuteResponse {
  status: 'success' | 'error'
  message?: string
  data?: { results: { leg: number; status: string; orderid?: string; message?: string }[] }
}

export const builderApi = {
  saveStrategy: async (payload: SaveBuilderPayload): Promise<SaveResponse> => {
    const res = await webClient.post<SaveResponse>('/strategy/api/builder/save', payload)
    return res.data
  },

  executeStrategy: async (strategyId: number): Promise<ExecuteResponse> => {
    const res = await webClient.post<ExecuteResponse>(`/strategy/api/builder/${strategyId}/execute`)
    return res.data
  },
}
