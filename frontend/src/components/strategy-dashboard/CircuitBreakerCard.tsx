import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { dashboardApi } from '@/api/strategy-dashboard'
import { showToast } from '@/utils/toast'
import type { CircuitBreakerConfig } from '@/types/strategy-dashboard'

type CBBehavior = CircuitBreakerConfig['daily_cb_behavior']

interface CircuitBreakerCardProps {
  strategyId: number
  strategyType: string
  currentBehavior: CBBehavior
  onUpdate?: (behavior: CBBehavior) => void
}

const BEHAVIORS: { value: CBBehavior; label: string; desc: string }[] = [
  { value: 'alert_only', label: 'Alert Only', desc: 'Toast + Telegram notification, no automatic action' },
  { value: 'stop_entries', label: 'Stop Entries', desc: 'Block new webhook entries, keep existing positions' },
  { value: 'close_all_positions', label: 'Close All Positions', desc: 'Close all positions immediately' },
]

export function CircuitBreakerCard({
  strategyId,
  strategyType,
  currentBehavior,
  onUpdate,
}: CircuitBreakerCardProps) {
  const [behavior, setBehavior] = useState<CBBehavior>(currentBehavior)
  const [saving, setSaving] = useState(false)
  const dirty = behavior !== currentBehavior

  const handleSave = async () => {
    setSaving(true)
    try {
      await dashboardApi.updateCircuitBreaker(strategyId, strategyType, {
        daily_cb_behavior: behavior,
      })
      showToast.success('Circuit breaker updated')
      onUpdate?.(behavior)
    } catch {
      showToast.error('Failed to update circuit breaker')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Daily Circuit Breaker</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">Behavior when triggered</label>
          <Select value={behavior} onValueChange={(v) => setBehavior(v as CBBehavior)}>
            <SelectTrigger className="text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BEHAVIORS.map((b) => (
                <SelectItem key={b.value} value={b.value} className="text-xs">
                  {b.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[10px] text-muted-foreground">
            {BEHAVIORS.find((b) => b.value === behavior)?.desc}
          </p>
        </div>
        {dirty && (
          <Button size="sm" className="w-full text-xs" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
