import { useHarmonic } from '@/hooks/useStrategyAnalysis'
import { StrategyTradeSetup } from './StrategyTradeSetup'
import { Badge } from '@/components/ui/badge'
import { Loader2, AlertCircle, Hexagon } from 'lucide-react'

interface HarmonicPanelProps {
  symbol: string
  exchange: string
  interval: string
}

const POINT_ORDER = ['X', 'A', 'B', 'C', 'D']

export function HarmonicPanel({ symbol, exchange, interval }: HarmonicPanelProps) {
  const { data, isLoading, error } = useHarmonic(symbol, exchange, interval)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Scanning for harmonic patterns...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-red-500">
        <AlertCircle className="h-4 w-4" />
        Failed to load harmonic data
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Harmonic Patterns</h3>
        <Badge variant="outline">{data.count} found</Badge>
      </div>

      {/* Patterns */}
      {data.patterns.length === 0 ? (
        <div className="text-center py-6 text-sm text-muted-foreground">
          <Hexagon className="h-8 w-8 mx-auto mb-2 text-muted-foreground/40" />
          No harmonic patterns detected in current range
        </div>
      ) : (
        <div className="space-y-3">
          {data.patterns.map((pattern, idx) => (
            <div key={idx} className="rounded-lg border p-3 space-y-2">
              {/* Pattern Name + Direction */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge
                    className={
                      pattern.bullish
                        ? 'bg-green-100 text-green-700'
                        : 'bg-red-100 text-red-700'
                    }
                  >
                    {pattern.bullish ? 'Bullish' : 'Bearish'}
                  </Badge>
                  <span className="text-sm font-semibold">{pattern.pattern}</span>
                </div>
                {pattern.completion !== undefined && (
                  <span className="text-xs text-muted-foreground">
                    {(pattern.completion * 100).toFixed(0)}% complete
                  </span>
                )}
              </div>

              {/* Points */}
              <div className="flex gap-1 flex-wrap">
                {POINT_ORDER.filter((p) => pattern.points[p]).map((p) => (
                  <div
                    key={p}
                    className="flex flex-col items-center px-2 py-1 bg-muted/50 rounded text-xs"
                  >
                    <span className="font-semibold text-muted-foreground">{p}</span>
                    <span className="font-mono">{pattern.points[p].price.toFixed(2)}</span>
                  </div>
                ))}
              </div>

              {/* Ratios */}
              {Object.keys(pattern.ratios).length > 0 && (
                <div className="flex gap-2 flex-wrap">
                  {Object.entries(pattern.ratios).map(([key, value]) => (
                    <span key={key} className="text-xs bg-amber-50 text-amber-800 px-1.5 py-0.5 rounded">
                      {key}: {value.toFixed(3)}
                    </span>
                  ))}
                </div>
              )}

              {/* Description */}
              {pattern.description && (
                <p className="text-xs text-muted-foreground">{pattern.description}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Trade Setup */}
      <StrategyTradeSetup levels={data.trade_levels} />
    </div>
  )
}
