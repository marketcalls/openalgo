import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import type { BuilderBasics, BuilderLeg, BuilderRiskConfig } from '@/types/strategy-builder'

interface ReviewStepProps {
  basics: BuilderBasics
  legs: BuilderLeg[]
  riskConfig: BuilderRiskConfig
  preset: string | null
  saving: boolean
  onBack: () => void
  onSave: (opts?: { saveAsTemplate?: boolean }) => void
}

export function ReviewStep({
  basics,
  legs,
  riskConfig,
  preset,
  saving,
  onBack,
  onSave,
}: ReviewStepProps) {
  const [saveAsTemplate, setSaveAsTemplate] = useState(false)

  return (
    <div className="max-w-lg mx-auto space-y-4">
      {/* Basics Summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Strategy Basics</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Name</span>
            <span className="font-medium">{basics.name}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Exchange</span>
            <span>{basics.exchange}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Underlying</span>
            <span>{basics.underlying}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Expiry</span>
            <span className="capitalize">{basics.expiry_type.replace('_', ' ')}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Product</span>
            <span>{basics.product_type}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Type</span>
            <span>{basics.is_intraday ? 'Intraday' : 'Positional'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Mode</span>
            <span>{basics.trading_mode}</span>
          </div>
        </CardContent>
      </Card>

      {/* Legs Summary */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">Legs ({legs.length})</CardTitle>
            {preset && (
              <Badge variant="secondary" className="text-[10px]">
                {preset.replace('_', ' ')}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-1.5">
            {legs.map((leg, idx) => (
              <div key={leg.id} className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground w-8">L{idx + 1}</span>
                <span className={leg.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>
                  {leg.action}
                </span>
                <span>{leg.option_type || 'FUT'}</span>
                <span className="text-muted-foreground">{leg.offset}</span>
                <span>x{leg.quantity_lots}</span>
                <span className="text-muted-foreground">{leg.expiry_type.replace('_', ' ')}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Risk Summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Risk Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Mode</span>
            <span className="capitalize">{riskConfig.risk_mode.replace('_', ' ')}</span>
          </div>
          {riskConfig.risk_mode === 'combined' ? (
            <>
              <div className="flex justify-between">
                <span className="text-muted-foreground">SL</span>
                <span>
                  {riskConfig.combined_stoploss_type
                    ? `${riskConfig.combined_stoploss_value} ${riskConfig.combined_stoploss_type}`
                    : 'Disabled'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">TGT</span>
                <span>
                  {riskConfig.combined_target_type
                    ? `${riskConfig.combined_target_value} ${riskConfig.combined_target_type}`
                    : 'Disabled'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">TSL</span>
                <span>
                  {riskConfig.combined_trailstop_type
                    ? `${riskConfig.combined_trailstop_value} ${riskConfig.combined_trailstop_type}`
                    : 'Disabled'}
                </span>
              </div>
            </>
          ) : (
            <>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Default SL</span>
                <span>
                  {riskConfig.default_stoploss_type
                    ? `${riskConfig.default_stoploss_value} ${riskConfig.default_stoploss_type}`
                    : 'Disabled'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Default TGT</span>
                <span>
                  {riskConfig.default_target_type
                    ? `${riskConfig.default_target_value} ${riskConfig.default_target_type}`
                    : 'Disabled'}
                </span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Save as Template Option */}
      <div className="flex items-center gap-2 px-1">
        <Checkbox
          id="save-as-template"
          checked={saveAsTemplate}
          onCheckedChange={(v) => setSaveAsTemplate(v === true)}
        />
        <Label htmlFor="save-as-template" className="text-xs cursor-pointer">
          Also save as reusable template
        </Label>
      </div>

      <div className="flex justify-between pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button onClick={() => onSave({ saveAsTemplate })} disabled={saving}>
          {saving ? 'Saving...' : 'Save Strategy'}
        </Button>
      </div>
    </div>
  )
}
