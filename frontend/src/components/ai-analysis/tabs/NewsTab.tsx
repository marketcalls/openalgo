import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useNewsSentiment } from '@/hooks/useStrategyAnalysis'
import { Loader2, ExternalLink, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import type { NewsArticle, SourceBreakdown } from '@/types/strategy-analysis'

interface Props {
  symbol: string
  exchange: string
}

const LABEL_COLORS: Record<string, string> = {
  Bullish: 'text-green-600',
  'Slightly Bullish': 'text-green-500',
  Neutral: 'text-yellow-600',
  'Slightly Bearish': 'text-orange-500',
  Bearish: 'text-red-600',
}

const LABEL_BG: Record<string, string> = {
  Bullish: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  'Slightly Bullish': 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300',
  Neutral: 'bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-300',
  'Slightly Bearish': 'bg-orange-50 text-orange-700 dark:bg-orange-900/20 dark:text-orange-300',
  Bearish: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
}

function SentimentIcon({ label }: { label: string }) {
  if (label.includes('Bullish')) return <TrendingUp className="h-4 w-4 text-green-500" />
  if (label.includes('Bearish')) return <TrendingDown className="h-4 w-4 text-red-500" />
  return <Minus className="h-4 w-4 text-yellow-500" />
}

function SentimentBar({ compound }: { compound: number }) {
  // compound: -1 to +1, map to 0-100% where 50% is center
  const pct = Math.min(Math.max((compound + 1) / 2 * 100, 0), 100)
  const isPositive = compound >= 0
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden relative">
        <div className="absolute inset-0 flex">
          <div className="w-1/2 flex justify-end">
            {!isPositive && (
              <div
                className="bg-red-500 h-full rounded-l"
                style={{ width: `${(1 - pct / 50) * 100}%` }}
              />
            )}
          </div>
          <div className="w-1/2">
            {isPositive && (
              <div
                className="bg-green-500 h-full rounded-r"
                style={{ width: `${(pct - 50) / 50 * 100}%` }}
              />
            )}
          </div>
        </div>
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border" />
      </div>
      <span className={`text-xs font-mono w-12 text-right ${compound >= 0 ? 'text-green-600' : 'text-red-600'}`}>
        {compound >= 0 ? '+' : ''}{compound.toFixed(2)}
      </span>
    </div>
  )
}

export function NewsTab({ symbol, exchange }: Props) {
  const { data, isLoading, error } = useNewsSentiment(symbol, exchange)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Fetching news for {symbol}...
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12 text-destructive">
        Failed to fetch news sentiment. Check if the server is running.
      </div>
    )
  }

  if (!data || data.total_articles === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        No news articles found for {symbol}. Try a different symbol.
      </div>
    )
  }

  const { overall_sentiment, source_breakdown, articles } = data

  return (
    <div className="space-y-4">
      {/* Overall Sentiment Summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>News Sentiment — {symbol}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${LABEL_BG[overall_sentiment.label] ?? 'bg-muted'}`}>
              {overall_sentiment.label}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="text-center">
              <div className={`text-2xl font-bold ${LABEL_COLORS[overall_sentiment.label] ?? ''}`}>
                {overall_sentiment.compound >= 0 ? '+' : ''}{overall_sentiment.compound.toFixed(2)}
              </div>
              <div className="text-xs text-muted-foreground">Overall Score</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">{overall_sentiment.bullish_count}</div>
              <div className="text-xs text-muted-foreground">Bullish</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">{overall_sentiment.bearish_count}</div>
              <div className="text-xs text-muted-foreground">Bearish</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-yellow-600">{overall_sentiment.neutral_count}</div>
              <div className="text-xs text-muted-foreground">Neutral</div>
            </div>
          </div>
          <div className="mt-3">
            <SentimentBar compound={overall_sentiment.compound} />
          </div>
        </CardContent>
      </Card>

      {/* Source Breakdown */}
      {source_breakdown.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Source Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {source_breakdown.map((src: SourceBreakdown) => (
                <div key={src.source} className="flex items-center justify-between p-2 rounded border">
                  <div>
                    <div className="text-sm font-medium">{src.source}</div>
                    <div className="text-xs text-muted-foreground">{src.count} articles</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-sm font-mono ${src.avg_sentiment >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {src.avg_sentiment >= 0 ? '+' : ''}{src.avg_sentiment.toFixed(3)}
                    </div>
                    <div className={`text-xs ${LABEL_COLORS[src.label] ?? ''}`}>{src.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Articles List */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            Headlines ({data.total_articles} articles)
          </CardTitle>
        </CardHeader>
        <CardContent className="max-h-[500px] overflow-y-auto">
          <div className="space-y-2">
            {articles.map((article: NewsArticle, i: number) => (
              <div
                key={i}
                className="flex items-start gap-3 p-2 rounded border hover:bg-muted/50 transition-colors"
              >
                <SentimentIcon label={article.label} />
                <div className="flex-1 min-w-0">
                  <a
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium hover:underline line-clamp-2 flex items-start gap-1"
                  >
                    {article.title}
                    <ExternalLink className="h-3 w-3 flex-shrink-0 mt-0.5 text-muted-foreground" />
                  </a>
                  <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                    <span>{article.source}</span>
                    {article.published && (
                      <>
                        <span>·</span>
                        <span>{article.published}</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex-shrink-0 text-right">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${LABEL_BG[article.label] ?? 'bg-muted'}`}>
                    {article.label}
                  </span>
                  <div className="text-xs font-mono mt-0.5">
                    <span className={article.sentiment.compound >= 0 ? 'text-green-600' : 'text-red-600'}>
                      {article.sentiment.compound >= 0 ? '+' : ''}{article.sentiment.compound.toFixed(2)}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
