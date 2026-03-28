import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'

// ---------------------------------------------------------------------------
// Panel -- Wrapper for every dashboard panel.
// Provides consistent styling with glassmorphism, title bar, loading skeleton,
// and error state. Updated for the trader-friendly redesign.
// ---------------------------------------------------------------------------

interface PanelProps {
  title: string
  icon?: ReactNode
  className?: string
  children?: ReactNode
  isLoading?: boolean
  error?: string | null
  /** Compact removes inner padding for chart panels */
  compact?: boolean
  /** Optional action button in the header */
  action?: ReactNode
}

export function Panel({
  title,
  icon,
  className,
  children,
  isLoading = false,
  error = null,
  compact = false,
  action,
}: PanelProps) {
  return (
    <div
      className={cn(
        'flex flex-col rounded-lg border border-slate-700/50',
        'bg-slate-900/80 backdrop-blur-sm',
        'overflow-hidden shadow-lg',
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/50 px-3 py-2">
        <div className="flex items-center gap-2">
          {icon && <span className="text-slate-400">{icon}</span>}
          <h3 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            {title}
          </h3>
        </div>
        {action}
      </div>

      {/* Body */}
      <div className={cn('flex-1 min-h-0', !compact && 'p-4')}>
        {isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-4 w-3/4 bg-slate-800" />
            <Skeleton className="h-4 w-1/2 bg-slate-800" />
            <Skeleton className="h-8 w-full bg-slate-800" />
          </div>
        ) : error ? (
          <div className="flex items-center justify-center p-4">
            <p className="text-xs text-rose-400">{error}</p>
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  )
}
