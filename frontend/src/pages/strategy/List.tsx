// pages/strategy/List.tsx
// Saved strategies: status, mode and P&L at a glance.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  deleteStrategy,
  listStrategies,
  strategyQueryKeys,
  useStrategyListPnl,
} from '@/api/strategy_module'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import {
  formatIst,
  formatListPnl,
  formatPnl,
  pnlToneClass,
  type StrategyStatus,
  universeTabLabel,
} from '@/types/strategy_module'
import { showToast } from '@/utils/toast'

function statusBadgeVariant(
  status: StrategyStatus
): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'running':
      return 'default'
    case 'paused':
      return 'secondary'
    case 'errored':
      return 'destructive'
    default:
      return 'outline'
  }
}

export default function StrategyList() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: strategyQueryKeys.list({}),
    queryFn: () => listStrategies({}),
    refetchInterval: 30_000,
  })

  const rows = data ?? []
  const pnlById = useStrategyListPnl(rows)

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteStrategy(id),
    onSuccess: () => {
      showToast.success('Strategy deleted')
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
      setDeleteTargetId(null)
    },
    onError: (err: Error) => {
      showToast.error(err.message || 'Delete failed')
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Strategies</h1>
          <p className="text-sm text-muted-foreground">
            Multi-leg options strategies with end-to-end risk management. Sandbox by default; live
            mode requires explicit per-strategy opt-in.
          </p>
        </div>
        <Button onClick={() => navigate('/strategy/new')}>+ New strategy</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Saved strategies</CardTitle>
          <CardDescription>
            P&amp;L columns are live for running strategies and reflect the last-run snapshot for
            stopped strategies. Status shows whether a run is currently active.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              Failed to load strategies. Check the backend logs.
            </p>
          ) : isLoading ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Loading…</p>
          ) : rows.length === 0 ? (
            <div className="space-y-3 py-8 text-center">
              <p className="text-sm text-muted-foreground">No strategies yet.</p>
              <Button variant="secondary" onClick={() => navigate('/strategy/new')}>
                Create your first strategy
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Underlying</TableHead>
                    <TableHead>Tab</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="text-right">Realized</TableHead>
                    <TableHead className="text-right">Unrealized</TableHead>
                    <TableHead className="text-right">Total P&amp;L</TableHead>
                    <TableHead>Updated</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row, index) => {
                    const pnl = pnlById.get(row.id)
                    return (
                      <TableRow key={row.id} className={index % 2 === 0 ? 'bg-muted/30' : ''}>
                        <TableCell>
                          <Link to={`/strategy/${row.id}`} className="font-medium hover:underline">
                            {row.name}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusBadgeVariant(row.status)}>{row.status}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={row.live_enabled ? 'destructive' : 'secondary'}>
                            {row.live_enabled ? 'LIVE-enabled' : 'SANDBOX-only'}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium">{row.underlying}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {universeTabLabel(row.universe_tab)}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{row.strategy_type}</Badge>
                        </TableCell>
                        <TableCell
                          className={cn('text-right font-mono', pnlToneClass(pnl?.realized))}
                        >
                          {pnl?.finalized ? formatPnl(pnl.realized) : formatListPnl(pnl?.realized)}
                        </TableCell>
                        <TableCell
                          className={cn('text-right font-mono', pnlToneClass(pnl?.unrealized))}
                        >
                          {pnl?.finalized
                            ? formatPnl(pnl.unrealized)
                            : formatListPnl(pnl?.unrealized)}
                        </TableCell>
                        <TableCell
                          className={cn(
                            'text-right font-mono font-medium',
                            pnlToneClass(pnl?.total)
                          )}
                        >
                          {pnl?.finalized ? formatPnl(pnl.total) : formatListPnl(pnl?.total)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                          {formatIst(row.updated_at, false)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => navigate(`/strategy/${row.id}`)}
                            >
                              Open
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={row.status === 'running'}
                              title={
                                row.status === 'running'
                                  ? `Cannot delete while ${row.status}`
                                  : undefined
                              }
                              onClick={() => setDeleteTargetId(row.id)}
                            >
                              Delete
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={deleteTargetId !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTargetId(null)
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base">Delete this strategy?</DialogTitle>
            <DialogDescription>
              This permanently removes the strategy and its audit trail. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTargetId(null)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              className="min-w-[120px]"
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (deleteTargetId !== null) deleteMutation.mutate(deleteTargetId)
              }}
            >
              {deleteMutation.isPending ? 'Working…' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
