/**
 * Strategy v2 — account-level RMS configuration page.
 *
 * Phase 4.5 deliverable per docs/plans/2026-05-06-strategy-v2-implementation-plan.md.
 *
 * URL: /strategy/v2/account
 *
 * Six knobs:
 *   - max_concurrent_runs           — cap simultaneous active runs across strategies
 *   - max_daily_loss_abs            — auto-lock when realized live loss breaches
 *   - cooldown_after_loss_minutes   — refuse new runs for N minutes after a loss
 *   - max_runs_per_strategy_per_day — per-strategy daily run cap
 *   - min_seconds_between_runs      — debounce per strategy
 *   - auto_clear_at                 — optional HH:MM IST; lockout self-clears
 *
 * Plus a live state card showing active_run_count / realized P&L (live + sandbox)
 * and a manual Unlock button when account is locked.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { strategyV2Api } from '@/api/strategy_v2'
import type {
  AccountRiskConfig,
  AccountRiskConfigPayload,
  AccountState,
} from '@/types/strategy_v2'

export default function StrategyV2AccountRisk() {
  const navigate = useNavigate()
  const [config, setConfig] = useState<AccountRiskConfig | null>(null)
  const [state, setState] = useState<AccountState | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  // Phase 6: cross-mode view toggle. The backend tracks live and sandbox
  // P&L independently — this picks which slice is highlighted on the
  // dashboard. Daily-loss lockout always operates on live only (see
  // services/strategy/account_rms.py:on_state_changed); the sandbox
  // numbers exist for visibility, not RMS gating.
  const [viewMode, setViewMode] = useState<'combined' | 'live' | 'sandbox'>(
    'combined',
  )

  const refresh = async () => {
    setLoading(true)
    try {
      const r = await strategyV2Api.getAccountRiskConfig()
      setConfig(r.config)
      setState(r.state)
    } catch (err) {
      toast.error('Failed to load account risk config')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const onSave = async () => {
    if (!config) return
    setSaving(true)
    try {
      const payload: AccountRiskConfigPayload = {
        max_concurrent_runs: config.max_concurrent_runs,
        max_daily_loss_abs: config.max_daily_loss_abs,
        cooldown_after_loss_minutes: config.cooldown_after_loss_minutes,
        max_runs_per_strategy_per_day: config.max_runs_per_strategy_per_day,
        min_seconds_between_runs: config.min_seconds_between_runs,
        auto_clear_at: config.auto_clear_at,
      }
      const updated = await strategyV2Api.updateAccountRiskConfig(payload)
      setConfig(updated)
      toast.success('Account risk config saved')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      toast.error(e?.response?.data?.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const onUnlock = async () => {
    try {
      const updated = await strategyV2Api.unlockAccount()
      setConfig(updated)
      toast.success('Account unlocked')
    } catch (err) {
      toast.error('Unlock failed')
      console.error(err)
    }
  }

  if (loading || !config || !state) {
    return <div className="container mx-auto p-8">Loading…</div>
  }

  const update = (patch: Partial<AccountRiskConfig>) =>
    setConfig({ ...config, ...patch })

  return (
    <div className="container mx-auto p-6 max-w-4xl space-y-6">
      <div>
        <button
          type="button"
          onClick={() => navigate('/strategy/v2')}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← All strategies
        </button>
        <h1 className="text-2xl font-semibold mt-1">Account Risk Management</h1>
        <p className="text-sm text-muted-foreground">
          Account-wide caps that gate every strategy. These rules fire BEFORE any
          per-strategy or per-leg rules.
        </p>
      </div>

      {/* Lockout banner ----------------------------------------------------- */}
      {config.is_locked_out && (
        <Card className="border-rose-500/50 bg-rose-500/10">
          <CardContent className="py-4 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="bg-rose-500/15 text-rose-700">
                  ACCOUNT LOCKED
                </Badge>
                <span className="text-sm font-medium">
                  Reason: {config.lockout_reason ?? 'unknown'}
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {config.lockout_until ? (
                  <>Auto-clears at {config.lockout_until}.</>
                ) : (
                  <>Manual unlock required — no auto-clear configured.</>
                )}{' '}
                New webhook signals are rejected with 429 until cleared.
              </p>
            </div>
            <Button variant="destructive" onClick={onUnlock}>
              Unlock Now
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Live state card ---------------------------------------------------- */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Live State</CardTitle>
          <Tabs
            value={viewMode}
            onValueChange={(v) => setViewMode(v as typeof viewMode)}
          >
            <TabsList>
              <TabsTrigger value="combined">Combined</TabsTrigger>
              <TabsTrigger value="live">Live</TabsTrigger>
              <TabsTrigger value="sandbox">Sandbox</TabsTrigger>
            </TabsList>
          </Tabs>
        </CardHeader>
        <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <Stat label="Active Runs" value={String(state.active_run_count)} />
          {(viewMode === 'combined' || viewMode === 'live') && (
            <Stat
              label="Today's Live P&L"
              value={fmtMoney(state.realized_pnl_today_live)}
              tone={tone(state.realized_pnl_today_live)}
            />
          )}
          {(viewMode === 'combined' || viewMode === 'sandbox') && (
            <Stat
              label="Today's Sandbox P&L"
              value={fmtMoney(state.realized_pnl_today_sandbox)}
              tone={tone(state.realized_pnl_today_sandbox)}
            />
          )}
          <Stat
            label="Unrealized Aggregate"
            value={fmtMoney(state.unrealized_pnl_aggregate)}
            tone={tone(state.unrealized_pnl_aggregate)}
          />
        </CardContent>
        {viewMode === 'sandbox' && (
          <CardContent className="pt-0 text-xs text-muted-foreground">
            Sandbox P&L is informational only. The daily-loss lockout cap
            below operates on live realized P&L only — sandbox losses never
            trigger an account lockout.
          </CardContent>
        )}
      </Card>

      {/* Caps card ---------------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Caps</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1">
            <Label>Max concurrent runs</Label>
            <Input
              type="number"
              min={0}
              value={config.max_concurrent_runs ?? ''}
              onChange={(e) =>
                update({
                  max_concurrent_runs: e.target.value === '' ? null : Number(e.target.value),
                })
              }
              placeholder="No limit"
            />
            <p className="text-xs text-muted-foreground">
              Across all strategies. New webhooks rejected when reached.
            </p>
          </div>

          <div className="space-y-1">
            <Label>Max daily loss (₹)</Label>
            <Input
              type="number"
              min={0}
              value={config.max_daily_loss_abs ?? ''}
              onChange={(e) =>
                update({
                  max_daily_loss_abs: e.target.value === '' ? null : Number(e.target.value),
                })
              }
              placeholder="No cap"
            />
            <p className="text-xs text-muted-foreground">
              Live realized only. Account auto-locks when breached.
            </p>
          </div>

          <div className="space-y-1">
            <Label>Cooldown after loss (minutes)</Label>
            <Input
              type="number"
              min={0}
              value={config.cooldown_after_loss_minutes ?? ''}
              onChange={(e) =>
                update({
                  cooldown_after_loss_minutes:
                    e.target.value === '' ? null : Number(e.target.value),
                })
              }
              placeholder="No cooldown"
            />
            <p className="text-xs text-muted-foreground">
              After a losing run closes, refuse new runs for this many minutes.
            </p>
          </div>

          <div className="space-y-1">
            <Label>Max runs per strategy per day</Label>
            <Input
              type="number"
              min={0}
              value={config.max_runs_per_strategy_per_day ?? ''}
              onChange={(e) =>
                update({
                  max_runs_per_strategy_per_day:
                    e.target.value === '' ? null : Number(e.target.value),
                })
              }
              placeholder="No limit"
            />
            <p className="text-xs text-muted-foreground">
              Stops a misbehaving signal source from spamming.
            </p>
          </div>

          <div className="space-y-1">
            <Label>Min seconds between runs (per strategy)</Label>
            <Input
              type="number"
              min={0}
              value={config.min_seconds_between_runs ?? ''}
              onChange={(e) =>
                update({
                  min_seconds_between_runs:
                    e.target.value === '' ? null : Number(e.target.value),
                })
              }
              placeholder="No debounce"
            />
            <p className="text-xs text-muted-foreground">
              Debounce duplicate webhooks for the same strategy.
            </p>
          </div>

          <div className="space-y-1">
            <Label>Lockout auto-clear (HH:MM IST)</Label>
            <Input
              type="time"
              value={config.auto_clear_at ?? ''}
              onChange={(e) =>
                update({ auto_clear_at: e.target.value || null })
              }
            />
            <p className="text-xs text-muted-foreground">
              Optional. Lockout self-clears at this time next trading day.
              Empty = manual unlock only.
            </p>
          </div>
        </CardContent>
        <CardContent className="flex justify-end pt-0">
          <Button onClick={onSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'positive' | 'negative' | 'neutral'
}) {
  const cls =
    tone === 'positive'
      ? 'text-emerald-700'
      : tone === 'negative'
        ? 'text-rose-700'
        : ''
  return (
    <div className="space-y-1">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className={`font-mono text-base ${cls}`}>{value}</div>
    </div>
  )
}

function fmtMoney(n: number): string {
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}₹${n.toFixed(2)}`
}

function tone(n: number): 'positive' | 'negative' | 'neutral' {
  if (n > 0) return 'positive'
  if (n < 0) return 'negative'
  return 'neutral'
}
