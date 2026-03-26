// frontend/src/components/ai-analysis/SubScoresChart.tsx
import type { SubScores } from '@/types/ai-analysis'

interface SubScoresChartProps {
  scores: SubScores
}

const LABELS: Record<string, string> = {
  supertrend: 'Supertrend',
  rsi: 'RSI',
  macd: 'MACD',
  ema_cross: 'EMA Cross',
  bollinger: 'Bollinger',
  adx_strength: 'ADX',
}

export function SubScoresChart({ scores }: SubScoresChartProps) {
  const entries = Object.entries(scores).filter(([, v]) => v !== undefined)

  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No signals available</p>
  }

  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => {
        const pct = ((value + 1) / 2) * 100 // -1..+1 -> 0..100
        const color = value > 0 ? 'bg-green-500' : value < 0 ? 'bg-red-500' : 'bg-gray-400'
        return (
          <div key={key} className="flex items-center gap-2">
            <span className="w-24 text-sm text-right">{LABELS[key] ?? key}</span>
            <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden relative">
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border" />
              <div
                className={`absolute top-0 bottom-0 ${color} rounded-full`}
                style={{
                  left: value > 0 ? '50%' : `${pct}%`,
                  width: `${Math.abs(value) * 50}%`,
                }}
              />
            </div>
            <span className="w-12 text-sm text-right font-mono">{value.toFixed(2)}</span>
          </div>
        )
      })}
    </div>
  )
}
