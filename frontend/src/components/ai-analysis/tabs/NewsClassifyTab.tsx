import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, Newspaper, TrendingUp, TrendingDown, Minus, Sparkles } from 'lucide-react'
import { useNewsClassify } from '@/hooks/useStrategyAnalysis'
import type { HeadlineClassification } from '@/types/strategy-analysis'

const DEFAULT_HEADLINES = [
  'RBI cuts repo rate, markets rally',
  'IT sector faces US slowdown headwinds',
  'Nifty holds support at 22000',
  'FII buying accelerates in banking stocks',
  'Adani shares fall on regulatory probe',
]

const LABEL_CONFIG = {
  bullish: {
    color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
    icon: TrendingUp,
  },
  bearish: {
    color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
    icon: TrendingDown,
  },
  neutral: {
    color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
    icon: Minus,
  },
}

function ClassificationRow({
  headline,
  result,
}: {
  headline: string
  result: HeadlineClassification
}) {
  const cfg = LABEL_CONFIG[result.label] ?? LABEL_CONFIG.neutral
  const Icon = cfg.icon
  return (
    <div className="flex items-start gap-3 py-2 border-b last:border-0">
      <div
        className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold shrink-0 ${cfg.color}`}
      >
        <Icon className="h-3 w-3" />
        {result.label.toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate" title={headline}>
          {headline}
        </p>
        <p className="text-xs text-muted-foreground">
          {(result.confidence * 100).toFixed(0)}% confidence
          {result.model === 'student' && (
            <span className="ml-1 text-purple-500">· student model</span>
          )}
          {result.model === 'vader_fallback' && (
            <span className="ml-1 text-muted-foreground">· VADER</span>
          )}
        </p>
      </div>
      {result.probs && (
        <div className="flex gap-1 shrink-0">
          <span className="text-xs text-green-600">
            {(result.probs.bullish * 100).toFixed(0)}%
          </span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs text-red-600">
            {(result.probs.bearish * 100).toFixed(0)}%
          </span>
        </div>
      )}
    </div>
  )
}

export function NewsClassifyTab() {
  const [input, setInput] = useState(DEFAULT_HEADLINES.join('\n'))
  const [headlines, setHeadlines] = useState<string[]>([])
  const [run, setRun] = useState(false)
  const { data, isLoading } = useNewsClassify(headlines, run)

  const handleClassify = () => {
    const hl = input
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 50)
    setHeadlines(hl)
    setRun(true)
  }

  const bullCount = data?.results.filter((r) => r.label === 'bullish').length ?? 0
  const bearCount = data?.results.filter((r) => r.label === 'bearish').length ?? 0
  const neutCount = data?.results.filter((r) => r.label === 'neutral').length ?? 0

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Newspaper className="h-5 w-5 text-blue-500" />
        <h3 className="font-semibold text-lg">News Classifier</h3>
        <Badge variant="outline" className="text-xs">
          DistilBERT Distilled
        </Badge>
        <Badge variant="outline" className="text-xs text-purple-600">
          <Sparkles className="h-3 w-3 mr-1" />
          AI
        </Badge>
      </div>

      <Card>
        <CardContent className="pt-4 space-y-2">
          <label className="text-xs text-muted-foreground">
            Headlines (one per line, max 50)
          </label>
          <textarea
            className="w-full border rounded px-3 py-2 text-sm bg-background resize-y min-h-28 font-mono"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Enter financial headlines, one per line..."
          />
          <Button onClick={handleClassify} disabled={isLoading} className="w-full">
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
                Classifying...
              </>
            ) : (
              'Classify Headlines'
            )}
          </Button>
        </CardContent>
      </Card>

      {data && (
        <>
          <div className="flex gap-3 flex-wrap">
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-green-50 dark:bg-green-900/20 rounded-lg">
              <TrendingUp className="h-4 w-4 text-green-600" />
              <span className="text-sm font-semibold text-green-700 dark:text-green-400">
                {bullCount} Bullish
              </span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 dark:bg-red-900/20 rounded-lg">
              <TrendingDown className="h-4 w-4 text-red-600" />
              <span className="text-sm font-semibold text-red-700 dark:text-red-400">
                {bearCount} Bearish
              </span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
              <Minus className="h-4 w-4 text-yellow-600" />
              <span className="text-sm font-semibold text-yellow-700 dark:text-yellow-400">
                {neutCount} Neutral
              </span>
            </div>
          </div>

          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm">Classification Results</CardTitle>
            </CardHeader>
            <CardContent>
              {data.results.map((r, i) => (
                <ClassificationRow key={i} headline={headlines[i] ?? ''} result={r} />
              ))}
            </CardContent>
          </Card>

          <p className="text-xs text-muted-foreground">
            Model:{' '}
            {data.results[0]?.model === 'student'
              ? 'DistilBERT student (fine-tuned)'
              : 'VADER fallback — train student model for higher accuracy'}
          </p>
        </>
      )}
    </div>
  )
}
