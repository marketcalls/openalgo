import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { builderApi } from '@/api/strategy-builder'
import { strategyApi } from '@/api/strategy'
import { dashboardApi } from '@/api/strategy-dashboard'
import { showToast } from '@/utils/toast'
import type {
  BuilderBasics,
  BuilderLeg,
  BuilderRiskConfig,
  BuilderStep,
} from '@/types/strategy-builder'
import { DEFAULT_BUILDER_BASICS, DEFAULT_RISK_CONFIG } from '@/types/strategy-builder'
import { BuilderStepper } from '@/components/strategy-builder/BuilderStepper'
import { BasicsStep } from '@/components/strategy-builder/BasicsStep'
import { LegsStep } from '@/components/strategy-builder/LegsStep'
import { RiskConfigStep } from '@/components/strategy-builder/RiskConfigStep'
import { ReviewStep } from '@/components/strategy-builder/ReviewStep'

export default function StrategyBuilder() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isEditMode = !!id

  const [step, setStep] = useState<BuilderStep>('basics')
  const [basics, setBasics] = useState<BuilderBasics>({ ...DEFAULT_BUILDER_BASICS })
  const [legs, setLegs] = useState<BuilderLeg[]>([])
  const [riskConfig, setRiskConfig] = useState<BuilderRiskConfig>({ ...DEFAULT_RISK_CONFIG })
  const [preset, setPreset] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)

  // Load existing strategy for edit mode
  useEffect(() => {
    if (!id) return
    let cancelled = false
    const loadStrategy = async () => {
      setLoading(true)
      try {
        const strategyId = Number(id)
        const [stratData, riskData] = await Promise.all([
          strategyApi.getStrategy(strategyId),
          dashboardApi.getRiskConfig(strategyId, 'builder').catch(() => null),
        ])

        if (cancelled) return

        const s = stratData.strategy
        const mapping = stratData.mappings[0]
        setBasics({
          name: s.name || '',
          exchange: (mapping?.exchange as BuilderBasics['exchange']) || 'NFO',
          underlying: mapping?.symbol || 'NIFTY',
          expiry_type: (mapping?.expiry_type as BuilderBasics['expiry_type']) || 'current_week',
          product_type: (mapping?.product_type as 'MIS' | 'NRML') || 'MIS',
          is_intraday: s.is_intraday ?? true,
          trading_mode: s.trading_mode || 'BOTH',
        })

        // Load legs from mapping's legs_config JSON
        if (mapping?.legs_config) {
          try {
            const parsed = typeof mapping.legs_config === 'string'
              ? JSON.parse(mapping.legs_config)
              : mapping.legs_config
            if (Array.isArray(parsed)) {
              setLegs(parsed.map((leg: Record<string, unknown>, i: number) => ({
                id: `leg-${i}-${Date.now()}`,
                leg_type: (leg.leg_type as 'option' | 'future') || 'option',
                action: (leg.action as 'BUY' | 'SELL') || 'SELL',
                option_type: (leg.option_type as 'CE' | 'PE' | null) ?? null,
                strike_type: (leg.strike_type as BuilderLeg['strike_type']) || 'ATM',
                offset: (leg.offset as string) || 'ATM',
                expiry_type: (leg.expiry_type as BuilderLeg['expiry_type']) || 'current_week',
                product_type: (leg.product_type as 'MIS' | 'NRML') || 'MIS',
                quantity_lots: (leg.quantity_lots as number) || 1,
                order_type: (leg.order_type as 'MARKET' | 'LIMIT') || 'MARKET',
                stoploss_type: (leg.stoploss_type as string) || null,
                stoploss_value: (leg.stoploss_value as number) || null,
                target_type: (leg.target_type as string) || null,
                target_value: (leg.target_value as number) || null,
              })))
            }
          } catch {
            // legs_config not valid JSON — leave legs empty
          }
        }

        if (mapping?.preset) {
          setPreset(mapping.preset)
        }

        if (riskData) {
          setRiskConfig({
            ...DEFAULT_RISK_CONFIG,
            default_stoploss_type: riskData.default_stoploss_type,
            default_stoploss_value: riskData.default_stoploss_value,
            default_target_type: riskData.default_target_type,
            default_target_value: riskData.default_target_value,
            default_trailstop_type: riskData.default_trailstop_type,
            default_trailstop_value: riskData.default_trailstop_value,
            default_breakeven_type: riskData.default_breakeven_type,
            default_breakeven_threshold: riskData.default_breakeven_threshold,
          })
        }
      } catch {
        showToast.error('Failed to load strategy')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadStrategy()
    return () => { cancelled = true }
  }, [id])

  const handleSave = async (opts?: { saveAsTemplate?: boolean }) => {
    setSaving(true)
    try {
      const payload = {
        basics,
        legs: legs.map(({ id: _id, ...rest }) => rest),
        riskConfig,
        preset,
        saveAsTemplate: opts?.saveAsTemplate,
        ...(isEditMode ? { strategy_id: Number(id) } : {}),
      }
      const result = await builderApi.saveStrategy(payload)
      if (result.status === 'success') {
        showToast.success(isEditMode ? 'Strategy updated' : 'Strategy saved successfully')
        navigate('/strategy/hub')
      } else {
        showToast.error(result.message || 'Failed to save strategy')
      }
    } catch {
      showToast.error('Failed to save strategy')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading strategy...</p>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold mb-1">
          {isEditMode ? 'Edit Strategy' : 'Strategy Builder'}
        </h1>
        <p className="text-sm text-muted-foreground">
          {isEditMode
            ? 'Modify your F&O multi-leg strategy'
            : 'Build F&O multi-leg strategies with a visual wizard'}
        </p>
      </div>

      <BuilderStepper currentStep={step} onStepClick={setStep} />

      <Card>
        <CardContent className="p-6">
          {step === 'basics' && (
            <BasicsStep
              basics={basics}
              onChange={setBasics}
              onNext={() => setStep('legs')}
            />
          )}
          {step === 'legs' && (
            <LegsStep
              legs={legs}
              onChange={setLegs}
              onPresetSelect={setPreset}
              onBack={() => setStep('basics')}
              onNext={() => setStep('risk')}
            />
          )}
          {step === 'risk' && (
            <RiskConfigStep
              config={riskConfig}
              onChange={setRiskConfig}
              onBack={() => setStep('legs')}
              onNext={() => setStep('review')}
            />
          )}
          {step === 'review' && (
            <ReviewStep
              basics={basics}
              legs={legs}
              riskConfig={riskConfig}
              preset={preset}
              saving={saving}
              onBack={() => setStep('risk')}
              onSave={handleSave}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
