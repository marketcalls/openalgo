export interface LLMCommentaryResponse {
  status: 'success' | 'error'
  message?: string
  data?: {
    commentary: string
    provider: string
    model: string
  }
}

export interface LLMModel {
  id: string
  name: string
  provider: string
  type: string
  enabled: boolean
}
