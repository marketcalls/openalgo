// frontend/src/components/ai-analysis/SignalGauge.tsx
import { useMemo } from 'react'

interface SignalGaugeProps {
  score: number // -1 to +1
  signal: string // STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
}

const SIGNAL_COLORS: Record<string, string> = {
  STRONG_BUY: '#16a34a',
  BUY: '#22c55e',
  HOLD: '#eab308',
  SELL: '#ef4444',
  STRONG_SELL: '#dc2626',
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180
  return {
    x: cx + r * Math.cos(rad),
    y: cy - r * Math.sin(rad),
  }
}

function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, r, startAngle)
  const end = polarToCartesian(cx, cy, r, endAngle)
  const largeArc = endAngle - startAngle > 180 ? 1 : 0
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`
}

export function SignalGauge({ score, signal }: SignalGaugeProps) {
  const clampedScore = Math.max(-1, Math.min(1, score))
  const color = SIGNAL_COLORS[signal] ?? SIGNAL_COLORS.HOLD

  // Map score from [-1, +1] to angle [180, 0] (left = SELL, right = BUY)
  // score -1 => 180 degrees (left), score +1 => 0 degrees (right)
  const needleAngle = useMemo(() => {
    return 180 - ((clampedScore + 1) / 2) * 180
  }, [clampedScore])

  // Arc fill: proportion from 0% to 100%
  const fillFraction = (clampedScore + 1) / 2

  const cx = 100
  const cy = 100
  const r = 90

  // Needle end point
  const needleEnd = polarToCartesian(cx, cy, r - 10, needleAngle)

  // Full arc path for background (180 to 0 degrees, left to right)
  const bgArc = describeArc(cx, cy, r, 0, 180)

  // Colored arc: from left side (180) sweeping to the needle position
  const coloredArc = fillFraction > 0.005
    ? describeArc(cx, cy, r, needleAngle, 180)
    : ''

  // Total arc length for the semicircle
  const arcLength = Math.PI * r
  const filledLength = fillFraction * arcLength

  const signalLabel = signal.replace(/_/g, ' ')

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 110" width="200" height="110" className="overflow-visible">
        {/* Background arc */}
        <path
          d={bgArc}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth="12"
          strokeLinecap="round"
        />

        {/* Colored arc */}
        {coloredArc && (
          <path
            d={bgArc}
            fill="none"
            stroke={color}
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={`${filledLength} ${arcLength}`}
            strokeDashoffset={0}
            className="transition-all duration-700 ease-out"
          />
        )}

        {/* Tick marks at key positions */}
        {[0, 45, 90, 135, 180].map((angle) => {
          const outer = polarToCartesian(cx, cy, r + 6, angle)
          const inner = polarToCartesian(cx, cy, r - 6, angle)
          return (
            <line
              key={angle}
              x1={outer.x}
              y1={outer.y}
              x2={inner.x}
              y2={inner.y}
              stroke="#9ca3af"
              strokeWidth="1.5"
            />
          )
        })}

        {/* Needle */}
        <line
          x1={cx}
          y1={cy}
          x2={needleEnd.x}
          y2={needleEnd.y}
          stroke="#1f2937"
          strokeWidth="2.5"
          strokeLinecap="round"
          className="transition-all duration-700 ease-out"
        />

        {/* Center dot */}
        <circle cx={cx} cy={cy} r="5" fill="#1f2937" />
        <circle cx={cx} cy={cy} r="3" fill="white" />

        {/* Score text */}
        <text
          x={cx}
          y={cy + 4}
          textAnchor="middle"
          fontSize="11"
          fontWeight="600"
          fill={color}
          className="select-none"
        >
          {clampedScore > 0 ? '+' : ''}{clampedScore.toFixed(2)}
        </text>

        {/* SELL label (left) */}
        <text
          x={14}
          y={108}
          textAnchor="start"
          fontSize="10"
          fontWeight="500"
          fill="#ef4444"
          className="select-none"
        >
          SELL
        </text>

        {/* BUY label (right) */}
        <text
          x={186}
          y={108}
          textAnchor="end"
          fontSize="10"
          fontWeight="500"
          fill="#22c55e"
          className="select-none"
        >
          BUY
        </text>
      </svg>

      {/* Signal label below */}
      <span
        className="mt-1 text-xs font-semibold tracking-wide uppercase"
        style={{ color }}
      >
        {signalLabel}
      </span>
    </div>
  )
}
