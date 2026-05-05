/**
 * Strategy v2 — list page.
 *
 * Mirrors the styling of StrategyPortfolio / Dashboard tables but is a
 * standalone page accessed at /strategy/v2 once routing is wired in
 * App.tsx.
 *
 * Phase 1 deliverable per docs/plans/2026-05-06-strategy-v2-implementation-plan.md.
 */
import { useEffect, useState } from 'react'
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
import type { StrategyV2 } from '@/types/strategy_v2'

const MODE_BADGE_CLASS: Record<string, string> = {
  live: 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30',
  sandbox: 'bg-amber-500/15 text-amber-700 border-amber-500/30',
}

const STATE_BADGE_CLASS: Record<string, string> = {
  DRAFT: 'bg-neutral-500/15 text-neutral-700',
  ARMED: 'bg-emerald-500/15 text-emerald-700',
  DISABLED: 'bg-neutral-500/15 text-neutral-700',
  ARCHIVED: 'bg-neutral-500/10 text-neutral-500',
}

export default function StrategyV2List() {
  const [rows, setRows] = useState<StrategyV2[]>([])
  const [loading, setLoading] = useState(true)
  const [deleteTarget, setDeleteTarget] = useState<StrategyV2 | null>(null)
  const navigate = useNavigate()

  const refresh = async () => {
    setLoading(true)
    try {
      const data = await strategyV2Api.list()
      setRows(data)
    } catch (err) {
      toast.error('Failed to load strategies')
      console.error(err)
    } finally {
      setLoading(false)
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
        <Button onClick={() => navigate('/strategy/v2/new')}>+ New Strategy</Button>
      </div>

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
                  <th className="px-4 py-3">Underlying</th>
                  <th className="px-4 py-3">Mode</th>
                  <th className="px-4 py-3">State</th>
                  <th className="px-4 py-3">Schedule</th>
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
                    <td className="px-4 py-3 text-muted-foreground">
                      {s.underlying ? `${s.underlying} · ${s.underlying_exchange ?? ''}` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={MODE_BADGE_CLASS[s.mode] || ''}>
                        {s.mode === 'sandbox' ? 'SANDBOX' : 'LIVE'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={STATE_BADGE_CLASS[s.state] || ''}>
                        {s.state}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {s.is_intraday
                        ? `${s.start_time}–${s.end_time}${s.squareoff_time ? ` · sq ${s.squareoff_time}` : ''}`
                        : 'Positional'}
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
