import { useState } from 'react'
import { useSmartMoneyDetail } from '@/hooks/useStrategyAnalysis'
import { StrategyTradeSetup } from './StrategyTradeSetup'
import { Badge } from '@/components/ui/badge'
import {
  Loader2,
  AlertCircle,
  ArrowUpDown,
  Layers,
  BarChart3,
  Zap,
} from 'lucide-react'
import type { SmartMoneyEngine } from '@/types/strategy-analysis'

interface SmartMoneyDetailPanelProps {
  symbol: string
  exchange: string
  interval: string
}

type EngineKey = 'from_scratch' | 'library'

function biasColor(bias: string): string {
  const b = bias.toUpperCase()
  if (b === 'BULLISH') return 'bg-green-100 text-green-700'
  if (b === 'BEARISH') return 'bg-red-100 text-red-700'
  return 'bg-yellow-100 text-yellow-700'
}

export function SmartMoneyDetailPanel({ symbol, exchange, interval }: SmartMoneyDetailPanelProps) {
  const { data, isLoading, error } = useSmartMoneyDetail(symbol, exchange, interval)
  const [engine, setEngine] = useState<EngineKey>('from_scratch')

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Analyzing smart money concepts...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-red-500">
        <AlertCircle className="h-4 w-4" />
        Failed to load Smart Money data
      </div>
    )
  }

  const hasLibrary = !!data.library
  const activeEngine: SmartMoneyEngine | undefined =
    engine === 'library' && data.library ? data.library : data.from_scratch

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Smart Money Concepts</h3>
        <Badge className={biasColor(data.bias)}>{data.bias.toUpperCase()}</Badge>
      </div>

      {/* Engine Toggle */}
      {hasLibrary && (
        <div className="flex gap-1 bg-muted rounded-lg p-0.5">
          <button
            className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
              engine === 'from_scratch'
                ? 'bg-background shadow text-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => setEngine('from_scratch')}
          >
            From Scratch
          </button>
          <button
            className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
              engine === 'library'
                ? 'bg-background shadow text-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => setEngine('library')}
          >
            SMC Library
          </button>
        </div>
      )}

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-2">
        <div className="text-center rounded bg-muted/50 p-2">
          <p className="text-[10px] text-muted-foreground uppercase">Active OBs</p>
          <p className="text-lg font-bold">{data.summary.active_obs}</p>
        </div>
        <div className="text-center rounded bg-muted/50 p-2">
          <p className="text-[10px] text-muted-foreground uppercase">Unfilled FVGs</p>
          <p className="text-lg font-bold">{data.summary.unfilled_fvgs}</p>
        </div>
        <div className="text-center rounded bg-muted/50 p-2">
          <p className="text-[10px] text-muted-foreground uppercase">Sweeps</p>
          <p className="text-lg font-bold">{data.summary.total_sweeps}</p>
        </div>
        <div className="text-center rounded bg-muted/50 p-2">
          <p className="text-[10px] text-muted-foreground uppercase">Breaks</p>
          <p className="text-lg font-bold">{data.summary.total_breaks}</p>
        </div>
      </div>

      {activeEngine && (
        <>
          {/* Active Order Blocks */}
          {activeEngine.active_order_blocks.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                <Layers className="h-3 w-3" /> Active Order Blocks
              </p>
              <div className="space-y-1.5">
                {activeEngine.active_order_blocks.map((ob, idx) => (
                  <div key={idx} className="flex items-center gap-2 px-2 py-1.5 rounded border text-xs">
                    <Badge
                      className={
                        ob.bullish
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }
                    >
                      {ob.bullish ? 'Bull OB' : 'Bear OB'}
                    </Badge>
                    <span className="font-mono text-muted-foreground">
                      {ob.low.toFixed(2)} - {ob.high.toFixed(2)}
                    </span>
                    {ob.source && (
                      <span className="text-muted-foreground/60 ml-auto">{ob.source}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Unfilled Fair Value Gaps */}
          {activeEngine.unfilled_fvgs.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                <BarChart3 className="h-3 w-3" /> Unfilled Fair Value Gaps
              </p>
              <div className="space-y-1.5">
                {activeEngine.unfilled_fvgs.map((fvg, idx) => (
                  <div key={idx} className="flex items-center gap-2 px-2 py-1.5 rounded border text-xs">
                    <Badge
                      className={
                        fvg.bullish
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }
                    >
                      {fvg.bullish ? 'Bullish' : 'Bearish'}
                    </Badge>
                    <span className="font-mono text-muted-foreground">
                      {fvg.bottom.toFixed(2)} - {fvg.top.toFixed(2)}
                    </span>
                    <span className="ml-auto text-muted-foreground/60">
                      gap: {fvg.gap_size.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Structure Breaks */}
          {activeEngine.structure_breaks.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                <ArrowUpDown className="h-3 w-3" /> Structure Breaks
              </p>
              <div className="space-y-1">
                {activeEngine.structure_breaks.slice(0, 5).map((sb, idx) => (
                  <div key={idx} className="flex items-center gap-2 px-2 py-1 text-xs">
                    <Badge
                      variant="outline"
                      className={
                        sb.signal.includes('BOS')
                          ? 'border-blue-300 text-blue-700'
                          : 'border-purple-300 text-purple-700'
                      }
                    >
                      {sb.signal.includes('BOS') ? 'BOS' : 'CHoCH'}
                    </Badge>
                    <span className="text-muted-foreground truncate">{sb.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Liquidity Sweeps */}
          {activeEngine.liquidity_sweeps.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                <Zap className="h-3 w-3" /> Liquidity Sweeps
              </p>
              <div className="space-y-1">
                {activeEngine.liquidity_sweeps.slice(0, 3).map((ls, idx) => (
                  <div key={idx} className="flex items-center gap-2 px-2 py-1 text-xs">
                    <Badge
                      className={
                        ls.bullish
                          ? 'bg-green-50 text-green-600'
                          : 'bg-red-50 text-red-600'
                      }
                    >
                      {ls.bullish ? 'Bull' : 'Bear'}
                    </Badge>
                    <span className="text-muted-foreground truncate">{ls.description}</span>
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
