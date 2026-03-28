import { useElliottWave } from '@/hooks/useStrategyAnalysis'
import { StrategyTradeSetup } from './StrategyTradeSetup'
import { Badge } from '@/components/ui/badge'
import { Loader2, AlertCircle, Waves } from 'lucide-react'

interface ElliottWavePanelProps {
  symbol: string
  exchange: string
  interval: string
}

const PHASE_LABELS: Record<string, string> = {
  impulse_completing: 'Impulse Wave Completing',
  post_impulse: 'Post-Impulse (Correction Expected)',
  correction_completing: 'Correction Completing',
  unknown: 'No Clear Wave Structure',
}

function phaseBadgeColor(phase: string): string {
  switch (phase) {
    case 'impulse_completing':
      return 'bg-green-100 text-green-700'
    case 'post_impulse':
      return 'bg-yellow-100 text-yellow-700'
    case 'correction_completing':
      return 'bg-blue-100 text-blue-700'
    default:
      return 'bg-muted text-muted-foreground'
  }
}

export function ElliottWavePanel({ symbol, exchange, interval }: ElliottWavePanelProps) {
  const { data, isLoading, error } = useElliottWave(symbol, exchange, interval)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Analyzing wave structure...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-red-500">
        <AlertCircle className="h-4 w-4" />
        Failed to load Elliott Wave data
      </div>
    )
  }

  const hasWaves = data.impulse_waves.length > 0 || data.corrective_waves.length > 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Elliott Wave Theory</h3>
        <Badge className={phaseBadgeColor(data.current_phase)}>
          {PHASE_LABELS[data.current_phase] ?? data.current_phase}
        </Badge>
      </div>

      {!hasWaves ? (
        <div className="text-center py-6 text-sm text-muted-foreground">
          <Waves className="h-8 w-8 mx-auto mb-2 text-muted-foreground/40" />
          No clear Elliott Wave structures detected
        </div>
      ) : (
        <>
          {/* Impulse Waves */}
          {data.impulse_waves.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2">Impulse Waves</p>
              <div className="space-y-2">
                {data.impulse_waves.map((iw, idx) => (
                  <div key={idx} className="rounded-lg border p-3 space-y-2">
                    {/* Badges */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge
                        className={
                          iw.bullish
                            ? 'bg-green-100 text-green-700'
                            : 'bg-red-100 text-red-700'
                        }
                      >
                        {iw.bullish ? 'Bullish' : 'Bearish'}
                      </Badge>
                      <Badge variant="outline" className="text-xs capitalize">
                        {iw.degree}
                      </Badge>
                      <Badge
                        className={
                          iw.valid
                            ? 'bg-green-50 text-green-600'
                            : 'bg-yellow-50 text-yellow-600'
                        }
                      >
                        {iw.valid ? 'Valid' : 'Partial'}
                      </Badge>
                    </div>

                    {/* Wave Points (W1-W5) */}
                    <div className="flex gap-1 flex-wrap">
                      {iw.waves.map((wp) => (
                        <div
                          key={wp.wave}
                          className="flex flex-col items-center px-2 py-1 bg-muted/50 rounded text-xs"
                        >
                          <span className="font-semibold text-muted-foreground">{wp.wave}</span>
                          <span className="font-mono">{wp.price.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>

                    {/* Violations */}
                    {iw.violations.length > 0 && (
                      <div className="space-y-0.5">
                        {iw.violations.map((v, vi) => (
                          <p key={vi} className="text-xs text-yellow-600 flex items-center gap-1">
                            <AlertCircle className="h-3 w-3 shrink-0" />
                            {v}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Corrective Waves */}
          {data.corrective_waves.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2">Corrective Waves</p>
              <div className="space-y-2">
                {data.corrective_waves.map((cw, idx) => (
                  <div key={idx} className="rounded-lg border p-3 space-y-2">
                    {/* Direction */}
                    <Badge
                      className={
                        cw.bullish
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }
                    >
                      {cw.bullish ? 'Bullish' : 'Bearish'}
                    </Badge>

                    {/* A-B-C Points */}
                    <div className="flex gap-1 flex-wrap">
                      {cw.waves.map((wp) => (
                        <div
                          key={wp.wave}
                          className="flex flex-col items-center px-2 py-1 bg-muted/50 rounded text-xs"
                        >
                          <span className="font-semibold text-muted-foreground">{wp.wave}</span>
                          <span className="font-mono">{wp.price.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>

                    {/* Ratios */}
                    <div className="flex gap-3 text-xs">
                      <span className="text-muted-foreground">
                        B Retrace:{' '}
                        <span className="font-mono font-medium">
                          {(cw.ratios.B_retrace_A * 100).toFixed(1)}%
                        </span>
                      </span>
                      <span className="text-muted-foreground">
                        C/A:{' '}
                        <span className="font-mono font-medium">
                          {cw.ratios.C_to_A.toFixed(3)}
                        </span>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Trade Setup */}
      <StrategyTradeSetup levels={data.trade_levels} />
    </div>
  )
}
