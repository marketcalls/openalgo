// frontend/src/components/ai-analysis/tabs/StrategiesTab.tsx
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ChartWithIndicators } from '@/components/ai-analysis'
import { FibonacciPanel } from '@/components/ai-analysis/FibonacciPanel'
import { HarmonicPanel } from '@/components/ai-analysis/HarmonicPanel'
import { ElliottWavePanel } from '@/components/ai-analysis/ElliottWavePanel'
import { SmartMoneyDetailPanel } from '@/components/ai-analysis/SmartMoneyDetailPanel'
import { HedgeFundPanel } from '@/components/ai-analysis/HedgeFundPanel'
import type { AIAnalysisResult } from '@/types/ai-analysis'

interface StrategiesTabProps {
  analysis: AIAnalysisResult
  symbol: string
  exchange: string
  interval: string
}

type StrategyKey = 'fibonacci' | 'harmonic' | 'elliott' | 'smartmoney' | 'hedgefund'

interface StrategyConfig {
  key: StrategyKey
  icon: string
  label: string
}

const STRATEGIES: StrategyConfig[] = [
  { key: 'fibonacci', icon: 'F', label: 'Fibonacci' },
  { key: 'harmonic', icon: 'H', label: 'Harmonic' },
  { key: 'elliott', icon: 'E', label: 'Elliott Wave' },
  { key: 'smartmoney', icon: 'S', label: 'Smart Money' },
  { key: 'hedgefund', icon: '$', label: 'Hedge Fund' },
]

export function StrategiesTab({ analysis, symbol, exchange, interval }: StrategiesTabProps) {
  const [activeStrategy, setActiveStrategy] = useState<StrategyKey>('fibonacci')
  const hasCandles = analysis.candles && analysis.candles.length > 0

  function renderStrategyPanel() {
    switch (activeStrategy) {
      case 'fibonacci':
        return <FibonacciPanel symbol={symbol} exchange={exchange} interval={interval} />
      case 'harmonic':
        return <HarmonicPanel symbol={symbol} exchange={exchange} interval={interval} />
      case 'elliott':
        return <ElliottWavePanel symbol={symbol} exchange={exchange} interval={interval} />
      case 'smartmoney':
        return <SmartMoneyDetailPanel symbol={symbol} exchange={exchange} interval={interval} />
      case 'hedgefund':
        return <HedgeFundPanel symbol={symbol} exchange={exchange} interval={interval} />
      default:
        return null
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Chart (1/2) */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            {symbol} ({exchange}) - {interval}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {hasCandles ? (
            <ChartWithIndicators
              candles={analysis.candles!}
              overlays={analysis.chart_overlays}
              height={520}
            />
          ) : (
            <div className="flex items-center justify-center h-[520px] text-sm text-muted-foreground">
              No chart data available
            </div>
          )}
        </CardContent>
      </Card>

      {/* Strategy Panel (1/2) */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">Strategy Analysis</CardTitle>
          </div>
          {/* Strategy Tab Selector */}
          <div className="flex gap-1 mt-2 flex-wrap">
            {STRATEGIES.map((s) => (
              <button
                key={s.key}
                onClick={() => setActiveStrategy(s.key)}
                className={`
                  inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                  transition-colors cursor-pointer
                  ${
                    activeStrategy === s.key
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'bg-muted text-muted-foreground hover:bg-muted/80'
                  }
                `}
              >
                <span
                  className={`
                    inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold
                    ${
                      activeStrategy === s.key
                        ? 'bg-primary-foreground/20 text-primary-foreground'
                        : 'bg-background text-foreground'
                    }
                  `}
                >
                  {s.icon}
                </span>
                {s.label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="overflow-y-auto max-h-[520px]">
          {renderStrategyPanel()}
        </CardContent>
      </Card>
    </div>
  )
}
