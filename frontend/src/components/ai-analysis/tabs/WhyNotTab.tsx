// frontend/src/components/ai-analysis/tabs/WhyNotTab.tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertTriangle, ShieldAlert, XCircle, TrendingDown, RefreshCw } from 'lucide-react'
import type { AIAnalysisResult } from '@/types/ai-analysis'

interface WhyNotTabProps {
  analysis: AIAnalysisResult
}

function fmt(n: number | null | undefined): string {
  return n != null
    ? n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : 'N/A'
}

export function WhyNotTab({ analysis }: WhyNotTabProps) {
  const { decision, indicators, regime, signal, trade_setup } = analysis

  // Derive thesis invalidators
  const invalidators: string[] = []
  if (trade_setup?.stop_loss) {
    invalidators.push(`Price closes below ${fmt(trade_setup.stop_loss)} (stop loss level)`)
  } else if (decision?.stop_loss) {
    invalidators.push(`Price closes below ${fmt(decision.stop_loss)} (stop loss level)`)
  }
  if (indicators.rsi_14 != null && indicators.rsi_14 > 70) {
    invalidators.push('RSI drops to oversold territory')
  }
  if (indicators.rsi_14 != null && indicators.rsi_14 < 30) {
    invalidators.push('RSI rises above 50 (momentum shift)')
  }
  if (regime === 'VOLATILE') {
    invalidators.push('Volatility subsides -- current regime is Volatile')
  }

  // Derive worst-case metrics
  const riskAmount = decision?.risk_amount ?? trade_setup?.risk_amount
  const slPercent = trade_setup?.sl_percent
  const slDistance = trade_setup?.sl_distance

  // Derive "what would change my mind"
  const isBullish = signal === 'STRONG_BUY' || signal === 'BUY'
  const isBearish = signal === 'STRONG_SELL' || signal === 'SELL'

  if (!decision && !trade_setup) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col items-center justify-center py-12 text-center gap-3">
            <ShieldAlert className="h-10 w-10 text-muted-foreground" />
            <h3 className="text-base font-medium">Run analysis first to see risk factors</h3>
            <p className="text-sm text-muted-foreground max-w-md">
              Once an analysis is completed, this tab will show risk warnings,
              thesis invalidators, and worst-case scenarios.
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Section 1: Risk Factors (opposing signals) */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            Risk Factors
          </CardTitle>
        </CardHeader>
        <CardContent>
          {decision?.opposing_signals && decision.opposing_signals.length > 0 ? (
            <ul className="space-y-1.5">
              {decision.opposing_signals.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2 text-sm">
                  <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                  <span className="text-muted-foreground">{item}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No opposing signals detected.</p>
          )}
        </CardContent>
      </Card>

      {/* Section 2: Risk Warning */}
      {decision?.risk_warning && (
        <Card className="border-amber-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-600" />
              Risk Warning
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-amber-700 leading-relaxed">{decision.risk_warning}</p>
          </CardContent>
        </Card>
      )}

      {/* Section 3: Thesis Invalidators */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <XCircle className="h-4 w-4 text-red-500" />
            Thesis Invalidators
          </CardTitle>
        </CardHeader>
        <CardContent>
          {invalidators.length > 0 ? (
            <ul className="space-y-1.5">
              {invalidators.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2 text-sm">
                  <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" />
                  <span className="text-muted-foreground">{item}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              No specific invalidators identified for current conditions.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Section 4: Worst Case Scenario */}
      <Card className="border-red-200">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-red-600" />
            Worst Case Scenario
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm">
            {riskAmount != null && (
              <div className="flex items-start gap-2">
                <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" />
                <span className="text-muted-foreground">
                  Max loss: {fmt(riskAmount)}
                  {slPercent != null ? ` (${slPercent.toFixed(2)}% of position)` : ''}
                </span>
              </div>
            )}
            {slDistance != null && (
              <div className="flex items-start gap-2">
                <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" />
                <span className="text-muted-foreground">
                  If SL hits: -{slDistance.toFixed(2)}% per share
                </span>
              </div>
            )}
            {riskAmount == null && slDistance == null && (
              <p className="text-muted-foreground">
                Insufficient data for worst-case calculation.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Section 5: What Would Change My Mind */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-blue-500" />
            What Would Change My Mind
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm text-muted-foreground">
            {isBullish && (
              <>
                <p>
                  This is currently a <span className="font-medium text-green-600">bullish</span> signal.
                  The thesis would weaken if:
                </p>
                <ul className="space-y-1 ml-4">
                  <li>- Price breaks below key support levels or stop loss</li>
                  <li>- RSI divergence turns bearish while price makes new highs</li>
                  <li>- Volume dries up on upward moves (distribution pattern)</li>
                  <li>- Market regime shifts from trending to volatile or ranging</li>
                  <li>- Broader market index turns decisively bearish</li>
                </ul>
              </>
            )}
            {isBearish && (
              <>
                <p>
                  This is currently a <span className="font-medium text-red-500">bearish</span> signal.
                  The thesis would weaken if:
                </p>
                <ul className="space-y-1 ml-4">
                  <li>- Price reclaims key resistance levels with strong volume</li>
                  <li>- RSI divergence turns bullish while price makes new lows</li>
                  <li>- Smart money order blocks appear with bullish bias</li>
                  <li>- Market regime shifts from trending down to ranging or trending up</li>
                  <li>- Institutional buying detected at current levels</li>
                </ul>
              </>
            )}
            {!isBullish && !isBearish && (
              <>
                <p>
                  This is currently a <span className="font-medium text-yellow-600">neutral</span> signal.
                  A directional move would be confirmed by:
                </p>
                <ul className="space-y-1 ml-4">
                  <li>- Breakout above resistance or breakdown below support with volume</li>
                  <li>- RSI moving decisively above 60 or below 40</li>
                  <li>- ADX rising above 25 indicating trend strength building</li>
                  <li>- Smart money concepts aligning in one direction</li>
                  <li>- Multiple timeframe confluence shifting bullish or bearish</li>
                </ul>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
