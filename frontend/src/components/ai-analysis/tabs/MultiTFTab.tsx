// frontend/src/components/ai-analysis/tabs/MultiTFTab.tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useMultiTimeframe } from '@/hooks/useStrategyAnalysis'
import { Loader2, AlertCircle } from 'lucide-react'

interface MultiTFTabProps {
  symbol: string
  exchange: string
}

const SIGNAL_COLORS: Record<string, string> = {
  STRONG_BUY: '#16a34a',
  BUY: '#22c55e',
  HOLD: '#eab308',
  SELL: '#ef4444',
  STRONG_SELL: '#dc2626',
}

const REGIME_COLORS: Record<string, string> = {
  TRENDING_UP: '#16a34a',
  TRENDING_DOWN: '#dc2626',
  RANGING: '#eab308',
  VOLATILE: '#f97316',
}

const TF_LABELS: Record<string, string> = {
  '1m': '1 Min',
  '5m': '5 Min',
  '15m': '15 Min',
  '30m': '30 Min',
  '1h': '1 Hour',
  '1d': 'Daily',
  '1wk': 'Weekly',
  '1mo': 'Monthly',
}

export function MultiTFTab({ symbol, exchange }: MultiTFTabProps) {
  const { data, isLoading, error } = useMultiTimeframe(symbol, exchange)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Analyzing multiple timeframes...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-destructive">
        <AlertCircle className="h-5 w-5" />
        Failed to load multi-timeframe data: {(error as Error).message}
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
        No multi-timeframe data available.
      </div>
    )
  }

  const { confluence, timeframes } = data
  const tfEntries = Object.entries(timeframes)
  const normalEntries = tfEntries.filter(([, v]) => !v.error)
  const errorEntries = tfEntries.filter(([, v]) => !!v.error)
  const confluenceColor = SIGNAL_COLORS[confluence.signal] ?? '#eab308'

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <h3 className="text-base font-semibold">Multi-Timeframe Confluence</h3>
              <Badge
                style={{ backgroundColor: confluenceColor, color: '#fff' }}
                className="text-xs"
              >
                {confluence.signal.replace('_', ' ')}
              </Badge>
            </div>
            <span className="text-sm text-muted-foreground">
              Confidence: {confluence.confidence.toFixed(1)}%
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card>
          <CardContent className="pt-4 text-center">
            <div className="text-2xl font-bold" style={{ color: confluenceColor }}>
              {confluence.score.toFixed(1)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Confluence Score</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-center">
            <div className="text-2xl font-bold">{confluence.agreement_pct.toFixed(0)}%</div>
            <div className="text-xs text-muted-foreground mt-1">Agreement</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-center">
            <div className="text-2xl font-bold text-green-600">
              {confluence.aligned_timeframes.length}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Aligned TFs</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-center">
            <div className="text-2xl font-bold text-red-500">
              {confluence.conflicting_timeframes.length}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Conflicting TFs</div>
          </CardContent>
        </Card>
      </div>

      {/* Agreement Bar */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>Bearish</span>
            <span>Agreement: {confluence.agreement_pct.toFixed(0)}%</span>
            <span>Bullish</span>
          </div>
          <div className="h-3 rounded-full overflow-hidden bg-muted flex">
            <div
              className="transition-all rounded-l-full"
              style={{
                width: `${confluence.agreement_pct}%`,
                backgroundColor: confluenceColor,
              }}
            />
          </div>
        </CardContent>
      </Card>

      {/* Per-Timeframe Grid */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Timeframe Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {/* Header row */}
            <div className="grid grid-cols-5 gap-2 text-xs text-muted-foreground font-medium pb-1 border-b">
              <span>Timeframe</span>
              <span>Signal</span>
              <span className="text-right">Score</span>
              <span>Confidence</span>
              <span>Regime</span>
            </div>
            {normalEntries.map(([tf, tfData]) => {
              const signalColor = SIGNAL_COLORS[tfData.signal] ?? '#eab308'
              const regimeColor = REGIME_COLORS[tfData.regime] ?? '#eab308'
              const scorePrefixed = tfData.score >= 0 ? `+${tfData.score.toFixed(3)}` : tfData.score.toFixed(3)

              return (
                <div key={tf} className="grid grid-cols-5 gap-2 items-center text-sm py-1.5 border-b border-muted/50">
                  <span className="font-medium">{TF_LABELS[tf] ?? tf}</span>
                  <Badge
                    style={{ backgroundColor: signalColor, color: '#fff' }}
                    className="text-xs w-fit"
                  >
                    {tfData.signal.replace('_', ' ')}
                  </Badge>
                  <span className={`text-right font-mono text-xs ${tfData.score >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                    {scorePrefixed}
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${Math.min(100, tfData.confidence)}%`,
                          backgroundColor: signalColor,
                        }}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground w-10 text-right">
                      {tfData.confidence.toFixed(0)}%
                    </span>
                  </div>
                  <Badge
                    variant="outline"
                    className="text-xs w-fit"
                    style={{ borderColor: regimeColor, color: regimeColor }}
                  >
                    {tfData.regime.replace('_', ' ')}
                  </Badge>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Error Timeframes */}
      {errorEntries.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-destructive">
              Failed Timeframes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {errorEntries.map(([tf, tfData]) => (
                <div key={tf} className="flex items-center gap-2 text-sm">
                  <AlertCircle className="h-3.5 w-3.5 text-destructive" />
                  <span className="font-medium">{TF_LABELS[tf] ?? tf}:</span>
                  <span className="text-muted-foreground">{tfData.error}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
