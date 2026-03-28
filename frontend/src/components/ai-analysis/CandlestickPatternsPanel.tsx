// frontend/src/components/ai-analysis/CandlestickPatternsPanel.tsx
import type { CandlestickPattern } from '@/types/strategy-analysis'

interface CandlestickPatternsPanelProps {
  patterns: CandlestickPattern[]
}

export function CandlestickPatternsPanel({ patterns }: CandlestickPatternsPanelProps) {
  if (!patterns || patterns.length === 0) {
    return (
      <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
        No patterns detected
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      {patterns.map((pattern, idx) => {
        const isBullish = pattern.bullish === true
        const isBearish = pattern.bullish === false
        const isStrong = (pattern.strength ?? 0) > 100

        let arrowIcon: string
        let arrowColor: string

        if (isBullish) {
          arrowIcon = '\u25B2' // ▲
          arrowColor = 'text-green-500'
        } else if (isBearish) {
          arrowIcon = '\u25BC' // ▼
          arrowColor = 'text-red-500'
        } else {
          arrowIcon = '\u25C6' // ◆
          arrowColor = 'text-yellow-500'
        }

        return (
          <div
            key={`${pattern.name}-${idx}`}
            className="flex items-center gap-2 rounded-md border px-3 py-2"
          >
            <span className={`text-sm ${arrowColor}`}>{arrowIcon}</span>

            <span className="flex-1 text-sm font-medium">{pattern.name}</span>

            {isStrong && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                Strong
              </span>
            )}

            {isBullish && (
              <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                Bullish
              </span>
            )}
            {isBearish && (
              <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                Bearish
              </span>
            )}
            {!isBullish && !isBearish && (
              <span className="rounded-full bg-yellow-50 px-2 py-0.5 text-xs font-medium text-yellow-700">
                Neutral
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
