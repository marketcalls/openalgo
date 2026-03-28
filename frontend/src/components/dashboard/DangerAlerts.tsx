import { useState } from 'react'
import { AlertTriangle, X, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import type { AlertItem } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// DangerAlerts -- Execution: show latest 2 alerts + badge count for more.
// Research: full scrollable list.
// ---------------------------------------------------------------------------

type PriorityKey = AlertItem['priority']

const priorityStyles: Record<PriorityKey, string> = {
  critical: 'border-rose-500/50 bg-rose-950/30',
  high: 'border-orange-500/40 bg-orange-950/20',
  medium: 'border-amber-500/30 bg-amber-950/20',
  low: 'border-slate-700 bg-slate-900/30',
}

const priorityBadge: Record<PriorityKey, string> = {
  critical: 'bg-rose-600 text-white animate-pulse',
  high: 'bg-orange-600 text-white',
  medium: 'bg-amber-600 text-white',
  low: 'bg-slate-600 text-slate-300',
}

const priorityLabel: Record<PriorityKey, string> = {
  critical: 'P0',
  high: 'P1',
  medium: 'P2',
  low: 'P3',
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m ago`
  return `${Math.floor(mins / 60)}h ago`
}

export function DangerAlerts() {
  const mode = useDashboardStore((s) => s.mode)
  const storeAlerts = useDashboardStore((s) => s.alerts)
  const dismissAlert = useDashboardStore((s) => s.dismissAlert)
  const [showAll, setShowAll] = useState(false)
  const visible = storeAlerts.filter((a) => !a.dismissed)

  const dismiss = (id: string) => {
    dismissAlert(id)
  }

  const maxVisible = mode === 'execution' && !showAll ? 2 : visible.length
  const shownAlerts = visible.slice(0, maxVisible)
  const hiddenCount = visible.length - maxVisible

  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <AlertTriangle size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Alerts</span>
        </div>
        {visible.length > 0 && (
          <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[9px] font-bold text-white">
            {visible.length}
          </span>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1.5">
        {visible.length === 0 && (
          <p className="text-center text-[10px] text-slate-600 py-4">No active alerts</p>
        )}

        {shownAlerts.map((a) => (
          <div
            key={a.id}
            className={cn(
              'flex items-start gap-2 rounded-lg border p-2',
              priorityStyles[a.priority],
            )}
          >
            <span
              className={cn(
                'mt-0.5 rounded px-1 py-0.5 text-[8px] font-bold uppercase shrink-0',
                priorityBadge[a.priority],
              )}
            >
              {priorityLabel[a.priority]}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-semibold text-slate-200 truncate">{a.title}</p>
              <p className="text-[10px] text-slate-400 line-clamp-1">{a.message}</p>
              <p className="mt-0.5 text-[9px] text-slate-600">{timeAgo(a.timestamp)}</p>
            </div>
            <button
              onClick={() => dismiss(a.id)}
              className="text-slate-600 hover:text-slate-400 shrink-0"
            >
              <X size={12} />
            </button>
          </div>
        ))}

        {mode === 'execution' && hiddenCount > 0 && !showAll && (
          <button
            onClick={() => setShowAll(true)}
            className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors w-full justify-center py-1"
          >
            <ChevronDown size={10} /> {hiddenCount} more alerts
          </button>
        )}
        {mode === 'execution' && showAll && visible.length > 2 && (
          <button
            onClick={() => setShowAll(false)}
            className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors w-full justify-center py-1"
          >
            <ChevronUp size={10} /> Show less
          </button>
        )}
      </div>
    </div>
  )
}
