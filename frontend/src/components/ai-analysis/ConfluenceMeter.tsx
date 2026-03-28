// frontend/src/components/ai-analysis/ConfluenceMeter.tsx

interface ConfluenceMeterProps {
  score: number // 0-100
  bullishCount: number
  bearishCount: number
  neutralCount: number
  color: string // action color hex
}

export function ConfluenceMeter({
  score,
  bullishCount,
  bearishCount,
  neutralCount,
  color,
}: ConfluenceMeterProps) {
  const clampedScore = Math.max(0, Math.min(100, score))

  const r = 34
  const circumference = 2 * Math.PI * r
  const progress = (clampedScore / 100) * circumference
  const offset = circumference - progress

  return (
    <div className="flex flex-col items-center gap-2">
      <svg viewBox="0 0 80 80" width="80" height="80">
        {/* Background circle */}
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth="6"
        />

        {/* Filled arc */}
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 40 40)"
          className="transition-all duration-700 ease-out"
        />

        {/* Percentage text */}
        <text
          x="40"
          y="37"
          textAnchor="middle"
          fontSize="14"
          fontWeight="700"
          fill={color}
          className="select-none"
        >
          {Math.round(clampedScore)}%
        </text>

        {/* Sub-label */}
        <text
          x="40"
          y="49"
          textAnchor="middle"
          fontSize="7"
          fill="#6b7280"
          className="select-none"
        >
          confluence
        </text>
      </svg>

      {/* Vote counts */}
      <div className="flex items-center gap-3 text-xs">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
          <span className="tabular-nums text-green-700">{bullishCount}</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-full bg-gray-400" />
          <span className="tabular-nums text-gray-600">{neutralCount}</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
          <span className="tabular-nums text-red-700">{bearishCount}</span>
        </span>
      </div>
    </div>
  )
}
