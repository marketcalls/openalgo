// Strategy Templates API — backend-powered CRUD + deploy

import type { BuilderExchange } from '@/types/strategy-builder'
import { webClient } from './client'

const BASE = '/strategy/api'

interface ApiResponse<T> {
  status: 'success' | 'error'
  message?: string
  data: T
}

export interface StrategyTemplate {
  id: number
  name: string
  description: string | null
  category: 'neutral' | 'bullish' | 'bearish'
  preset: string | null
  legs_config: Record<string, unknown>[]
  risk_config: Record<string, unknown> | null
  is_system: boolean
  created_by: string | null
  created_at: string | null
}

export const templatesApi = {
  /** Get all available templates */
  getTemplates: async (category?: string): Promise<StrategyTemplate[]> => {
    const params = category ? `?category=${category}` : ''
    const res = await webClient.get<ApiResponse<StrategyTemplate[]>>(`${BASE}/templates${params}`)
    return res.data.data
  },

  /** Get a single template by ID */
  getTemplate: async (id: number): Promise<StrategyTemplate> => {
    const res = await webClient.get<ApiResponse<StrategyTemplate>>(`${BASE}/templates/${id}`)
    return res.data.data
  },

  /** Create a user template */
  createTemplate: async (data: {
    name: string
    description?: string
    category?: string
    preset?: string
    legs_config: Record<string, unknown>[]
    risk_config?: Record<string, unknown>
  }): Promise<StrategyTemplate> => {
    const res = await webClient.post<ApiResponse<StrategyTemplate>>(`${BASE}/templates`, data)
    return res.data.data
  },

  /** Delete a user template */
  deleteTemplate: async (id: number): Promise<void> => {
    await webClient.delete(`${BASE}/templates/${id}`)
  },

  /** Deploy a template as a new strategy */
  deployTemplate: async (
    templateId: number,
    config: {
      name: string
      exchange: BuilderExchange
      underlying: string
      expiry_type: string
      product_type: string
      lots: number
      default_stoploss_type?: string | null
      default_stoploss_value?: number | null
      default_target_type?: string | null
      default_target_value?: number | null
    }
  ): Promise<{ strategy_id: number; webhook_id: string }> => {
    const res = await webClient.post<ApiResponse<{ strategy_id: number; webhook_id: string }>>(
      `${BASE}/templates/${templateId}/deploy`,
      config
    )
    return res.data.data
  },
}
