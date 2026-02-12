import { ArrowLeft, Clock, FileText, HardDrive, RefreshCw, ScrollText, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { LogViewer } from '@/components/ui/log-viewer'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import type { LogContent, LogFile, PythonStrategy } from '@/types/python-strategy'

export default function PythonStrategyLogs() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const [strategy, setStrategy] = useState<PythonStrategy | null>(null)
  const [logFiles, setLogFiles] = useState<LogFile[]>([])
  const [selectedLog, setSelectedLog] = useState<string | null>(null)
  const [logContent, setLogContent] = useState<LogContent | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingContent, setLoadingContent] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [clearDialogOpen, setClearDialogOpen] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const fetchData = async () => {
    if (!strategyId) return
    try {
      setLoading(true)
      const [strategyData, logsData] = await Promise.all([
        pythonStrategyApi.getStrategy(strategyId),
        pythonStrategyApi.getLogFiles(strategyId),
      ])
      setStrategy(strategyData)
      setLogFiles(logsData)

      // Auto-select first log if available
      if (logsData.length > 0 && !selectedLog) {
        setSelectedLog(logsData[0].name)
      }
    } catch (error) {
      showToast.error('Failed to load logs', 'pythonStrategy')
    } finally {
      setLoading(false)
    }
  }

  const fetchLogContent = async (logName: string, showLoading = true) => {
    if (!strategyId) return
    try {
      // Only show loading state for initial load, not auto-refresh
      if (showLoading) {
        setLoadingContent(true)
      }
      const content = await pythonStrategyApi.getLogContent(strategyId, logName)
      setLogContent(content)
    } catch (error) {
      // Only show toast for manual fetch, not auto-refresh
      if (showLoading) {
        showToast.error('Failed to load log content', 'pythonStrategy')
      }
    } finally {
      if (showLoading) {
        setLoadingContent(false)
      }
    }
  }

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (selectedLog) {
      fetchLogContent(selectedLog)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLog])

  // Auto-refresh if strategy is running and auto-refresh is enabled
  useEffect(() => {
    if (strategy?.status === 'running' && selectedLog && autoRefresh) {
      const interval = setInterval(() => {
        // Pass false to avoid showing loading spinner during auto-refresh
        fetchLogContent(selectedLog, false)
      }, 3000)
      return () => clearInterval(interval)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy?.status, selectedLog, autoRefresh])

  const handleClearLogs = async () => {
    if (!strategyId) return
    try {
      // Disable auto-refresh to prevent race conditions during clear
      setAutoRefresh(false)
      setClearing(true)

      const response = await pythonStrategyApi.clearLogs(strategyId)
      if (response.status === 'success') {
        showToast.success('Logs cleared', 'pythonStrategy')
        setLogFiles([])
        setSelectedLog(null)
        setLogContent(null)
      } else {
        showToast.error(response.message || 'Failed to clear logs', 'pythonStrategy')
      }
    } catch (error) {
      showToast.error('Failed to clear logs', 'pythonStrategy')
    } finally {
      setClearing(false)
      setClearDialogOpen(false)
      // Re-enable auto-refresh after operation completes
      setAutoRefresh(true)
    }
  }

  const formatLogName = (name: string) => {
    // Remove strategy ID prefix if present
    const parts = name.split('_')
    if (parts.length > 1) {
      return parts.slice(1).join('_').replace('.log', '')
    }
    return name.replace('.log', '')
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <div className="grid grid-cols-4 gap-6">
          <Skeleton className="h-[600px]" />
          <Skeleton className="h-[600px] col-span-3" />
        </div>
      </div>
    )
  }

  if (!strategy) {
    return null
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Strategy Logs</h1>
          <p className="text-muted-foreground">{strategy.name}</p>
        </div>
        <div className="flex gap-2">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="auto-refresh"
              checked={autoRefresh}
              onCheckedChange={(checked) => setAutoRefresh(checked as boolean)}
            />
            <Label htmlFor="auto-refresh" className="text-sm">
              Auto-refresh
            </Label>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => selectedLog && fetchLogContent(selectedLog)}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setClearDialogOpen(true)}
            disabled={logFiles.length === 0 || strategy.status === 'running'}
            title={strategy.status === 'running' ? 'Stop strategy first to clear logs' : undefined}
          >
            <Trash2 className="h-4 w-4 mr-2" />
            Clear All
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Log Files List */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Log Files
            </CardTitle>
            <CardDescription>{logFiles.length} file(s)</CardDescription>
          </CardHeader>
          <CardContent>
            {logFiles.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">No log files found</p>
            ) : (
              <ScrollArea className="h-[500px]">
                <div className="space-y-2">
                  {logFiles.map((log) => (
                    <button
                      key={log.name}
                      onClick={() => setSelectedLog(log.name)}
                      className={`w-full text-left p-3 rounded-lg transition-colors ${
                        selectedLog === log.name
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted hover:bg-muted/80'
                      }`}
                    >
                      <div className="font-medium text-sm truncate">{formatLogName(log.name)}</div>
                      <div className="flex items-center gap-2 mt-1 text-xs opacity-80">
                        <Clock className="h-3 w-3" />
                        {new Date(log.last_modified).toLocaleString('en-IN', {
                          day: '2-digit',
                          month: 'short',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </div>
                      <div className="flex items-center gap-2 mt-1 text-xs opacity-80">
                        <HardDrive className="h-3 w-3" />
                        {log.size_kb.toFixed(2)} KB
                      </div>
                    </button>
                  ))}
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>

        {/* Log Content */}
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="text-sm flex items-center justify-between">
              <span className="flex items-center gap-2">
                <ScrollText className="h-4 w-4" />
                Log Content
              </span>
              {strategy.status === 'running' && (
                <Badge className="bg-green-500 animate-pulse">Live</Badge>
              )}
            </CardTitle>
            {logContent && (
              <CardDescription>
                {logContent.lines} lines • {logContent.size_kb.toFixed(2)} KB • Last updated:{' '}
                {new Date(logContent.last_updated).toLocaleString()}
              </CardDescription>
            )}
          </CardHeader>
          <CardContent>
            {!selectedLog ? (
              <div className="flex items-center justify-center h-[500px] text-muted-foreground">
                Select a log file to view its contents
              </div>
            ) : loadingContent ? (
              <div className="flex items-center justify-center h-[500px]">
                <RefreshCw className="h-6 w-6 animate-spin" />
              </div>
            ) : logContent ? (
              <LogViewer
                value={logContent.content}
                height="500px"
                followTail={strategy?.status === 'running' && autoRefresh}
              />
            ) : (
              <div className="flex items-center justify-center h-[500px] text-muted-foreground">
                No content available
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Clear Logs Dialog */}
      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear All Logs</DialogTitle>
            <DialogDescription>
              Are you sure you want to clear all log files for "{strategy.name}"? This action cannot
              be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setClearDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleClearLogs} disabled={clearing}>
              {clearing ? 'Clearing...' : 'Clear All Logs'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
