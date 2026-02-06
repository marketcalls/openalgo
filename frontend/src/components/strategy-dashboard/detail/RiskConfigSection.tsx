import { Loader2, ShieldAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { showToast } from '@/utils/toast'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { RiskFieldGroup } from './RiskFieldGroup'
import type { RiskField } from './RiskFieldGroup'
import type { DashboardStrategy, RiskConfigUpdate } from '@/types/strategy-dashboard'

interface RiskConfigSectionProps {
  strategy: DashboardStrategy
  onSaved: () => void
}

export function RiskConfigSection({ strategy, onSaved }: RiskConfigSectionProps) {
  const [saving, setSaving] = useState(false)
  const [stoploss, setStoploss] = useState<RiskField>({ type: null, value: '' })
  const [target, setTarget] = useState<RiskField>({ type: null, value: '' })
  const [trailstop, setTrailstop] = useState<RiskField>({ type: null, value: '' })
  const [breakeven, setBreakeven] = useState<RiskField>({ type: null, value: '' })
  const [exitExecution, setExitExecution] = useState('market')
  const [autoSquareoff, setAutoSquareoff] = useState('')
  // Daily circuit breaker
  const [dailyStoploss, setDailyStoploss] = useState<RiskField>({ type: null, value: '' })
  const [dailyTarget, setDailyTarget] = useState<RiskField>({ type: null, value: '' })
  const [dailyTrailstop, setDailyTrailstop] = useState<RiskField>({ type: null, value: '' })

  // Pre-populate from strategy
  useEffect(() => {
    setStoploss({
      type: (strategy.default_stoploss_type as RiskField['type']) ?? null,
      value: strategy.default_stoploss_value?.toString() ?? '',
    })
    setTarget({
      type: (strategy.default_target_type as RiskField['type']) ?? null,
      value: strategy.default_target_value?.toString() ?? '',
    })
    setTrailstop({
      type: (strategy.default_trailstop_type as RiskField['type']) ?? null,
      value: strategy.default_trailstop_value?.toString() ?? '',
    })
    setBreakeven({
      type: (strategy.default_breakeven_type as RiskField['type']) ?? null,
      value: strategy.default_breakeven_threshold?.toString() ?? '',
    })
    setExitExecution(strategy.default_exit_execution || 'market')
    setAutoSquareoff(strategy.auto_squareoff_time ?? '')
    // Daily CB
    setDailyStoploss({
      type: (strategy.daily_stoploss_type as RiskField['type']) ?? null,
      value: strategy.daily_stoploss_value?.toString() ?? '',
    })
    setDailyTarget({
      type: (strategy.daily_target_type as RiskField['type']) ?? null,
      value: strategy.daily_target_value?.toString() ?? '',
    })
    setDailyTrailstop({
      type: (strategy.daily_trailstop_type as RiskField['type']) ?? null,
      value: strategy.daily_trailstop_value?.toString() ?? '',
    })
  }, [strategy])

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
        // Daily circuit breaker
        daily_stoploss_type: dailyStoploss.type,
        daily_stoploss_value:
          dailyStoploss.type && dailyStoploss.value ? Number(dailyStoploss.value) : null,
        daily_target_type: dailyTarget.type,
        daily_target_value:
          dailyTarget.type && dailyTarget.value ? Number(dailyTarget.value) : null,
        daily_trailstop_type: dailyTrailstop.type,
        daily_trailstop_value:
          dailyTrailstop.type && dailyTrailstop.value ? Number(dailyTrailstop.value) : null,
      }

      const res = await strategyDashboardApi.updateRiskConfig(strategy.id, config)
      if (res.status === 'success') {
        showToast.success('Risk configuration updated', 'strategyRisk')
        onSaved()
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
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Risk Configuration</CardTitle>
        <CardDescription className="text-xs">
          Default risk parameters for new positions
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* ── Per-Position Risk Defaults ── */}
        <div className="grid gap-6 md:grid-cols-2">
          <RiskFieldGroup label="Stoploss" field={stoploss} onChange={setStoploss} />
          <RiskFieldGroup label="Target" field={target} onChange={setTarget} />
          <RiskFieldGroup label="Trailing Stop" field={trailstop} onChange={setTrailstop} />
          <RiskFieldGroup
            label="Breakeven Threshold"
            field={breakeven}
            onChange={setBreakeven}
          />
        </div>

        <Separator />

        {/* ── Exit Execution + Auto Square-Off ── */}
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <Label className="text-sm">Exit Execution</Label>
            <Tabs value={exitExecution} onValueChange={setExitExecution}>
              <TabsList className="grid w-full grid-cols-1">
                <TabsTrigger value="market">Market</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="space-y-2">
            <Label className="text-sm">Auto Square-Off Time</Label>
            <Input
              type="time"
              value={autoSquareoff}
              onChange={(e) => setAutoSquareoff(e.target.value)}
              placeholder="15:15"
            />
            <p className="text-xs text-muted-foreground">Leave empty to disable</p>
          </div>
        </div>

        <Separator />

        {/* ── Daily Risk Limits (Circuit Breaker) ── */}
        <div className="space-y-1">
          <Label className="flex items-center gap-1.5 text-sm font-medium">
            <ShieldAlert className="h-4 w-4" />
            Daily Risk Limits
          </Label>
          <p className="text-xs text-muted-foreground">
            Strategy-level circuit breaker — halts all trading when daily P&L thresholds are hit
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          <RiskFieldGroup
            label="Daily Stoploss"
            field={dailyStoploss}
            onChange={setDailyStoploss}
            pointsOnly
          />
          <RiskFieldGroup
            label="Daily Target"
            field={dailyTarget}
            onChange={setDailyTarget}
            pointsOnly
          />
          <RiskFieldGroup
            label="Daily Trail Stop"
            field={dailyTrailstop}
            onChange={setDailyTrailstop}
            pointsOnly
          />
        </div>

        {/* Save */}
        <div className="flex justify-end pt-2">
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            Save Risk Configuration
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
