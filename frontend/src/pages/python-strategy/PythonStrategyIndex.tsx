import {
  AlertTriangle,
  Calendar,
  Clock,
  Download,
  FileCode,
  FileText,
  HelpCircle,
  MoreVertical,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Square,
  Trash2,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { MasterContractStatus, PythonStrategy } from '@/types/python-strategy'
import { SCHEDULE_DAYS, STATUS_COLORS, STATUS_LABELS } from '@/types/python-strategy'

export default function PythonStrategyIndex() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<PythonStrategy[]>([])
  const [masterStatus, setMasterStatus] = useState<MasterContractStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [strategyToDelete, setStrategyToDelete] = useState<PythonStrategy | null>(null)
  const [currentTime, setCurrentTime] = useState(new Date())

  const fetchData = async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const [strategiesData, statusData] = await Promise.all([
        pythonStrategyApi.getStrategies(),
        pythonStrategyApi.getMasterContractStatus(),
      ])
      setStrategies(strategiesData)
      setMasterStatus(statusData)
    } catch (error) {
      if (!silent) showToast.error('Failed to load strategies', 'pythonStrategy')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    // Update current time every second
    const timer = setInterval(() => setCurrentTime(new Date()), 1000)

    // Subscribe to SSE for real-time status updates
    const eventSource = new EventSource('/python/api/events')

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'connected') {
          return
        }

        // Refresh data silently when we receive a status update
        if (data.strategy_id && data.status) {
          fetchData(true) // Silent refresh
        }
      } catch (e) {
        // Ignore parse errors (heartbeat messages)
      }
    }

    eventSource.onerror = () => {
    }

    return () => {
      clearInterval(timer)
      eventSource.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleStart = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const response = await pythonStrategyApi.startStrategy(strategy.id)
      if (response.status === 'success') {
        // Use response message which differs for immediate start vs armed for schedule
        showToast.success(response.message || `Strategy ${strategy.name} started`, 'pythonStrategy')
        fetchData()
      } else {
        showToast.error(response.message || 'Failed to start strategy', 'pythonStrategy')
      }
    } catch (error: unknown) {
      // Extract error message from Axios response
      const axiosError = error as { response?: { data?: { message?: string } } }
      const errorMessage = axiosError.response?.data?.message || 'Failed to start strategy'
      showToast.error(errorMessage, 'pythonStrategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handleStop = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const response = await pythonStrategyApi.stopStrategy(strategy.id)
      if (response.status === 'success') {
        // Use response message which differs for running vs scheduled strategies
        showToast.success(response.message || `Strategy ${strategy.name} stopped`, 'pythonStrategy')
        fetchData()
      } else {
        showToast.error(response.message || 'Failed to stop strategy', 'pythonStrategy')
      }
    } catch (error) {
      showToast.error('Failed to stop strategy', 'pythonStrategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handleClearError = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const response = await pythonStrategyApi.clearError(strategy.id)
      if (response.status === 'success') {
        showToast.success('Error cleared', 'pythonStrategy')
        fetchData()
      } else {
        showToast.error(response.message || 'Failed to clear error', 'pythonStrategy')
      }
    } catch (error) {
      showToast.error('Failed to clear error', 'pythonStrategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async () => {
    if (!strategyToDelete) return
    try {
      setActionLoading(strategyToDelete.id)
      const response = await pythonStrategyApi.deleteStrategy(strategyToDelete.id)
      if (response.status === 'success') {
        showToast.success('Strategy deleted', 'pythonStrategy')
        setStrategies(strategies.filter((s) => s.id !== strategyToDelete.id))
      } else {
        showToast.error(response.message || 'Failed to delete strategy', 'pythonStrategy')
      }
    } catch (error) {
      showToast.error('Failed to delete strategy', 'pythonStrategy')
    } finally {
      setActionLoading(null)
      setDeleteDialogOpen(false)
      setStrategyToDelete(null)
    }
  }

  const handleExport = async (strategy: PythonStrategy) => {
    try {
      const blob = await pythonStrategyApi.exportStrategy(strategy.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = strategy.file_name
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      showToast.success('Strategy exported', 'pythonStrategy')
    } catch (error) {
      showToast.error('Failed to export strategy', 'pythonStrategy')
    }
  }

  const handleCheckContracts = async () => {
    try {
      setActionLoading('master')
      const response = await pythonStrategyApi.checkAndStartPending()
      if (response.status === 'success') {
        const started = response.data?.started || 0
        showToast.success(`Started ${started} pending strategies`, 'pythonStrategy')
        fetchData()
      } else {
        showToast.error(response.message || 'Failed to check contracts', 'pythonStrategy')
      }
    } catch (error) {
      showToast.error('Failed to check contracts', 'pythonStrategy')
    } finally {
      setActionLoading(null)
    }
  }

  const formatScheduleDays = (days: string[]) => {
    if (!days || days.length === 0) return ''
    if (days.length === 7) return 'Every day'
    if (days.length === 5 && !days.includes('sat') && !days.includes('sun')) return 'Weekdays'
    return days
      .map((d) => SCHEDULE_DAYS.find((sd) => sd.value === d)?.label.slice(0, 3) || d)
      .join(', ')
  }

  const formatTime = (timeStr: string | null) => {
    if (!timeStr) return '-'
    return new Date(timeStr).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // Stats
  const stats = {
    total: strategies.length,
    running: strategies.filter((s) => s.status === 'running').length,
    scheduled: strategies.filter((s) => s.is_scheduled).length,
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <div className="flex justify-between items-center">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-10 w-32" />
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Python Strategies</h1>
          <p className="text-muted-foreground">Manage and run your Python trading scripts</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate('/python/guide')}>
            <HelpCircle className="h-4 w-4 mr-2" />
            Guide
          </Button>
          <Button variant="outline" size="sm" onClick={() => fetchData()}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
          <Button onClick={() => navigate('/python/new')}>
            <Plus className="h-4 w-4 mr-2" />
            Add Strategy
          </Button>
        </div>
      </div>

      {/* Stats Bar */}
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total</p>
                <p className="text-2xl font-bold">{stats.total}</p>
              </div>
              <FileCode className="h-8 w-8 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Running</p>
                <p className="text-2xl font-bold text-green-500">{stats.running}</p>
              </div>
              <Play className="h-8 w-8 text-green-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Scheduled</p>
                <p className="text-2xl font-bold text-blue-500">{stats.scheduled}</p>
              </div>
              <Calendar className="h-8 w-8 text-blue-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Master Contract</p>
                <Badge variant={masterStatus?.ready ? 'default' : 'secondary'}>
                  {masterStatus?.ready ? 'Ready' : 'Not Ready'}
                </Badge>
              </div>
              {!masterStatus?.ready && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleCheckContracts}
                  disabled={actionLoading === 'master'}
                >
                  Check
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Current Time */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Clock className="h-4 w-4" />
        Current IST: {currentTime.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}
      </div>

      {/* Strategies Grid */}
      {strategies.length === 0 ? (
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <FileCode className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No Python Strategies</h3>
            <p className="text-muted-foreground mb-4">
              Upload your first Python trading script to get started.
            </p>
            <Button onClick={() => navigate('/python/new')}>
              <Plus className="h-4 w-4 mr-2" />
              Add Strategy
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 items-start">
          {strategies.map((strategy) => (
            <Card key={strategy.id} className="relative overflow-hidden flex flex-col">
              {/* Status bar */}
              <div
                className={`absolute top-0 left-0 right-0 h-1 ${STATUS_COLORS[strategy.status]}`}
              />

              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <CardTitle className="text-lg">{strategy.name}</CardTitle>
                    <CardDescription className="font-mono text-xs">
                      {strategy.file_name}
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Tooltip>
                      <TooltipTrigger>
                        <Badge
                          variant={strategy.status === 'running' ? 'default' : 'secondary'}
                          className={STATUS_COLORS[strategy.status] || ''}
                        >
                          {STATUS_LABELS[strategy.status] || strategy.status}
                        </Badge>
                      </TooltipTrigger>
                      <TooltipContent>
                        {strategy.status_message || STATUS_LABELS[strategy.status]}
                      </TooltipContent>
                    </Tooltip>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon">
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => handleExport(strategy)}>
                          <Download className="h-4 w-4 mr-2" />
                          Export
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          className="text-red-500"
                          disabled={strategy.status === 'running'}
                          onClick={() => {
                            setStrategyToDelete(strategy)
                            setDeleteDialogOpen(true)
                          }}
                        >
                          <Trash2 className="h-4 w-4 mr-2" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4 flex-1 flex flex-col">
                {/* Schedule Info - always show */}
                <div className="text-sm p-2 rounded min-h-[52px] bg-blue-500/10 border border-blue-500/20">
                  <div className="flex items-center gap-2">
                    <Calendar className="h-4 w-4 text-blue-500" />
                    <span>
                      {strategy.schedule_start_time || '09:00'}
                      {' - '}
                      {strategy.schedule_stop_time || '16:00'}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {formatScheduleDays(strategy.schedule_days?.length ? strategy.schedule_days : ['mon', 'tue', 'wed', 'thu', 'fri'])}
                  </p>
                </div>

                {/* Error Message */}
                {strategy.status === 'error' && strategy.error_message && (
                  <Alert variant="destructive">
                    <AlertTriangle className="h-4 w-4" />
                    <AlertDescription className="text-xs">
                      {strategy.error_message}
                      <Button
                        variant="link"
                        size="sm"
                        className="p-0 h-auto ml-2"
                        onClick={() => handleClearError(strategy)}
                      >
                        Clear
                      </Button>
                    </AlertDescription>
                  </Alert>
                )}

                {/* Timestamps */}
                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground mt-auto">
                  <div>
                    <span className="block">Last Started</span>
                    <span>{formatTime(strategy.last_started)}</span>
                  </div>
                  <div>
                    <span className="block">Last Stopped</span>
                    <span>{formatTime(strategy.last_stopped)}</span>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-2 pt-2 mt-auto">
                  {strategy.status === 'running' || strategy.status === 'scheduled' ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant={strategy.status === 'running' ? 'destructive' : 'outline'}
                          size="sm"
                          className={`flex-1 ${strategy.status === 'scheduled' ? 'border-orange-500 text-orange-600 hover:bg-orange-50 dark:text-orange-400 dark:hover:bg-orange-950' : ''}`}
                          onClick={() => handleStop(strategy)}
                          disabled={actionLoading === strategy.id}
                        >
                          <Square className="h-4 w-4 mr-2" />
                          {strategy.status === 'running' ? 'Stop' : 'Cancel'}
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        {strategy.status === 'running' ? 'Stop running strategy' : 'Cancel scheduled auto-start'}
                      </TooltipContent>
                    </Tooltip>
                  ) : (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="default"
                          size="sm"
                          className="flex-1 bg-green-600 hover:bg-green-700"
                          onClick={() => handleStart(strategy)}
                          disabled={actionLoading === strategy.id}
                        >
                          <Play className="h-4 w-4 mr-2" />
                          Start
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Start strategy</TooltipContent>
                    </Tooltip>
                  )}

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        className="border-blue-500 text-blue-600 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-950"
                        asChild
                        disabled={strategy.status === 'running'}
                      >
                        <Link to={`/python/${strategy.id}/schedule`}>
                          <Pencil className="h-4 w-4 mr-1" />
                          <span className="text-xs">Schedule</span>
                        </Link>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {strategy.schedule_start_time && strategy.schedule_stop_time
                        ? `${strategy.schedule_start_time} - ${strategy.schedule_stop_time}`
                        : 'Edit schedule'}
                    </TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/python/${strategy.id}/logs`}>
                          <FileText className="h-4 w-4" />
                        </Link>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>View logs</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/python/${strategy.id}/edit`}>
                          <FileCode className="h-4 w-4" />
                        </Link>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Edit code</TooltipContent>
                  </Tooltip>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Delete Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Strategy</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{strategyToDelete?.name}"? This will remove the
              strategy file and all associated logs.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Delete Strategy
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
