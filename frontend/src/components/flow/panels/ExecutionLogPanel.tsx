// components/flow/panels/ExecutionLogPanel.tsx
// Displays real-time execution logs from workflow runs

import { X, CheckCircle2, XCircle, AlertCircle, Clock, Terminal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

export interface LogEntry {
  time: string
  message: string
  level: 'info' | 'error' | 'warning'
  node?: string
}

interface ExecutionLogPanelProps {
  logs: LogEntry[]
  status: 'idle' | 'running' | 'success' | 'error'
  onClose: () => void
}

export function ExecutionLogPanel({ logs, status, onClose }: ExecutionLogPanelProps) {
  const getStatusIcon = () => {
    switch (status) {
      case 'running':
        return <Clock className="h-4 w-4 animate-pulse text-amber-500" />
      case 'success':
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case 'error':
        return <XCircle className="h-4 w-4 text-red-500" />
      default:
        return <Terminal className="h-4 w-4 text-muted-foreground" />
    }
  }

  const getStatusText = () => {
    switch (status) {
      case 'running':
        return 'Executing...'
      case 'success':
        return 'Completed'
      case 'error':
        return 'Failed'
      default:
        return 'Ready'
    }
  }

  const formatTime = (isoString: string) => {
    try {
      const date = new Date(isoString)
      return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    } catch {
      return isoString
    }
  }

  const getLevelIcon = (level: string) => {
    switch (level) {
      case 'error':
        return <XCircle className="h-3.5 w-3.5 text-red-500" />
      case 'warning':
        return <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
      default:
        return <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
    }
  }

  return (
    <div className="w-80 border-l border-border bg-card flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          {getStatusIcon()}
          <span className="font-medium">Execution Log</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn(
            "text-xs px-2 py-0.5 rounded-full",
            status === 'running' && "bg-amber-500/10 text-amber-500",
            status === 'success' && "bg-green-500/10 text-green-500",
            status === 'error' && "bg-red-500/10 text-red-500",
            status === 'idle' && "bg-muted text-muted-foreground"
          )}>
            {getStatusText()}
          </span>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Log entries */}
      <ScrollArea className="flex-1">
        <div className="p-3 space-y-2">
          {logs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground text-sm">
              <Terminal className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No logs yet</p>
              <p className="text-xs mt-1">Click "Run Now" to execute the workflow</p>
            </div>
          ) : (
            logs.map((log, index) => (
              <div
                key={index}
                className={cn(
                  "rounded-lg border p-2.5 text-sm",
                  log.level === 'error' && "border-red-500/30 bg-red-500/5",
                  log.level === 'warning' && "border-amber-500/30 bg-amber-500/5",
                  log.level === 'info' && "border-border bg-background"
                )}
              >
                <div className="flex items-start gap-2">
                  <div className="mt-0.5">
                    {getLevelIcon(log.level)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs text-muted-foreground font-mono">
                        {formatTime(log.time)}
                      </span>
                    </div>
                    <p className={cn(
                      "text-sm break-words",
                      log.level === 'error' && "text-red-500",
                      log.level === 'warning' && "text-amber-500"
                    )}>
                      {log.message}
                    </p>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      {/* Footer with summary */}
      {logs.length > 0 && (
        <div className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
          <div className="flex justify-between">
            <span>{logs.length} log entries</span>
            <span>{logs.filter(l => l.level === 'error').length} errors</span>
          </div>
        </div>
      )}
    </div>
  )
}
