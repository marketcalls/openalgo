// frontend/src/components/ai-analysis/StrategyTradeSetup.tsx
import type { StrategyTradeLevels } from '@/types/strategy-analysis'

interface StrategyTradeSetupProps {
  levels: StrategyTradeLevels | null
}

const DIRECTION_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  bullish: { bg: 'bg-green-100', text: 'text-green-700', label: 'Bullish' },
  bearish: { bg: 'bg-red-100', text: 'text-red-700', label: 'Bearish' },
  neutral: { bg: 'bg-yellow-100', text: 'text-yellow-700', label: 'Neutral' },
}

export function StrategyTradeSetup({ levels }: StrategyTradeSetupProps) {
  if (!levels) {
    return (
      <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
        No trade setup available
      </div>
    )
  }

  const dirStyle = DIRECTION_STYLES[levels.direction] ?? DIRECTION_STYLES.neutral
  const confidencePct = Math.max(0, Math.min(100, Math.round(levels.confidence * 100)))

  return (
    <div className="space-y-4">
      {/* Direction badge */}
      <div className="flex items-center gap-2">
        <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${dirStyle.bg} ${dirStyle.text}`}>
          {dirStyle.label}
        </span>
      </div>

      {/* Entry zone */}
      <div className="rounded-md border px-3 py-2">
        <div className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Entry Zone
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="font-mono text-sm tabular-nums">
            {levels.entry.low.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">-</span>
          <span className="font-mono text-sm tabular-nums">
            {levels.entry.high.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">
            (mid: {levels.entry.mid.toFixed(2)})
          </span>
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Source: {levels.entry.source}
        </div>
      </div>

      {/* Stop loss */}
      <div className="rounded-md border border-red-200 bg-red-50/50 px-3 py-2">
        <div className="mb-1 text-xs font-medium uppercase tracking-wider text-red-600">
          Stop Loss
        </div>
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-sm font-semibold tabular-nums text-red-700">
            {levels.stop_loss.price.toFixed(2)}
          </span>
          <span className="text-xs text-red-500">
            ({levels.stop_loss.distance_pct.toFixed(2)}% away)
          </span>
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Source: {levels.stop_loss.source}
        </div>
      </div>

      {/* Targets table */}
      {levels.targets.length > 0 && (
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30 text-xs">
                <th className="px-3 py-1.5 text-left font-medium">Target</th>
                <th className="px-3 py-1.5 text-right font-medium">Price</th>
                <th className="px-3 py-1.5 text-right font-medium">R:R</th>
                <th className="px-3 py-1.5 text-left font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {levels.targets.map((target, idx) => (
                <tr
                  key={`${target.label}-${idx}`}
                  className="border-b last:border-0"
                >
                  <td className="px-3 py-1.5 font-medium text-green-700">
                    {target.label}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                    {target.price.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums text-blue-600">
                    {target.rr_ratio.toFixed(1)}:1
                  </td>
                  <td className="px-3 py-1.5 text-xs text-muted-foreground">
                    {target.source}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Confidence bar */}
      <div>
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="font-medium text-muted-foreground">Confidence</span>
          <span className="font-semibold tabular-nums">{confidencePct}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${confidencePct}%`,
              backgroundColor:
                confidencePct > 70 ? '#16a34a' : confidencePct > 40 ? '#ca8a04' : '#dc2626',
            }}
          />
        </div>
      </div>

      {/* Reasoning bullets */}
      {levels.reasoning.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Reasoning
          </div>
          <ul className="space-y-1">
            {levels.reasoning.map((reason, idx) => (
              <li key={idx} className="flex items-start gap-2 text-xs leading-relaxed">
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-green-500" />
                <span className="text-muted-foreground">{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
