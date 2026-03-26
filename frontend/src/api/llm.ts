import { apiClient } from './client'
import type { LLMCommentaryResponse } from '@/types/llm'

export const llmApi = {
  getCommentary: async (apiKey: string, analysis: Record<string, unknown>): Promise<LLMCommentaryResponse> => {
    const response = await apiClient.post<LLMCommentaryResponse>('/llm/commentary', {
      apikey: apiKey,
      analysis,
    })
    return response.data
  },

  getModels: async () => {
    const response = await apiClient.get('/llm/models')
    return response.data
  },
}
