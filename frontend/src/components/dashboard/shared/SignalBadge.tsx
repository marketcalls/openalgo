import { cn } from '@/lib/utils'
import type { Signal } from '@/types/dashboard'

// ─────────────────────────────────────────────────────────────────────────────
// SignalBadge — Colored badge for BUY / SELL / HOLD signals.
// Uses emerald for BUY, rose for SELL, amber for HOLD.
// ─────────────────────────────────────────────────────────────────────────────

interface SignalBadgeProps {
  signal: Signal
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const colorMap: Record<Signal, string> = {
  BUY: 'bg-emerald-600/20 text-emerald-400 border-emerald-600/40',
  SELL: 'bg-rose-600/20 text-rose-400 border-rose-600/40',
  HOLD: 'bg-amber-600/20 text-amber-400 border-amber-600/40',
}

const sizeMap = {
  sm: 'px-1.5 py-0.5 text-[10px]',
  md: 'px-2 py-0.5 text-xs',
  lg: 'px-3 py-1 text-sm',
}

export function SignalBadge({ signal, size = 'md', className }: SignalBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border font-bold tracking-wide',
        colorMap[signal],
        sizeMap[size],
        className,
      )}
    >
      {signal}
    </span>
  )
}
