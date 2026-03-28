import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useDailyReport } from '@/hooks/useStrategyAnalysis'
import {
  Loader2, AlertCircle, TrendingUp, TrendingDown, Minus,
  BarChart3, Newspaper, Target,
} from 'lucide-react'

interface Props {
  exchange: string
}

const SIGNAL_BADGE: Record<string, string> = {
  STRONG_BUY: 'bg-green-600 text-white',
  BUY: 'bg-green-400 text-white',
  HOLD: 'bg-yellow-400 text-yellow-900',
  SELL: 'bg-orange-500 text-white',
  STRONG_SELL: 'bg-red-600 text-white',
}

const STATUS_STYLE: Record<string, string> = {
  bullish: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  bearish: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  neutral: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
  mixed: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
}

function fmt(n: number | null | undefined): string {
  return n != null
    ? n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : 'N/A'
}

function fmtPct(n: number | null | undefined): string {
  return n != null ? `${n.toFixed(2)}%` : 'N/A'
}

export function DailyReportTab({ exchange }: Props) {
  const { data, isLoading, error } = useDailyReport(exchange)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Generating daily report for {exchange}...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12 gap-2 text-destructive">
        <AlertCircle className="h-5 w-5" />
        Failed to generate daily report: {(error as Error).message}
      </div>
    )
  }

  if (!data) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        No report data available. Try again later.
      </div>
    )
  }

  const overview = data.market_overview

  return (
    <div className="space-y-4">
      {/* Market Summary */}
      <Card className="border-l-4 border-l-blue-500">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>Market Summary -- {data.report_date}</span>
            <span className="text-xs text-muted-foreground">{data.report_time}</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed text-foreground/90">{data.market_summary}</p>
          <div className="mt-2 text-xs text-muted-foreground">
            {data.symbols_analyzed} symbols analyzed on {data.exchange}
          </div>
        </CardContent>
      </Card>

      {/* Market Overview */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            Market Overview
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 mb-4">
            <Badge className={STATUS_STYLE[overview.status?.toLowerCase()] ?? 'bg-muted'}>
              {overview.status}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {overview.total_symbols} symbols
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">{fmtPct(overview.bullish_pct)}</div>
              <div className="text-xs text-muted-foreground">Bullish</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">{fmtPct(overview.bearish_pct)}</div>
              <div className="text-xs text-muted-foreground">Bearish</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-yellow-600">{fmtPct(overview.neutral_pct)}</div>
              <div className="text-xs text-muted-foreground">Neutral</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold">{overview.avg_score.toFixed(3)}</div>
              <div className="text-xs text-muted-foreground">Avg Score</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold">{fmtPct(overview.avg_confidence)}</div>
              <div className="text-xs text-muted-foreground">Avg Confidence</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Signal Distribution */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Signal Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-3">
            {(['STRONG_BUY', 'BUY', 'HOLD', 'SELL', 'STRONG_SELL'] as const).map((sig) => {
              const count = data.signal_distribution[sig] ?? 0
              return (
                <Badge key={sig} className={`${SIGNAL_BADGE[sig]} text-sm px-3 py-1`}>
                  {sig.replace('_', ' ')}: {count}
                </Badge>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Top Gainers & Losers */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Top Gainers */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-green-500" />
              Top Gainers
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.top_gainers.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No gainers data</p>
            ) : (
              <div className="space-y-2">
                {data.top_gainers.slice(0, 5).map((g) => (
                  <div key={g.symbol} className="flex items-center justify-between p-2 rounded border">
                    <div>
                      <span className="text-sm font-medium">{g.symbol}</span>
                      <span className="text-xs text-muted-foreground ml-2">{fmt(g.price)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono text-green-600">+{fmtPct(g.change_pct)}</span>
                      <Badge className={`${SIGNAL_BADGE[g.signal] ?? 'bg-muted'} text-xs`}>
                        {g.signal.replace('_', ' ')}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Top Losers */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-red-500" />
              Top Losers
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.top_losers.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No losers data</p>
            ) : (
              <div className="space-y-2">
                {data.top_losers.slice(0, 5).map((l) => (
                  <div key={l.symbol} className="flex items-center justify-between p-2 rounded border">
                    <div>
                      <span className="text-sm font-medium">{l.symbol}</span>
                      <span className="text-xs text-muted-foreground ml-2">{fmt(l.price)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono text-red-600">{fmtPct(l.change_pct)}</span>
                      <Badge className={`${SIGNAL_BADGE[l.signal] ?? 'bg-muted'} text-xs`}>
                        {l.signal.replace('_', ' ')}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Sector Analysis */}
      {data.sector_analysis.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Sector Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {data.sector_analysis.map((sector) => {
                const groupColor =
                  sector.group.toLowerCase().includes('bullish')
                    ? 'border-green-500'
                    : sector.group.toLowerCase().includes('bearish')
                      ? 'border-red-500'
                      : 'border-yellow-500'
                return (
                  <div key={sector.group} className={`p-3 rounded border-l-4 ${groupColor} bg-muted/30`}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium">{sector.group}</span>
                      <Badge variant="outline" className="text-xs">{sector.count}</Badge>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {sector.symbols.map((sym) => (
                        <span
                          key={sym}
                          className="text-xs px-1.5 py-0.5 rounded bg-muted text-foreground"
                        >
                          {sym}
                        </span>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* News Sentiment */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Newspaper className="h-4 w-4" />
            News Sentiment
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4 mb-3">
            <Badge className={STATUS_STYLE[data.news_sentiment.label?.toLowerCase()] ?? 'bg-muted'}>
              {data.news_sentiment.label}
            </Badge>
            <span className="text-sm font-mono">
              Score: {data.news_sentiment.avg_sentiment >= 0 ? '+' : ''}
              {data.news_sentiment.avg_sentiment.toFixed(3)}
            </span>
            <span className="text-xs text-muted-foreground">
              {data.news_sentiment.total_articles} articles
            </span>
          </div>
          {Object.keys(data.news_sentiment.top_sources).length > 0 && (
            <div>
              <div className="text-xs text-muted-foreground mb-1">Top Sources</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(data.news_sentiment.top_sources).map(([source, count]) => (
                  <span key={source} className="text-xs px-2 py-1 rounded border">
                    {source}: {count}
                  </span>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Key Levels Table */}
      {data.key_levels.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Target className="h-4 w-4" />
              Key Levels
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="text-left py-2 pr-4 font-medium">Symbol</th>
                    <th className="text-right py-2 px-2 font-medium">Pivot</th>
                    <th className="text-right py-2 px-2 font-medium text-green-600">R1</th>
                    <th className="text-right py-2 px-2 font-medium text-red-600">S1</th>
                    <th className="text-right py-2 px-2 font-medium text-green-600">R2</th>
                    <th className="text-right py-2 px-2 font-medium text-red-600">S2</th>
                  </tr>
                </thead>
                <tbody>
                  {data.key_levels.map((level) => (
                    <tr key={level.symbol} className="border-b last:border-0 hover:bg-muted/50">
                      <td className="py-1.5 pr-4 font-medium">{level.symbol}</td>
                      <td className="py-1.5 px-2 text-right font-mono">{fmt(level.pivot)}</td>
                      <td className="py-1.5 px-2 text-right font-mono text-green-600">{fmt(level.r1)}</td>
                      <td className="py-1.5 px-2 text-right font-mono text-red-600">{fmt(level.s1)}</td>
                      <td className="py-1.5 px-2 text-right font-mono text-green-600">{fmt(level.r2)}</td>
                      <td className="py-1.5 px-2 text-right font-mono text-red-600">{fmt(level.s2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
