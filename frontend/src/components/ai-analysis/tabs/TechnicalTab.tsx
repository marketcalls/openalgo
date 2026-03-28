// frontend/src/components/ai-analysis/tabs/TechnicalTab.tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  ChartWithIndicators,
  SignalBadge,
  ConfidenceGauge,
  SubScoresChart,
  MLConfidenceBar,
  LevelsPanel,
  AdvancedSignalsPanel,
  LLMCommentary,
  IndicatorTable,
} from '@/components/ai-analysis'
import { SignalGauge } from '@/components/ai-analysis/SignalGauge'
import type { AIAnalysisResult } from '@/types/ai-analysis'
import { REGIME_CONFIG } from '@/types/ai-analysis'

interface TechnicalTabProps {
  analysis: AIAnalysisResult
  symbol: string
  exchange: string
  interval: string
}

export function TechnicalTab({ analysis, symbol, exchange, interval }: TechnicalTabProps) {
  const hasCandles = analysis.candles && analysis.candles.length > 0
  const hasAdvanced = !!analysis.advanced
  const hasCpr = hasAdvanced && analysis.advanced!.cpr && Object.keys(analysis.advanced!.cpr).length > 0
  const regimeConfig = REGIME_CONFIG[analysis.regime]

  return (
    <div className="space-y-4">
      {/* Row 1: Chart + Signal Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Chart (2/3 width) */}
        <Card className="lg:col-span-2">
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
                height={420}
              />
            ) : (
              <div className="flex items-center justify-center h-[420px] text-sm text-muted-foreground">
                No chart data available
              </div>
            )}
          </CardContent>
        </Card>

        {/* Signal Panel (1/3 width) */}
        <Card className="lg:col-span-1 overflow-y-auto max-h-[540px]">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Signal Overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Signal Badge + Confidence Gauge */}
            <div className="flex items-center justify-between">
              <SignalBadge signal={analysis.signal} size="lg" />
              <ConfidenceGauge confidence={analysis.confidence} />
            </div>

            {/* Signal Gauge */}
            <SignalGauge score={analysis.score} signal={analysis.signal} />

            {/* Market Regime */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Market Regime:</span>
              <Badge variant="outline" className="text-xs">
                {regimeConfig.label}
              </Badge>
            </div>

            {/* Sub Scores */}
            <div>
              <h4 className="text-xs font-medium text-muted-foreground mb-2">Indicator Scores</h4>
              <SubScoresChart scores={analysis.sub_scores} />
            </div>

            {/* ML Confidence */}
            {hasAdvanced && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-2">ML Confidence</h4>
                <MLConfidenceBar
                  buyConfidence={analysis.advanced!.ml_confidence.buy}
                  sellConfidence={analysis.advanced!.ml_confidence.sell}
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Row 2: Pivot Levels + Pattern Alerts + AI Commentary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Pivot Levels */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Pivot Levels (CPR)</CardTitle>
          </CardHeader>
          <CardContent>
            {hasCpr ? (
              <LevelsPanel
                cpr={analysis.advanced!.cpr}
                currentPrice={analysis.candles?.[analysis.candles.length - 1]?.close}
              />
            ) : (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No pivot data available
              </p>
            )}
          </CardContent>
        </Card>

        {/* Pattern Alerts */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Pattern Alerts</CardTitle>
          </CardHeader>
          <CardContent>
            {hasAdvanced ? (
              <AdvancedSignalsPanel signals={analysis.advanced!} />
            ) : (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No advanced signals available
              </p>
            )}
          </CardContent>
        </Card>

        {/* AI Commentary */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">AI Commentary</CardTitle>
          </CardHeader>
          <CardContent>
            <LLMCommentary analysis={analysis} />
          </CardContent>
        </Card>
      </div>

      {/* Row 3: Indicator Table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Indicator Values</CardTitle>
        </CardHeader>
        <CardContent>
          <IndicatorTable indicators={analysis.indicators} />
        </CardContent>
      </Card>
    </div>
  )
}
