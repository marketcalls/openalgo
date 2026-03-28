// frontend/src/components/ai-analysis/SupportResistancePanel.tsx
import type { SupportResistanceData } from '@/types/strategy-analysis'

interface SupportResistancePanelProps {
  data: SupportResistanceData
}

export function SupportResistancePanel({ data }: SupportResistancePanelProps) {
  const { support, resistance, pivots } = data

  // Build resistance levels (R3, R2, R1) in descending order
  const resistanceLevels = resistance
    .slice()
    .sort((a, b) => b - a)
    .map((price, i) => ({
      label: `R${resistance.length - i}`,
      price,
    }))

  // Build support levels (S1, S2, S3) in descending order
  const supportLevels = support
    .slice()
    .sort((a, b) => b - a)
    .map((price, i) => ({
      label: `S${i + 1}`,
      price,
    }))

  const pivotPrice = pivots?.PP ?? pivots?.pivot ?? pivots?.P ?? null

  return (
    <div className="space-y-0.5">
      {/* Resistance levels (top = highest) */}
      {resistanceLevels.map(({ label, price }) => (
        <div
          key={label}
          className="flex items-center justify-between rounded-sm px-3 py-1.5 transition-colors hover:bg-red-50/50"
        >
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
            <span className="text-sm font-medium text-red-600">{label}</span>
          </div>
          <span className="font-mono text-sm tabular-nums text-red-600">
            {price.toFixed(2)}
          </span>
        </div>
      ))}

      {/* Pivot */}
      {pivotPrice !== null && (
        <div className="flex items-center justify-between rounded-sm border-y border-dashed border-yellow-300 bg-yellow-50/50 px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-yellow-500" />
            <span className="text-sm font-semibold text-yellow-700">Pivot</span>
          </div>
          <span className="font-mono text-sm font-semibold tabular-nums text-yellow-700">
            {pivotPrice.toFixed(2)}
          </span>
        </div>
      )}

      {/* Additional pivot levels (R1, R2, S1, S2 from pivots object) */}
      {Object.entries(pivots)
        .filter(([key]) => !['PP', 'pivot', 'P'].includes(key))
        .length > 0 && !pivotPrice && (
        <div className="flex items-center justify-between rounded-sm border-y border-dashed border-yellow-300 bg-yellow-50/50 px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-yellow-500" />
            <span className="text-sm font-semibold text-yellow-700">Pivot Levels</span>
          </div>
        </div>
      )}

      {/* Support levels (descending, so S1 is closest to price) */}
      {supportLevels.map(({ label, price }) => (
        <div
          key={label}
          className="flex items-center justify-between rounded-sm px-3 py-1.5 transition-colors hover:bg-green-50/50"
        >
          <div className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
            <span className="text-sm font-medium text-green-600">{label}</span>
          </div>
          <span className="font-mono text-sm tabular-nums text-green-600">
            {price.toFixed(2)}
          </span>
        </div>
      ))}

      {/* Empty state */}
      {resistanceLevels.length === 0 && supportLevels.length === 0 && pivotPrice === null && (
        <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
          No support/resistance data available
        </div>
      )}
    </div>
  )
}
