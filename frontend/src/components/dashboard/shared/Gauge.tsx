import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// Gauge — Circular gauge component (0-100).
// Uses SVG arcs. Color transitions: green -> amber -> red.
// ─────────────────────────────────────────────────────────────────────────────

interface GaugeProps {
  value: number
  max?: number
  size?: number
  strokeWidth?: number
  label?: string
  className?: string
}

function getGaugeColor(pct: number): string {
  if (pct >= 70) return '#10b981' // emerald-500
  if (pct >= 40) return '#f59e0b' // amber-500
  return '#f43f5e' // rose-500
}

export function Gauge({
  value,
  max = 100,
  size = 80,
  strokeWidth = 6,
  label,
  className,
}: GaugeProps) {
  const pct = Math.min(Math.max((value / max) * 100, 0), 100)
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (pct / 100) * circumference
  const color = getGaugeColor(pct)

  return (
    <div className={cn('flex flex-col items-center gap-1', className)}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Background track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-slate-800"
        />
        {/* Value arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-500 ease-out"
        />
      </svg>
      {/* Center text */}
      <div className="absolute flex flex-col items-center justify-center" style={{ width: size, height: size }}>
        <span className="text-sm font-bold text-slate-100">{Math.round(pct)}</span>
      </div>
      {label && (
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
          {label}
        </span>
      )}
    </div>
  )
}
