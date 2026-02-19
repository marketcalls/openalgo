import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { BuilderRiskConfig } from '@/types/strategy-builder'

interface RiskConfigStepProps {
  config: BuilderRiskConfig
  onChange: (config: BuilderRiskConfig) => void
  onBack: () => void
  onNext: () => void
}

const RISK_TYPES = [
  { value: '', label: 'Disabled' },
  { value: 'percentage', label: 'Percentage' },
  { value: 'points', label: 'Points' },
]

function RiskField({
  label,
  typeValue,
  numValue,
  onTypeChange,
  onNumChange,
}: {
  label: string
  typeValue: string | null
  numValue: number | null
  onTypeChange: (v: string | null) => void
  onNumChange: (v: number | null) => void
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <div className="flex gap-2">
        <Select value={typeValue || ''} onValueChange={(v) => onTypeChange(v || null)}>
          <SelectTrigger className="w-[130px] h-8 text-xs">
            <SelectValue placeholder="Disabled" />
          </SelectTrigger>
          <SelectContent>
            {RISK_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          type="number"
          step="0.01"
          className="h-8 text-xs"
          value={numValue ?? ''}
          disabled={!typeValue}
          onChange={(e) => onNumChange(e.target.value ? Number(e.target.value) : null)}
        />
      </div>
    </div>
  )
}

export function RiskConfigStep({ config, onChange, onBack, onNext }: RiskConfigStepProps) {
  const update = <K extends keyof BuilderRiskConfig>(key: K, value: BuilderRiskConfig[K]) =>
    onChange({ ...config, [key]: value })

  return (
    <div className="max-w-lg mx-auto space-y-5">
      <Tabs
        value={config.risk_mode}
        onValueChange={(v) => update('risk_mode', v as 'per_leg' | 'combined')}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Risk Mode</h3>
          <TabsList>
            <TabsTrigger value="combined" className="text-xs">Combined</TabsTrigger>
            <TabsTrigger value="per_leg" className="text-xs">Per Leg</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="combined" className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Combined risk applies to the net premium of all legs together.
          </p>
          <RiskField
            label="Combined Stop Loss"
            typeValue={config.combined_stoploss_type}
            numValue={config.combined_stoploss_value}
            onTypeChange={(v) => update('combined_stoploss_type', v)}
            onNumChange={(v) => update('combined_stoploss_value', v)}
          />
          <RiskField
            label="Combined Target"
            typeValue={config.combined_target_type}
            numValue={config.combined_target_value}
            onTypeChange={(v) => update('combined_target_type', v)}
            onNumChange={(v) => update('combined_target_value', v)}
          />
          <RiskField
            label="Combined Trailing Stop"
            typeValue={config.combined_trailstop_type}
            numValue={config.combined_trailstop_value}
            onTypeChange={(v) => update('combined_trailstop_type', v)}
            onNumChange={(v) => update('combined_trailstop_value', v)}
          />
        </TabsContent>

        <TabsContent value="per_leg" className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Per-leg risk applies to each leg individually. Configure defaults here —
            override per leg in the Legs step.
          </p>
          <RiskField
            label="Default Stop Loss"
            typeValue={config.default_stoploss_type}
            numValue={config.default_stoploss_value}
            onTypeChange={(v) => update('default_stoploss_type', v)}
            onNumChange={(v) => update('default_stoploss_value', v)}
          />
          <RiskField
            label="Default Target"
            typeValue={config.default_target_type}
            numValue={config.default_target_value}
            onTypeChange={(v) => update('default_target_type', v)}
            onNumChange={(v) => update('default_target_value', v)}
          />
          <RiskField
            label="Default Trailing Stop"
            typeValue={config.default_trailstop_type}
            numValue={config.default_trailstop_value}
            onTypeChange={(v) => update('default_trailstop_type', v)}
            onNumChange={(v) => update('default_trailstop_value', v)}
          />
          <RiskField
            label="Breakeven Threshold"
            typeValue={config.default_breakeven_type}
            numValue={config.default_breakeven_threshold}
            onTypeChange={(v) => update('default_breakeven_type', v)}
            onNumChange={(v) => update('default_breakeven_threshold', v)}
          />
        </TabsContent>
      </Tabs>

      <div className="flex justify-between pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button onClick={onNext}>Next: Review</Button>
      </div>
    </div>
  )
}
