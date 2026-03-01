import {
  BarChart3,
  Clock,
  Download,
  GitCompare,
  Plus,
  RefreshCw,
  Trash2,
  TrendingDown,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { backtestApi } from '@/api/backtest'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { BacktestListItem } from '@/types/backtest'
import { STATUS_COLORS, STATUS_LABELS } from '@/types/backtest'
import { showToast } from '@/utils/toast'

export default function BacktestIndex() {
  const navigate = useNavigate()
  const [backtests, setBacktests] = useState<BacktestListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  const fetchBacktests = useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const data = await backtestApi.list()
      setBacktests(data)
    } catch {
      if (!silent) showToast.error('Failed to load backtests')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchBacktests()
  }, [fetchBacktests])

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this backtest? This cannot be undone.')) return
    setActionLoading(id)
    try {
      await backtestApi.delete(id)
      showToast.success('Backtest deleted')
      fetchBacktests(true)
    } catch {
      showToast.error('Failed to delete backtest')
    } finally {
      setActionLoading(null)
    }
  }

  const handleCancel = async (id: string) => {
    setActionLoading(id)
    try {
      await backtestApi.cancel(id)
      showToast.success('Cancellation requested')
      fetchBacktests(true)
    } catch {
      showToast.error('Failed to cancel backtest')
    } finally {
      setActionLoading(null)
    }
  }

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  const handleCompare = () => {
    if (selectedIds.length < 2) {
      showToast.error('Select at least 2 backtests to compare')
      return
    }
    navigate(`/backtest/compare?ids=${selectedIds.join(',')}`)
  }

  const formatDuration = (ms: number | null) => {
    if (!ms) return '-'
    if (ms < 1000) return `${ms}ms`
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
    return `${(ms / 60000).toFixed(1)}m`
  }

  const formatReturn = (pct: number | null) => {
    if (pct === null || pct === undefined) return '-'
    const isPositive = pct >= 0
    return (
      <span className={isPositive ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
        {isPositive ? '+' : ''}{pct.toFixed(2)}%
      </span>
    )
  }

  if (loading) {
    return (
      <div className="container mx-auto p-6 space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BarChart3 className="h-6 w-6" />
            Backtests
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Test your strategies on historical data
          </p>
        </div>
        <div className="flex gap-2">
          {selectedIds.length >= 2 && (
            <Button variant="outline" onClick={handleCompare}>
              <GitCompare className="h-4 w-4 mr-2" />
              Compare ({selectedIds.length})
            </Button>
          )}
          <Button variant="outline" size="icon" onClick={() => fetchBacktests()}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button onClick={() => navigate('/backtest/new')}>
            <Plus className="h-4 w-4 mr-2" />
            New Backtest
          </Button>
        </div>
      </div>

      {/* Backtests Table */}
      {backtests.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <BarChart3 className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-medium">No backtests yet</h3>
            <p className="text-muted-foreground text-sm mt-1">
              Create your first backtest to start testing strategies
            </p>
            <Button className="mt-4" onClick={() => navigate('/backtest/new')}>
              <Plus className="h-4 w-4 mr-2" />
              New Backtest
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>All Backtests</CardTitle>
            <CardDescription>
              Click on a backtest to view detailed results. Select multiple to compare.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Symbols</TableHead>
                  <TableHead>Interval</TableHead>
                  <TableHead>Period</TableHead>
                  <TableHead className="text-right">Return</TableHead>
                  <TableHead className="text-right">Sharpe</TableHead>
                  <TableHead className="text-right">Max DD</TableHead>
                  <TableHead className="text-right">Trades</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                  <TableHead className="w-20">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {backtests.map((bt) => (
                  <TableRow
                    key={bt.backtest_id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => {
                      if (bt.status === 'completed') {
                        navigate(`/backtest/${bt.backtest_id}`)
                      } else if (bt.status === 'running') {
                        navigate(`/backtest/${bt.backtest_id}`)
                      }
                    }}
                  >
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      {bt.status === 'completed' && (
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(bt.backtest_id)}
                          onChange={() => toggleSelect(bt.backtest_id)}
                          className="h-4 w-4 rounded border-gray-300"
                        />
                      )}
                    </TableCell>
                    <TableCell className="font-medium max-w-48 truncate">
                      {bt.name}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="secondary"
                        className={`${STATUS_COLORS[bt.status] || 'bg-gray-500'} text-white text-xs`}
                      >
                        {STATUS_LABELS[bt.status] || bt.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-32 truncate">
                      {bt.symbols.join(', ')}
                    </TableCell>
                    <TableCell>{bt.interval}</TableCell>
                    <TableCell className="text-xs">
                      {bt.start_date} to {bt.end_date}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {formatReturn(bt.total_return_pct)}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {bt.sharpe_ratio !== null ? bt.sharpe_ratio.toFixed(2) : '-'}
                    </TableCell>
                    <TableCell className="text-right font-mono text-red-600 dark:text-red-400">
                      {bt.max_drawdown_pct !== null ? `-${bt.max_drawdown_pct.toFixed(2)}%` : '-'}
                    </TableCell>
                    <TableCell className="text-right">{bt.total_trades}</TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      <Clock className="inline h-3 w-3 mr-1" />
                      {formatDuration(bt.duration_ms)}
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <div className="flex gap-1">
                        {bt.status === 'running' && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            disabled={actionLoading === bt.backtest_id}
                            onClick={() => handleCancel(bt.backtest_id)}
                          >
                            <TrendingDown className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        {bt.status === 'completed' && (
                          <a
                            href={backtestApi.getExportUrl(bt.backtest_id)}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Button variant="ghost" size="icon" className="h-7 w-7">
                              <Download className="h-3.5 w-3.5" />
                            </Button>
                          </a>
                        )}
                        {bt.status !== 'running' && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-red-500"
                            disabled={actionLoading === bt.backtest_id}
                            onClick={() => handleDelete(bt.backtest_id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
