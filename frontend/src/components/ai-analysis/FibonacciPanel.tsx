import { useFibonacci } from '@/hooks/useStrategyAnalysis'
import { StrategyTradeSetup } from './StrategyTradeSetup'
import { Badge } from '@/components/ui/badge'
import { TrendingUp, TrendingDown, Loader2, AlertCircle } from 'lucide-react'

interface FibonacciPanelProps {
  symbol: string
  exchange: string
  interval: string
}

export function FibonacciPanel({ symbol, exchange, interval }: FibonacciPanelProps) {
  const { data, isLoading, error } = useFibonacci(symbol, exchange, interval)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Calculating Fibonacci levels...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-red-500">
        <AlertCircle className="h-4 w-4" />
        Failed to load Fibonacci data
      </div>
    )
  }

  const isUptrend = data.trend === 'uptrend'
  const TrendIcon = isUptrend ? TrendingUp : TrendingDown

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Fibonacci Analysis</h3>
        <Badge className={isUptrend ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>
          <TrendIcon className="h-3 w-3 mr-1" />
          {data.trend}
        </Badge>
      </div>

      {/* Swing Points + Current Price */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded bg-red-50 p-2">
          <p className="text-[10px] text-muted-foreground uppercase">Swing High</p>
          <p className="font-mono text-sm font-semibold text-red-700">
            {data.swing_high?.price.toFixed(2) ?? '—'}
          </p>
        </div>
        <div className="rounded bg-muted p-2">
          <p className="text-[10px] text-muted-foreground uppercase">Current</p>
          <p className="font-mono text-sm font-semibold">
            {data.current_price.toFixed(2)}
          </p>
        </div>
        <div className="rounded bg-green-50 p-2">
          <p className="text-[10px] text-muted-foreground uppercase">Swing Low</p>
          <p className="font-mono text-sm font-semibold text-green-700">
            {data.swing_low?.price.toFixed(2) ?? '—'}
          </p>
        </div>
      </div>

      {/* Retracements */}
      {data.retracements.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">Retracements</p>
          <div className="space-y-1.5">
            {data.retracements.map((level) => {
              const isNearest =
                data.nearest_retracement &&
                Math.abs(level.price - data.nearest_retracement.price) < 0.01
              return (
                <div
                  key={level.label}
                  className={`flex items-center gap-2 px-2 py-1 rounded text-xs ${
                    isNearest ? 'border-2 border-blue-400 bg-blue-50' : 'bg-muted/50'
                  }`}
                >
                  <span className="w-14 font-medium text-muted-foreground shrink-0">
                    {level.label}
                  </span>
                  <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        isNearest ? 'bg-blue-500' : 'bg-amber-400'
                      }`}
                      style={{ width: `${Math.min(level.ratio * 100, 100)}%` }}
                    />
                  </div>
                  <span className="font-mono w-20 text-right shrink-0">
                    {level.price.toFixed(2)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Extensions */}
      {data.extensions.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">Extensions</p>
          <div className="space-y-1">
            {data.extensions.map((level) => (
              <div
                key={level.label}
                className="flex justify-between items-center px-2 py-1 bg-muted/30 rounded text-xs"
              >
                <span className="font-medium text-muted-foreground">{level.label}</span>
                <span className="font-mono">{level.price.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Nearest Level Callout */}
      {data.nearest_retracement && (
        <div className="flex items-center gap-2 p-2 bg-blue-50 rounded border border-blue-200">
          <span className="text-xs text-blue-700">
            Nearest Level: <strong>{data.nearest_retracement.label}</strong> at{' '}
            <span className="font-mono">{data.nearest_retracement.price.toFixed(2)}</span>
          </span>
        </div>
      )}

      {/* Trade Setup */}
      <StrategyTradeSetup levels={data.trade_levels} />
    </div>
  )
}
