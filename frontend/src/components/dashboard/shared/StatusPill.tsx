import { cn } from '@/lib/utils'
import type { Bias } from '@/types/dashboard'

// ─────────────────────────────────────────────────────────────────────────────
// StatusPill — Colored pill for bullish / bearish / neutral.
// ─────────────────────────────────────────────────────────────────────────────

interface StatusPillProps {
  bias: Bias
  className?: string
}

const pillStyles: Record<Bias, string> = {
  bullish: 'bg-emerald-950 text-emerald-400 border-emerald-700',
  bearish: 'bg-rose-950 text-rose-400 border-rose-700',
  neutral: 'bg-slate-800 text-slate-400 border-slate-600',
}

export function StatusPill({ bias, className }: StatusPillProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
        pillStyles[bias],
        className,
      )}
    >
      {bias}
    </span>
  )
}
