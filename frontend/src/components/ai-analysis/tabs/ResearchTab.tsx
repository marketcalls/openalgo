import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useResearch } from '@/hooks/useStrategyAnalysis'
import {
  Loader2, AlertCircle, CheckCircle2, XCircle, Search,
  AlertTriangle, TrendingUp, ShieldAlert, Lightbulb, BarChart3,
  Target,
} from 'lucide-react'

interface Props {
  symbol: string
  exchange: string
}

const VERDICT_STYLE: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  BULLISH: { bg: 'bg-green-50 dark:bg-green-900/20', border: 'border-green-500', text: 'text-green-700 dark:text-green-400', icon: 'text-green-500' },
  BEARISH: { bg: 'bg-red-50 dark:bg-red-900/20', border: 'border-red-500', text: 'text-red-700 dark:text-red-400', icon: 'text-red-500' },
  NEUTRAL: { bg: 'bg-yellow-50 dark:bg-yellow-900/20', border: 'border-yellow-500', text: 'text-yellow-700 dark:text-yellow-400', icon: 'text-yellow-500' },
}

const SIGNAL_COLORS: Record<string, string> = {
  STRONG_BUY: 'bg-green-600 text-white',
  BUY: 'bg-green-400 text-white',
  HOLD: 'bg-yellow-400 text-yellow-900',
  SELL: 'bg-orange-500 text-white',
  STRONG_SELL: 'bg-red-600 text-white',
  BULLISH: 'bg-green-500 text-white',
  BEARISH: 'bg-red-500 text-white',
  NEUTRAL: 'bg-yellow-400 text-yellow-900',
}

function StepIcon({ status }: { status: string }) {
  if (status === 'completed' || status === 'done' || status === 'success') {
    return <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
  }
  if (status === 'failed' || status === 'error') {
    return <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
  }
  if (status === 'running' || status === 'in_progress') {
    return <Loader2 className="h-4 w-4 text-blue-500 animate-spin flex-shrink-0" />
  }
  return <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30 flex-shrink-0" />
}

function fmt(n: number | null | undefined): string {
  return n != null
    ? n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : 'N/A'
}

export function ResearchTab({ symbol, exchange }: Props) {
  const defaultQ = `Should I invest in ${symbol}?`
  const [question, setQuestion] = useState(defaultQ)
  const [runEnabled, setRunEnabled] = useState(false)
  const [activeQuestion, setActiveQuestion] = useState('')

  const { data, isLoading, error } = useResearch(
    symbol,
    exchange,
    activeQuestion,
    runEnabled && !!activeQuestion,
  )

  function handleRun() {
    setActiveQuestion(question)
    setRunEnabled(true)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') handleRun()
  }

  const report = data?.report

  return (
    <div className="space-y-4">
      {/* Question Input */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Search className="h-4 w-4" />
            Research Agent -- {symbol}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Ask about ${symbol}...`}
              className="flex-1 px-3 py-2 text-sm rounded-md border bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <button
              onClick={handleRun}
              disabled={isLoading || !question.trim()}
              className="px-4 py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Researching...
                </>
              ) : (
                'Run Research'
              )}
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          Running deep research on {symbol}... This may take a minute.
        </div>
      )}

      {/* Error State */}
      {error && !isLoading && (
        <div className="flex items-center justify-center py-12 gap-2 text-destructive">
          <AlertCircle className="h-5 w-5" />
          Research failed: {(error as Error).message}
        </div>
      )}

      {/* Empty / Not-started State */}
      {!data && !isLoading && !error && (
        <div className="text-center py-12 text-muted-foreground">
          Enter a question and click "Run Research" to start deep analysis of {symbol}.
        </div>
      )}

      {/* Results */}
      {data && !isLoading && (
        <>
          {/* Research Steps */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">
                Research Steps ({data.steps_completed}/{data.steps.length} completed)
                {data.steps_failed > 0 && (
                  <span className="text-red-500 ml-2">({data.steps_failed} failed)</span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {data.steps.map((step) => (
                  <div key={step.step} className="flex items-center gap-3 py-1">
                    <StepIcon status={step.status} />
                    <span className="text-xs text-muted-foreground w-6">#{step.step}</span>
                    <span className="text-sm flex-1">{step.task}</span>
                    {step.error && (
                      <span className="text-xs text-red-500 truncate max-w-[200px]" title={step.error}>
                        {step.error}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Verdict Banner */}
          {report && (
            <>
              {(() => {
                const style = VERDICT_STYLE[report.verdict?.toUpperCase()] ?? VERDICT_STYLE.NEUTRAL
                return (
                  <Card className={`border-l-4 ${style.border} ${style.bg}`}>
                    <CardContent className="pt-4">
                      <div className="flex items-center justify-between flex-wrap gap-3">
                        <div className="flex items-center gap-3">
                          {report.verdict?.toUpperCase() === 'BULLISH' && <TrendingUp className={`h-6 w-6 ${style.icon}`} />}
                          {report.verdict?.toUpperCase() === 'BEARISH' && <AlertTriangle className={`h-6 w-6 ${style.icon}`} />}
                          {report.verdict?.toUpperCase() === 'NEUTRAL' && <BarChart3 className={`h-6 w-6 ${style.icon}`} />}
                          <div>
                            <div className={`text-lg font-bold ${style.text}`}>
                              {report.verdict}
                            </div>
                            <div className="text-sm text-muted-foreground">{report.verdict_detail}</div>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-2xl font-bold">{report.confidence.toFixed(1)}%</div>
                          <div className="text-xs text-muted-foreground">Confidence</div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )
              })()}

              {/* Answer */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Answer</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-relaxed">{report.answer}</p>
                </CardContent>
              </Card>

              {/* Reasoning */}
              {report.reasoning.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Lightbulb className="h-4 w-4 text-green-500" />
                      Reasoning
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {report.reasoning.map((r, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="mt-1.5 h-2 w-2 rounded-full bg-green-500 flex-shrink-0" />
                          {r}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {/* Risks & Opportunities */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Risks */}
                {report.risks.length > 0 && (
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <ShieldAlert className="h-4 w-4 text-red-500" />
                        Risks
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {report.risks.map((r, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm">
                            <AlertTriangle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
                            {r}
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                )}

                {/* Opportunities */}
                {report.opportunities.length > 0 && (
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <TrendingUp className="h-4 w-4 text-green-500" />
                        Opportunities
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {report.opportunities.map((o, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm">
                            <CheckCircle2 className="h-4 w-4 text-green-400 flex-shrink-0 mt-0.5" />
                            {o}
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                )}
              </div>

              {/* Signals Summary */}
              {report.signals_summary.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <BarChart3 className="h-4 w-4" />
                      Signals Summary
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {report.signals_summary.map((sig, i) => (
                        <div key={i} className="flex items-center gap-3">
                          <span className="text-sm font-medium w-32 truncate" title={sig.module}>
                            {sig.module}
                          </span>
                          <Badge className={`${SIGNAL_COLORS[sig.signal?.toUpperCase()] ?? 'bg-muted'} text-xs`}>
                            {sig.signal}
                          </Badge>
                          <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-blue-500 rounded-full transition-all"
                              style={{ width: `${Math.min(Math.max(sig.confidence, 0), 100)}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono w-12 text-right">
                            {sig.confidence.toFixed(1)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Trade Setup */}
              {report.trade_setup && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Target className="h-4 w-4" />
                      Trade Setup
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      {/* Entry */}
                      <div className="p-3 rounded border bg-muted/30">
                        <div className="text-xs text-muted-foreground mb-1">Entry</div>
                        {Object.entries(report.trade_setup.entry).map(([k, v]) => (
                          <div key={k} className="flex justify-between text-sm">
                            <span className="text-muted-foreground capitalize">{k}</span>
                            <span className="font-mono">{typeof v === 'number' ? fmt(v) : String(v)}</span>
                          </div>
                        ))}
                      </div>
                      {/* Stop Loss */}
                      <div className="p-3 rounded border border-red-200 bg-red-50/50 dark:bg-red-900/10 dark:border-red-900/30">
                        <div className="text-xs text-red-600 mb-1">Stop Loss</div>
                        {Object.entries(report.trade_setup.stop_loss).map(([k, v]) => (
                          <div key={k} className="flex justify-between text-sm">
                            <span className="text-muted-foreground capitalize">{k}</span>
                            <span className="font-mono text-red-600">
                              {typeof v === 'number' ? fmt(v) : String(v)}
                            </span>
                          </div>
                        ))}
                      </div>
                      {/* Targets */}
                      <div className="p-3 rounded border border-green-200 bg-green-50/50 dark:bg-green-900/10 dark:border-green-900/30">
                        <div className="text-xs text-green-600 mb-1">Targets</div>
                        {report.trade_setup.targets.map((t, i) => (
                          <div key={i} className="text-sm">
                            {Object.entries(t).map(([k, v]) => (
                              <div key={k} className="flex justify-between">
                                <span className="text-muted-foreground capitalize">{k}</span>
                                <span className="font-mono text-green-600">
                                  {typeof v === 'number' ? fmt(v) : String(v)}
                                </span>
                              </div>
                            ))}
                            {i < report.trade_setup!.targets.length - 1 && <hr className="my-1" />}
                          </div>
                        ))}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
