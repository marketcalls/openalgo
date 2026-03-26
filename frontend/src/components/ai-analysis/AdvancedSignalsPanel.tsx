// frontend/src/components/ai-analysis/AdvancedSignalsPanel.tsx
import { Badge } from '@/components/ui/badge'
import type { AdvancedSignals } from '@/types/ai-analysis'
import { AlertTriangle, TrendingUp, TrendingDown, Activity, Zap } from 'lucide-react'

interface AdvancedSignalsPanelProps {
  signals: AdvancedSignals
}

const SMC_LABELS: Record<string, { label: string; type: 'bullish' | 'bearish' }> = {
  smc_bos_bullish: { label: 'BOS Bullish', type: 'bullish' },
  smc_bos_bearish: { label: 'BOS Bearish', type: 'bearish' },
  smc_choch_bullish: { label: 'CHoCH Bullish', type: 'bullish' },
  smc_choch_bearish: { label: 'CHoCH Bearish', type: 'bearish' },
  smc_fvg_bullish: { label: 'FVG Bullish', type: 'bullish' },
  smc_fvg_bearish: { label: 'FVG Bearish', type: 'bearish' },
  smc_ob_bullish: { label: 'Order Block Bullish', type: 'bullish' },
  smc_ob_bearish: { label: 'Order Block Bearish', type: 'bearish' },
}

export function AdvancedSignalsPanel({ signals }: AdvancedSignalsPanelProps) {
  const smcAlerts = Object.entries(signals.smc).filter(([, v]) => v)
  const hasPatterns = smcAlerts.length > 0 || signals.candlestick.length > 0 ||
    signals.harmonic.bullish > 0 || signals.harmonic.bearish > 0 ||
    signals.divergence.rsi_bullish > 0 || signals.divergence.rsi_bearish > 0 ||
    signals.volume.exhaustion > 0 || signals.volume.vwap_bb_confluence > 0

  if (!hasPatterns) {
    return <p className="text-sm text-muted-foreground py-4 text-center">No patterns detected</p>
  }

  return (
    <div className="space-y-3">
      {/* SMC Alerts */}
      {smcAlerts.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
            <Zap className="h-3 w-3" /> Smart Money
          </p>
          <div className="flex flex-wrap gap-1">
            {smcAlerts.map(([key]) => {
              const info = SMC_LABELS[key]
              return (
                <Badge key={key} className={info?.type === 'bullish' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>
                  {info?.label ?? key}
                </Badge>
              )
            })}
          </div>
        </div>
      )}

      {/* Candlestick Patterns */}
      {signals.candlestick.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
            <Activity className="h-3 w-3" /> Candlestick
          </p>
          <div className="flex flex-wrap gap-1">
            {signals.candlestick.map((p) => (
              <Badge key={p} variant="outline" className="text-xs capitalize">
                {p.replace(/_/g, ' ')}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Harmonic */}
      {(signals.harmonic.bullish > 0 || signals.harmonic.bearish > 0) && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Harmonic:</span>
          {signals.harmonic.bullish > 0 && <Badge className="bg-green-100 text-green-700">Bullish Pattern</Badge>}
          {signals.harmonic.bearish > 0 && <Badge className="bg-red-100 text-red-700">Bearish Pattern</Badge>}
        </div>
      )}

      {/* Divergence */}
      {(signals.divergence.rsi_bullish > 0 || signals.divergence.rsi_bearish > 0) && (
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-3 w-3 text-yellow-500" />
          <span className="text-xs text-muted-foreground">RSI Divergence:</span>
          {signals.divergence.rsi_bullish > 0 && <Badge className="bg-green-50 text-green-600">Bullish</Badge>}
          {signals.divergence.rsi_bearish > 0 && <Badge className="bg-red-50 text-red-600">Bearish</Badge>}
        </div>
      )}

      {/* Volume */}
      {(signals.volume.exhaustion > 0 || signals.volume.vwap_bb_confluence > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          {signals.volume.exhaustion > 0 && <Badge variant="outline">Volume Exhaustion</Badge>}
          {signals.volume.vwap_bb_confluence > 0 && <Badge variant="outline">VWAP+BB Confluence</Badge>}
        </div>
      )}

      {/* Fibonacci */}
      {(signals.fibonacci.long > 0 || signals.fibonacci.short > 0) && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Fibonacci:</span>
          {signals.fibonacci.long > 0 && (
            <Badge className="bg-green-50 text-green-600">
              <TrendingUp className="h-3 w-3 mr-1" /> Support Level
            </Badge>
          )}
          {signals.fibonacci.short > 0 && (
            <Badge className="bg-red-50 text-red-600">
              <TrendingDown className="h-3 w-3 mr-1" /> Resistance Level
            </Badge>
          )}
        </div>
      )}
    </div>
  )
}
