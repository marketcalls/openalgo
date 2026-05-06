/**
 * Strategy v2 — list page.
 *
 * Mirrors the styling of StrategyPortfolio / Dashboard tables but is a
 * standalone page accessed at /strategy/v2 once routing is wired in
 * App.tsx.
 *
 * Phase 1 deliverable per docs/plans/2026-05-06-strategy-v2-implementation-plan.md.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { strategyV2Api } from '@/api/strategy_v2'
import { useStrategyV2ListSocket } from '@/hooks/useStrategyV2Socket'
import type { AccountRiskConfig, StrategyV2 } from '@/types/strategy_v2'

const MODE_BADGE_CLASS: Record<string, string> = {
  live: 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30',
  sandbox: 'bg-amber-500/15 text-amber-700 border-amber-500/30',
}

const STATE_BADGE_CLASS: Record<string, string> = {
  DRAFT: 'bg-sky-500/15 text-sky-700 border-sky-500/30',
  ARMED: 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30',
  DISABLED: 'bg-rose-500/15 text-rose-700 border-rose-500/30',
  ARCHIVED: 'bg-neutral-500/10 text-neutral-500 border-neutral-500/30',
}

// Friendly state labels — schema stays DRAFT/ARMED/DISABLED/ARCHIVED but
// the UI displays Draft/Enabled/Disabled/Archived per user feedback.
const STATE_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  ARMED: 'Enabled',
  DISABLED: 'Disabled',
  ARCHIVED: 'Archived',
}

export default function StrategyV2List() {
  const [rows, setRows] = useState<StrategyV2[]>([])
  const [accountConfig, setAccountConfig] = useState<AccountRiskConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [deleteTarget, setDeleteTarget] = useState<StrategyV2 | null>(null)
  const navigate = useNavigate()

  // Phase 9.2 — subscribe via Socket.IO to every strategy that has an
  // active run, so the Today's P&L column updates in real time. Only
  // active runs receive ticks from the engine, so subscribing for
  // strategies without one is wasted RAM but harmless.
  const subscribableIds = useMemo(
    () =>
      rows
        .filter((r) => r.live?.active_run_id != null)
        .map((r) => r.id),
    [rows],
  )
  const livePnl = useStrategyV2ListSocket(subscribableIds)

  const refresh = async () => {
    setLoading(true)
    try {
      const [strategies, accountInfo] = await Promise.all([
        strategyV2Api.list(),
        strategyV2Api.getAccountRiskConfig().catch(() => null),
      ])
      setRows(strategies)
      if (accountInfo) setAccountConfig(accountInfo.config)
    } catch (err) {
      toast.error('Failed to load strategies')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const onUnlockAccount = async () => {
    try {
      const updated = await strategyV2Api.unlockAccount()
      setAccountConfig(updated)
      toast.success('Account unlocked')
    } catch (err) {
      toast.error('Unlock failed')
      console.error(err)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const onToggle = async (s: StrategyV2) => {
    try {
      await strategyV2Api.toggle(s.id)
      await refresh()
    } catch (err) {
      toast.error(`Failed to toggle ${s.name}`)
      console.error(err)
    }
  }

  const onDelete = (s: StrategyV2) => {
    if (s.is_active) {
      toast.error('Disable the strategy before deleting')
      return
    }
    setDeleteTarget(s)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    const s = deleteTarget
    setDeleteTarget(null)
    try {
      await strategyV2Api.remove(s.id)
      toast.success(`Deleted ${s.name}`)
      await refresh()
    } catch (err) {
      toast.error(`Failed to delete ${s.name}`)
      console.error(err)
    }
  }

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Strategies (v2)</h1>
          <p className="text-sm text-muted-foreground">
            Multi-leg strategies with leg-level + overall risk controls,
            webhook security, and live/sandbox modes.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate('/strategy/v2/account')}>
            Account Risk
          </Button>
          <Button onClick={() => navigate('/strategy/v2/new')}>+ New Strategy</Button>
        </div>
      </div>

      {/* Account-level lockout banner */}
      {accountConfig?.is_locked_out && (
        <Card className="mb-6 border-rose-500/50 bg-rose-500/10">
          <CardContent className="py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Badge variant="outline" className="bg-rose-500/15 text-rose-700">
                ACCOUNT LOCKED
              </Badge>
              <span className="text-sm">
                {accountConfig.lockout_reason ?? 'Reason unknown'}.{' '}
                <span className="text-muted-foreground">
                  New webhooks rejected with 429 until cleared.
                </span>
              </span>
            </div>
            <Button variant="destructive" size="sm" onClick={onUnlockAccount}>
              Unlock
            </Button>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">Loading…</CardContent>
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No strategies yet</CardTitle>
            <CardDescription>
              Create your first multi-leg strategy with webhook signing,
              segment-aware leg builder, and risk controls.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => navigate('/strategy/v2/new')}>Create your first strategy</Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="border-b text-left">
                <tr className="text-xs uppercase text-muted-foreground">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Segment</th>
                  <th className="px-4 py-3">Mode</th>
                  <th className="px-4 py-3">State</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Schedule</th>
                  <th className="px-4 py-3 text-right">Today's P&amp;L</th>
                  <th className="px-4 py-3">Active</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="border-b last:border-b-0 hover:bg-muted/40">
                    <td className="px-4 py-3 font-medium">
                      <button
                        type="button"
                        className="hover:underline text-left"
                        onClick={() => navigate(`/strategy/v2/${s.id}`)}
                      >
                        {s.name}
                      </button>
                    </td>
                    {/* Segment column lets the operator scan a long list
                        and immediately see what each strategy trades. */}
                    <td className="px-4 py-3 text-muted-foreground">
                      {s.segment === 'CASH'
                        ? 'Cash'
                        : s.underlying
                          ? `${s.underlying} · ${s.underlying_exchange ?? ''}`
                          : s.segment === 'STOCK_FO'
                            ? 'Stock F&O'
                            : 'Index F&O'}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={MODE_BADGE_CLASS[s.mode] || ''}>
                        {s.mode === 'sandbox' ? 'SANDBOX' : 'LIVE'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={STATE_BADGE_CLASS[s.state] || ''}>
                        {STATE_LABELS[s.state] ?? s.state}
                      </Badge>
                    </td>
                    {/* Type column — Intraday vs Positional. Schedule
                        column to the right shows the actual timing /
                        date / run-forever info. */}
                    <td className="px-4 py-3 text-muted-foreground">
                      {s.is_intraday ? 'Intraday' : 'Positional'}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {s.is_intraday
                        ? `${s.start_time}–${s.end_time ?? ''}${s.squareoff_time ? ` · sq ${s.squareoff_time}` : ''}`
                        : s.run_forever
                          ? 'Run forever'
                          : s.exit_date
                            ? `until ${s.exit_date}`
                            : '—'}
                    </td>
                    {/* Today's P&L = realized (closed runs today) + unrealized
                        (active run's live agg_mtm). Live updates arrive via
                        Socket.IO and override the snapshot from the initial
                        list payload. */}
                    <td className="px-4 py-3 text-right font-mono">
                      {(() => {
                        const liveAgg =
                          livePnl[s.id]?.agg_mtm ?? s.live?.agg_mtm ?? 0
                        const realized = s.live?.realized_today ?? 0
                        const total = liveAgg + realized
                        if (!s.live || (s.live.active_run_id == null && realized === 0)) {
                          return <span className="text-muted-foreground">—</span>
                        }
                        const cls =
                          total > 0
                            ? 'text-emerald-700'
                            : total < 0
                              ? 'text-rose-700'
                              : ''
                        const sign = total > 0 ? '+' : ''
                        return (
                          <span className={cls}>
                            {sign}₹{total.toFixed(2)}
                            {s.live.active_run_id != null && (
                              <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse align-middle" />
                            )}
                          </span>
                        )
                      })()}
                    </td>
                    <td className="px-4 py-3">
                      <Button
                        variant={s.is_active ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => onToggle(s)}
                      >
                        {s.is_active ? 'On' : 'Off'}
                      </Button>
                    </td>
                    <td className="px-4 py-3 text-right space-x-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => navigate(`/strategy/v2/${s.id}`)}
                      >
                        Edit
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => onDelete(s)}>
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete strategy?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete{' '}
              <span className="font-medium">{deleteTarget?.name ?? ''}</span>{' '}
              and all of its legs, runs, orders, and audit history. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
