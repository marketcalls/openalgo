import { Loader2, Settings } from 'lucide-react'
import { useEffect, useState } from 'react'
import { showToast } from '@/utils/toast'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { DashboardStrategy, RiskConfigUpdate } from '@/types/strategy-dashboard'

interface RiskConfigDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  strategy: DashboardStrategy
  onSaved: () => void
}

type RiskType = 'percentage' | 'points' | null

interface RiskField {
  type: RiskType
  value: string
}

export function RiskConfigDrawer({
  open,
  onOpenChange,
  strategy,
  onSaved,
}: RiskConfigDrawerProps) {
  const [saving, setSaving] = useState(false)
  const [stoploss, setStoploss] = useState<RiskField>({ type: null, value: '' })
  const [target, setTarget] = useState<RiskField>({ type: null, value: '' })
  const [trailstop, setTrailstop] = useState<RiskField>({ type: null, value: '' })
  const [breakeven, setBreakeven] = useState<RiskField>({ type: null, value: '' })
  const [exitExecution, setExitExecution] = useState('market')
  const [autoSquareoff, setAutoSquareoff] = useState('')

  // Pre-populate from strategy
  useEffect(() => {
    if (!open) return
    setStoploss({
      type: (strategy.default_stoploss_type as RiskType) ?? null,
      value: strategy.default_stoploss_value?.toString() ?? '',
    })
    setTarget({
      type: (strategy.default_target_type as RiskType) ?? null,
      value: strategy.default_target_value?.toString() ?? '',
    })
    setTrailstop({
      type: (strategy.default_trailstop_type as RiskType) ?? null,
      value: strategy.default_trailstop_value?.toString() ?? '',
    })
    setBreakeven({
      type: (strategy.default_breakeven_type as RiskType) ?? null,
      value: strategy.default_breakeven_threshold?.toString() ?? '',
    })
    setExitExecution(strategy.default_exit_execution || 'market')
    setAutoSquareoff(strategy.auto_squareoff_time ?? '')
  }, [open, strategy])

  const handleSave = async () => {
    setSaving(true)
    try {
      const config: RiskConfigUpdate = {
        default_stoploss_type: stoploss.type,
        default_stoploss_value: stoploss.type && stoploss.value ? Number(stoploss.value) : null,
        default_target_type: target.type,
        default_target_value: target.type && target.value ? Number(target.value) : null,
        default_trailstop_type: trailstop.type,
        default_trailstop_value: trailstop.type && trailstop.value ? Number(trailstop.value) : null,
        default_breakeven_type: breakeven.type,
        default_breakeven_threshold: breakeven.type && breakeven.value ? Number(breakeven.value) : null,
        default_exit_execution: exitExecution,
        auto_squareoff_time: autoSquareoff || null,
      }

      const res = await strategyDashboardApi.updateRiskConfig(strategy.id, config)
      if (res.status === 'success') {
        showToast.success('Risk configuration updated', 'strategyRisk')
        onSaved()
        onOpenChange(false)
      } else {
        showToast.error(res.message || 'Failed to update', 'strategyRisk')
      }
    } catch {
      showToast.error('Failed to update risk configuration', 'strategyRisk')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-[500px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            Risk Configuration
          </SheetTitle>
          <SheetDescription>
            {strategy.name} — Default risk parameters for new positions
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Stoploss */}
          <RiskFieldGroup
            label="Stoploss"
            field={stoploss}
            onChange={setStoploss}
          />

          <Separator />

          {/* Target */}
          <RiskFieldGroup
            label="Target"
            field={target}
            onChange={setTarget}
          />

          <Separator />

          {/* Trailing Stop */}
          <RiskFieldGroup
            label="Trailing Stop"
            field={trailstop}
            onChange={setTrailstop}
          />

          <Separator />

          {/* Breakeven */}
          <RiskFieldGroup
            label="Breakeven Threshold"
            field={breakeven}
            onChange={setBreakeven}
          />

          <Separator />

          {/* Exit Execution */}
          <div className="space-y-2">
            <Label>Exit Execution</Label>
            <Tabs value={exitExecution} onValueChange={setExitExecution}>
              <TabsList className="grid w-full grid-cols-1">
                <TabsTrigger value="market">Market</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {/* Auto Square-Off */}
          <div className="space-y-2">
            <Label>Auto Square-Off Time</Label>
            <Input
              type="time"
              value={autoSquareoff}
              onChange={(e) => setAutoSquareoff(e.target.value)}
              placeholder="15:15"
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to disable auto square-off
            </p>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-4">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Save Changes
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}

// ── Sub-component for each risk type selector ──────

function RiskFieldGroup({
  label,
  field,
  onChange,
}: {
  label: string
  field: RiskField
  onChange: (field: RiskField) => void
}) {
  const typeValue = field.type ?? 'none'

  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Tabs
        value={typeValue}
        onValueChange={(v) =>
          onChange({ ...field, type: v === 'none' ? null : (v as RiskType) })
        }
      >
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="percentage">Percentage</TabsTrigger>
          <TabsTrigger value="points">Points</TabsTrigger>
          <TabsTrigger value="none">None</TabsTrigger>
        </TabsList>
      </Tabs>
      {field.type && (
        <Input
          type="number"
          step="0.01"
          min="0"
          value={field.value}
          onChange={(e) => onChange({ ...field, value: e.target.value })}
          placeholder={field.type === 'percentage' ? '2.0' : '50'}
          className="font-mono"
        />
      )}
    </div>
  )
}
