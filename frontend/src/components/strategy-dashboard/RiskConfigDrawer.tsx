import { useEffect, useState } from 'react'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { dashboardApi } from '@/api/strategy-dashboard'
import { showToast } from '@/utils/toast'
import type { RiskConfig } from '@/types/strategy-dashboard'

interface RiskConfigDrawerProps {
  open: boolean
  onClose: () => void
  strategyId: number
  strategyType: string
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
  onTypeChange: (v: string) => void
  onNumChange: (v: number | null) => void
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <div className="flex gap-2">
        <Select value={typeValue || ''} onValueChange={onTypeChange}>
          <SelectTrigger className="w-[120px] h-8 text-xs">
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

export function RiskConfigDrawer({
  open,
  onClose,
  strategyId,
  strategyType,
}: RiskConfigDrawerProps) {
  const [config, setConfig] = useState<RiskConfig | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      dashboardApi.getRiskConfig(strategyId, strategyType).then(setConfig).catch(() => {})
    }
  }, [open, strategyId, strategyType])

  const update = (field: keyof RiskConfig, value: unknown) => {
    if (config) {
      setConfig({ ...config, [field]: value || null })
    }
  }

  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    try {
      await dashboardApi.updateRiskConfig(strategyId, strategyType, config)
      showToast.success('Risk config updated')
      onClose()
    } catch {
      showToast.error('Failed to save risk config')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent className="w-[360px] sm:w-[400px]">
        <SheetHeader>
          <SheetTitle>Risk Configuration</SheetTitle>
        </SheetHeader>
        {config ? (
          <div className="space-y-4 mt-4">
            <RiskField
              label="Stop Loss"
              typeValue={config.default_stoploss_type}
              numValue={config.default_stoploss_value}
              onTypeChange={(v) => update('default_stoploss_type', v)}
              onNumChange={(v) => update('default_stoploss_value', v)}
            />
            <RiskField
              label="Target"
              typeValue={config.default_target_type}
              numValue={config.default_target_value}
              onTypeChange={(v) => update('default_target_type', v)}
              onNumChange={(v) => update('default_target_value', v)}
            />
            <RiskField
              label="Trailing Stop"
              typeValue={config.default_trailstop_type}
              numValue={config.default_trailstop_value}
              onTypeChange={(v) => update('default_trailstop_type', v)}
              onNumChange={(v) => update('default_trailstop_value', v)}
            />
            <RiskField
              label="Breakeven"
              typeValue={config.default_breakeven_type}
              numValue={config.default_breakeven_threshold}
              onTypeChange={(v) => update('default_breakeven_type', v)}
              onNumChange={(v) => update('default_breakeven_threshold', v)}
            />
            <div className="space-y-1.5">
              <Label className="text-xs">Auto Squareoff Time</Label>
              <Input
                type="time"
                className="h-8 text-xs"
                value={config.auto_squareoff_time || '15:15'}
                onChange={(e) => update('auto_squareoff_time', e.target.value)}
              />
            </div>
            <div className="pt-4">
              <Button onClick={handleSave} disabled={saving} className="w-full">
                {saving ? 'Saving...' : 'Save Changes'}
              </Button>
            </div>
          </div>
        ) : (
          <div className="py-8 text-center text-sm text-muted-foreground">Loading...</div>
        )}
      </SheetContent>
    </Sheet>
  )
}
