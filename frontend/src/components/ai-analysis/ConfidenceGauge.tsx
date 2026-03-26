// frontend/src/components/ai-analysis/ConfidenceGauge.tsx
interface ConfidenceGaugeProps {
  confidence: number // 0-100
}

export function ConfidenceGauge({ confidence }: ConfidenceGaugeProps) {
  const radius = 40
  const circumference = 2 * Math.PI * radius
  const progress = (confidence / 100) * circumference
  const color = confidence > 70 ? '#16a34a' : confidence > 40 ? '#ca8a04' : '#dc2626'

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="8" />
        <circle
          cx="50" cy="50" r={radius} fill="none"
          stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          transform="rotate(-90 50 50)"
        />
        <text x="50" y="55" textAnchor="middle" className="text-lg font-bold fill-current">
          {confidence}%
        </text>
      </svg>
      <span className="text-xs text-muted-foreground">Confidence</span>
    </div>
  )
}
