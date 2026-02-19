import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { builderApi } from '@/api/strategy-builder'
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
  const [step, setStep] = useState<BuilderStep>('basics')
  const [basics, setBasics] = useState<BuilderBasics>({ ...DEFAULT_BUILDER_BASICS })
  const [legs, setLegs] = useState<BuilderLeg[]>([])
  const [riskConfig, setRiskConfig] = useState<BuilderRiskConfig>({ ...DEFAULT_RISK_CONFIG })
  const [preset, setPreset] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload = {
        basics,
        legs: legs.map(({ id: _id, ...rest }) => rest),
        riskConfig,
        preset,
      }
      const result = await builderApi.saveStrategy(payload)
      if (result.status === 'success') {
        showToast.success('Strategy saved successfully')
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

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold mb-1">Strategy Builder</h1>
        <p className="text-sm text-muted-foreground">Build F&O multi-leg strategies with a visual wizard</p>
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
