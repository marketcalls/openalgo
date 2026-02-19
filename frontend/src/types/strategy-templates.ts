// Strategy Templates Types

import type { BuilderLeg } from './strategy-builder'

export interface TemplateDefinition {
  id: string
  name: string
  description: string
  category: 'neutral' | 'bullish' | 'bearish'
  legs: Omit<BuilderLeg, 'id'>[]
}

export interface DeployTemplatePayload {
  name: string
  exchange: 'NFO' | 'BFO'
  underlying: string
  expiry_type: string
  lots: number
  template_id: string
}
