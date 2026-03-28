import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// Sparkline — Tiny inline SVG chart for quick trend visualization.
// ─────────────────────────────────────────────────────────────────────────────

interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  strokeColor?: string
  className?: string
}

export function Sparkline({
  data,
  width = 80,
  height = 24,
  strokeColor,
  className,
}: SparklineProps) {
  if (data.length < 2) return null

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const padding = 1

  const points = data
    .map((v, i) => {
      const x = padding + (i / (data.length - 1)) * (width - 2 * padding)
      const y = height - padding - ((v - min) / range) * (height - 2 * padding)
      return `${x},${y}`
    })
    .join(' ')

  // Determine color from trend: last vs first
  const color =
    strokeColor ?? (data[data.length - 1] >= data[0] ? '#10b981' : '#f43f5e')

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn('inline-block', className)}
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
