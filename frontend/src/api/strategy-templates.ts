// Strategy Templates API — client-side constants + deploy via builder endpoint

import type { PresetDefinition, BuilderBasics, BuilderExchange, BuilderRiskConfig } from '@/types/strategy-builder'
import { PRESETS } from '@/components/strategy-builder/PresetSelector'
import { builderApi } from './strategy-builder'
import { DEFAULT_RISK_CONFIG } from '@/types/strategy-builder'

export { PRESETS as STRATEGY_TEMPLATES }

export const templatesApi = {
  /** Get all available templates (client-side constants) */
  getTemplates: () => PRESETS,

  /** Get a single template by ID */
  getTemplate: (id: string) => PRESETS.find((p) => p.id === id) ?? null,

  /** Deploy a template as a new strategy via builder save endpoint */
  deployTemplate: async (
    template: PresetDefinition,
    config: {
      name: string
      exchange: BuilderExchange
      underlying: string
      expiry_type: string
      product_type: string
      lots: number
    }
  ) => {
    const basics: BuilderBasics = {
      name: config.name,
      exchange: config.exchange,
      underlying: config.underlying,
      expiry_type: config.expiry_type as BuilderBasics['expiry_type'],
      product_type: config.product_type as 'MIS' | 'NRML',
      is_intraday: config.product_type === 'MIS',
      trading_mode: 'BOTH',
    }

    const legs = template.legs.map((leg) => ({
      ...leg,
      quantity_lots: config.lots,
    }))

    const riskConfig: BuilderRiskConfig = { ...DEFAULT_RISK_CONFIG }

    return builderApi.saveStrategy({
      basics,
      legs,
      riskConfig,
      preset: template.id,
    })
  },
}
