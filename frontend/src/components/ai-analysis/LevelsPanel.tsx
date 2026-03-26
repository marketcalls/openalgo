// frontend/src/components/ai-analysis/LevelsPanel.tsx
interface LevelsPanelProps {
  cpr: Record<string, number>
  currentPrice?: number
}

const LEVEL_ORDER = ['r3', 'r2', 'r1', 'tc', 'pivot', 'bc', 's1', 's2', 's3']
const LEVEL_LABELS: Record<string, string> = {
  pivot: 'Pivot', bc: 'BC', tc: 'TC',
  r1: 'R1', r2: 'R2', r3: 'R3',
  s1: 'S1', s2: 'S2', s3: 'S3',
}

export function LevelsPanel({ cpr, currentPrice }: LevelsPanelProps) {
  const levels = LEVEL_ORDER
    .filter((k) => cpr[k] !== undefined)
    .map((k) => ({ key: k, label: LEVEL_LABELS[k] ?? k, value: cpr[k] }))

  if (levels.length === 0) {
    return <p className="text-xs text-muted-foreground">No levels available</p>
  }

  return (
    <div className="space-y-0.5">
      {levels.map(({ key, label, value }) => {
        const isResistance = key.startsWith('r') || key === 'tc'
        const isSupport = key.startsWith('s') || key === 'bc'
        const isPivot = key === 'pivot'
        const isNearPrice = currentPrice && Math.abs(value - currentPrice) / currentPrice < 0.005

        return (
          <div
            key={key}
            className={`flex justify-between text-xs px-2 py-0.5 rounded ${
              isNearPrice ? 'bg-yellow-50 font-bold' :
              isPivot ? 'bg-blue-50' :
              isResistance ? 'text-red-600' :
              isSupport ? 'text-green-600' : ''
            }`}
          >
            <span>{label}</span>
            <span className="font-mono">{value.toFixed(2)}</span>
          </div>
        )
      })}
    </div>
  )
}
