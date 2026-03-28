/**
 * AAUM Intelligence — 12-layer AI trading analysis page.
 *
 * Layout: FullWidthLayout (48px toolbar + scrollable content)
 * State: TanStack Query (useMutation/useQuery) — no Zustand needed
 * Progress: Asymptotic curve 0→95% + phase labels (survives tab sleep)
 * Panels: 7 panels rendered after analysis completes
 */
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Pause,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { aaumApi } from '@/api/aaumAdvisor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type {
  AgentDebate,
  AnalysisResult,
  EquitySignal,
  LayerResult,
  OptionsStrategy,
  PortfolioStatus,
  TradeAction,
} from '@/types/aaum'

// ---------------------------------------------------------------------------
// Phase labels — time-based so user knows what's happening during 30-90s wait
// ---------------------------------------------------------------------------
const PHASE_LABELS = [
  { after: 0,     label: 'Fetching market data…' },
  { after: 2000,  label: 'Running safety checks…' },
  { after: 5000,  label: 'Computing alpha factors…' },
  { after: 8000,  label: 'Agents analyzing (1/9)…' },
  { after: 20000, label: 'Agents analyzing (5/9)…' },
  { after: 35000, label: 'Agent debate in progress…' },
  { after: 42000, label: 'Risk moderation…' },
  { after: 45000, label: 'Assembling final report…' },
  { after: 60000, label: 'Taking longer than expected…' },
] as const

// ---------------------------------------------------------------------------
// useAnalysisProgress — asymptotic curve, survives browser tab sleep
// ---------------------------------------------------------------------------
function useAnalysisProgress(isPending: boolean) {
  const [progress, setProgress] = useState(0)
  const [phaseLabel, setPhaseLabel] = useState('')
  const startTimeRef = useRef(0)

  useEffect(() => {
    if (!isPending) {
      if (progress > 0) {
        setProgress(100)
        setPhaseLabel('Analysis complete')
        const reset = setTimeout(() => {
          setProgress(0)
          setPhaseLabel('')
        }, 1500)
        return () => clearTimeout(reset)
      }
      return
    }

    startTimeRef.current = Date.now()
    setProgress(0)

    // Asymptotic: 95 * (1 - e^(-t/30s)) — approaches 95% but never stalls
    const tick = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current
      const pct = 95 * (1 - Math.exp(-elapsed / 30_000))
      setProgress(Math.round(pct))

      for (let i = PHASE_LABELS.length - 1; i >= 0; i--) {
        if (elapsed >= PHASE_LABELS[i].after) {
          setPhaseLabel(PHASE_LABELS[i].label)
          break
        }
      }
    }, 250) // 4 FPS

    return () => clearInterval(tick)
  }, [isPending])

  return { progress, phaseLabel }
}

// ---------------------------------------------------------------------------
// VerdictBanner — sticky, color-coded, accessible (color + word + icon)
// ---------------------------------------------------------------------------
function VerdictBanner({ result }: { result: AnalysisResult }) {
  const configs: Record<TradeAction, { bg: string; textColor: string; icon: React.ReactNode }> = {
    BUY:       { bg: 'bg-emerald-600', textColor: 'text-white',      icon: <TrendingUp className="h-8 w-8" /> },
    SELL:      { bg: 'bg-red-600',     textColor: 'text-white',      icon: <TrendingDown className="h-8 w-8" /> },
    HOLD:      { bg: 'bg-amber-500',   textColor: 'text-black',      icon: <Pause className="h-8 w-8" /> },
    NO_ACTION: { bg: 'bg-zinc-800',    textColor: 'text-zinc-300',   icon: <ShieldAlert className="h-8 w-8" /> },
  }
  const cfg = configs[result.action] ?? configs.NO_ACTION
  const bullishLayers = result.layers.filter((l) => l.signal === 'bullish').length

  return (
    <div className={`sticky top-0 z-50 ${cfg.bg} ${cfg.textColor} p-6 rounded-lg mb-4`}>
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          {cfg.icon}
          <div>
            <div className="text-4xl md:text-5xl font-black tracking-tight font-mono">
              {result.action}
            </div>
            {result.veto_reason && (
              <div className="text-sm opacity-80 mt-1">{result.veto_reason}</div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-6 flex-wrap">
          <div>
            <div className="text-xs opacity-70 uppercase tracking-wide mb-1">Confidence</div>
            <div className="flex items-center gap-2">
              <Progress value={result.confidence} className="w-32 h-2" />
              <span className={`font-semibold ${result.confidence < 50 ? 'text-amber-300' : ''}`}>
                {result.confidence}%
              </span>
            </div>
          </div>

          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <div className="text-xs opacity-70 uppercase tracking-wide mb-1">Confluence</div>
                  <Badge variant="outline" className="font-mono">
                    {bullishLayers}/{result.layers.length} layers
                  </Badge>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                {bullishLayers} of {result.layers.length} layers are bullish.
                Confluence &gt;80% = HIGH conviction.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <div>
            <div className="text-xs opacity-70 uppercase tracking-wide mb-1">Regime</div>
            <Badge variant="secondary">{result.regime}</Badge>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// EquitySignalCard (Panel 3)
// ---------------------------------------------------------------------------
function EquitySignalCard({ signal }: { signal: EquitySignal }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm font-medium">Equity Signal</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="grid grid-cols-2 gap-2">
          <div><span className="text-muted-foreground">Entry</span><div className="font-mono font-semibold">₹{signal.entry_price.toFixed(2)}</div></div>
          <div><span className="text-muted-foreground">Stop Loss</span><div className="font-mono font-semibold text-red-500">₹{signal.stop_loss.toFixed(2)}</div></div>
          <div><span className="text-muted-foreground">Target 1</span><div className="font-mono font-semibold text-emerald-500">₹{signal.target_1.toFixed(2)}</div></div>
          {signal.target_2 != null && (
            <div><span className="text-muted-foreground">Target 2</span><div className="font-mono font-semibold text-emerald-500">₹{signal.target_2.toFixed(2)}</div></div>
          )}
          <div><span className="text-muted-foreground">R:R</span><div className="font-mono font-semibold">{signal.rr_ratio.toFixed(2)}</div></div>
          <div><span className="text-muted-foreground">ATR(14)</span><div className="font-mono">{signal.atr_14.toFixed(2)}</div></div>
          <div><span className="text-muted-foreground">Position Size</span><div className="font-mono">{signal.position_size_pct}%</div></div>
          <div><span className="text-muted-foreground">Qty</span><div className="font-mono">{signal.quantity}{signal.lot_size ? ` (lot: ${signal.lot_size})` : ''}</div></div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// OptionsStrategyCard (Panel 4)
// ---------------------------------------------------------------------------
function OptionsStrategyCard({ strategy }: { strategy: OptionsStrategy }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Options: {strategy.strategy_name}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm space-y-3">
        {strategy.legs.length > 0 ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="text-left">Action</th>
                <th className="text-left">Strike</th>
                <th className="text-left">Type</th>
                <th className="text-right">Premium</th>
                <th className="text-right">Qty</th>
              </tr>
            </thead>
            <tbody>
              {strategy.legs.map((leg, i) => (
                <tr key={i} className="border-t">
                  <td className={leg.action === 'BUY' ? 'text-emerald-500' : 'text-red-500'}>{leg.action}</td>
                  <td className="font-mono">{leg.strike}</td>
                  <td>{leg.option_type}</td>
                  <td className="text-right font-mono">₹{leg.premium.toFixed(2)}</td>
                  <td className="text-right">{leg.quantity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-muted-foreground text-xs italic">
            Options strategy selector wires in Phase 2 (PCR/max_pain/IV_rank)
          </div>
        )}
        <div className="grid grid-cols-2 gap-2 pt-2 text-xs">
          <div><span className="text-muted-foreground">Delta</span><div className="font-mono">{strategy.greeks.delta.toFixed(3)}</div></div>
          <div><span className="text-muted-foreground">Theta</span><div className="font-mono">{strategy.greeks.theta.toFixed(3)}</div></div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// ConfluenceMap — 12-layer accordion (Panel 5)
// ---------------------------------------------------------------------------
function ConfluenceMap({ layers }: { layers: LayerResult[] }) {
  const signalIcon = (s: string) =>
    s === 'bullish' ? '🟢' : s === 'bearish' ? '🔴' : '🟡'

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm font-medium">12-Layer Confluence Map</CardTitle></CardHeader>
      <CardContent>
        <Accordion type="multiple" className="space-y-1">
          {layers.map((layer) => (
            <AccordionItem
              key={layer.layer_number}
              value={String(layer.layer_number)}
              className="border rounded px-3"
            >
              <AccordionTrigger className="text-sm py-2">
                <div className="flex items-center gap-3 w-full">
                  <span className="text-xs text-muted-foreground w-4">L{layer.layer_number}</span>
                  <span>{signalIcon(layer.signal)}</span>
                  <span className="flex-1 text-left">{layer.layer_name}</span>
                  <span className="text-xs text-muted-foreground">{layer.confidence.toFixed(0)}%</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="text-xs text-muted-foreground pb-2">
                {layer.reasoning}
                {(layer.entry != null || layer.stop_loss != null || layer.target != null) && (
                  <div className="mt-1 font-mono">
                    {layer.entry != null && `Entry: ₹${layer.entry.toFixed(2)} `}
                    {layer.stop_loss != null && `SL: ₹${layer.stop_loss.toFixed(2)} `}
                    {layer.target != null && `T: ₹${layer.target.toFixed(2)}`}
                  </div>
                )}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// AgentDebatePanel (Panel 6)
// ---------------------------------------------------------------------------
function AgentDebatePanel({ debate }: { debate: AgentDebate }) {
  type AgentList = typeof debate.bulls
  const Section = ({
    title,
    agents,
    colorClass,
  }: {
    title: string
    agents: AgentList
    colorClass: string
  }) => (
    <div>
      <div className={`text-xs font-semibold uppercase tracking-wide mb-2 ${colorClass}`}>
        {title} ({agents.length})
      </div>
      {agents.length === 0 ? (
        <div className="text-xs text-muted-foreground italic">None</div>
      ) : (
        agents.map((a) => (
          <div key={a.agent_name} className="mb-2 p-2 bg-muted/40 rounded text-xs">
            <div className="font-semibold">{a.agent_name}</div>
            <div className="text-muted-foreground line-clamp-3">{a.reasoning}</div>
            <div className="text-xs mt-1 opacity-70">Confidence: {a.confidence}%</div>
          </div>
        ))
      )}
    </div>
  )

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Agent Debate (9 Agents)</CardTitle>
          <Badge variant="outline" className="font-mono">
            Conviction: {debate.conviction_pct.toFixed(0)}%
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Section title="Bullish" agents={debate.bulls} colorClass="text-emerald-500" />
          <Section title="Bearish" agents={debate.bears} colorClass="text-red-500" />
          <Section title="Neutral" agents={debate.neutral} colorClass="text-amber-500" />
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// PortfolioActions — positions table + execute buttons (Panel 7)
// ---------------------------------------------------------------------------
function PortfolioActions({
  portfolio,
  result,
  onExecute,
  isExecuting,
}: {
  portfolio: PortfolioStatus
  result: AnalysisResult
  onExecute: (paper: boolean) => void
  isExecuting: boolean
}) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm font-medium">Portfolio & Actions</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {portfolio.positions.length > 0 ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="text-left">Symbol</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Avg</th>
                <th className="text-right">LTP</th>
                <th className="text-right">P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr key={p.symbol} className="border-t">
                  <td>{p.symbol}</td>
                  <td className="text-right">{p.quantity}</td>
                  <td className="text-right font-mono">₹{p.avg_price.toFixed(2)}</td>
                  <td className="text-right font-mono">₹{p.ltp.toFixed(2)}</td>
                  <td className={`text-right font-mono ${p.pnl >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                    ₹{p.pnl.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-xs text-muted-foreground italic">No open positions</div>
        )}

        <div className="text-xs text-muted-foreground">
          Total P&amp;L:{' '}
          <span className={portfolio.total_pnl >= 0 ? 'text-emerald-500 font-semibold' : 'text-red-500 font-semibold'}>
            ₹{portfolio.total_pnl.toFixed(2)}
          </span>
        </div>

        {result.action !== 'NO_ACTION' && (
          <div className="flex gap-3 flex-wrap pt-2">
            <Button
              onClick={() => onExecute(false)}
              disabled={isExecuting}
              className="bg-red-600 hover:bg-red-700 text-white font-bold px-8 py-3 text-base"
            >
              {isExecuting ? 'Placing Order…' : '⚡ Execute Live'}
            </Button>
            <Button
              variant="outline"
              onClick={() => onExecute(true)}
              disabled={isExecuting}
              className="border-emerald-600 text-emerald-600 hover:bg-emerald-50 px-6 py-3"
            >
              Paper Trade
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// AAUMAdvisor — main page component
// ---------------------------------------------------------------------------
export default function AAUMAdvisor() {
  const [inputValue, setInputValue] = useState('')
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  // Cancel in-flight analysis on unmount
  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  // Health poll — every 30s, 5s timeout
  const healthQuery = useQuery({
    queryKey: ['aaum-health'],
    queryFn: aaumApi.health,
    refetchInterval: 30_000,
    retry: 1,
    staleTime: 25_000,
  })

  // Long-running analysis mutation
  const analyzeMutation = useMutation({
    mutationFn: (symbol: string) => {
      abortRef.current?.abort()
      abortRef.current = new AbortController()
      return aaumApi.analyze(symbol, abortRef.current.signal)
    },
    onSettled: () => { abortRef.current = null },
    onError: (error) => {
      // Don't surface error toast for intentional abort (re-analyze / nav away)
      if (error instanceof Error && error.name === 'CanceledError') return
      console.error('AAUM analysis failed:', error)
    },
  })

  const executeMutation = useMutation({
    mutationFn: (params: { paper: boolean }) => {
      const r = analyzeMutation.data!
      return aaumApi.execute(r.symbol, params.paper, r.analysis_id)
    },
  })

  const { progress, phaseLabel } = useAnalysisProgress(analyzeMutation.isPending)
  const result = analyzeMutation.data

  // Service is usable when 'healthy' OR 'degraded' (AAUM running, Ollama may be down)
  const serviceStatus = healthQuery.data?.status
  const isServiceUsable = serviceStatus === 'healthy' || serviceStatus === 'degraded'
  const isServiceOnline = serviceStatus === 'healthy'

  const handleAnalyze = () => {
    const symbol = inputValue.trim().toUpperCase()
    if (!symbol || analyzeMutation.isPending) return
    analyzeMutation.mutate(symbol)
  }

  const handleExecute = (paper: boolean) => {
    if (!paper) {
      setShowConfirmDialog(true)
    } else {
      executeMutation.mutate({ paper: true })
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Mini toolbar — same pattern as Playground, FlowEditor */}
      <div className="flex items-center justify-between h-12 px-4 border-b shrink-0">
        <Link
          to="/dashboard"
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Dashboard
        </Link>
        <span className="font-semibold">AAUM Intelligence</span>
        <div className="flex items-center gap-2">
          {healthQuery.isLoading ? (
            <Badge variant="outline">Checking…</Badge>
          ) : (
            <Badge variant={isServiceOnline ? 'default' : serviceStatus === 'degraded' ? 'secondary' : 'destructive'}>
              {serviceStatus === 'healthy' ? 'Online' : serviceStatus === 'degraded' ? 'Degraded' : 'Offline'}
            </Badge>
          )}
          {serviceStatus === 'degraded' && (
            <span className="text-xs text-muted-foreground hidden sm:block">
              Ollama: {healthQuery.data?.ollama_status}
            </span>
          )}
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 max-w-7xl mx-auto w-full">

        {/* Panel 1: Symbol search */}
        <Card>
          <CardContent className="pt-6 space-y-3">
            <form
              onSubmit={(e) => { e.preventDefault(); handleAnalyze() }}
              className="flex gap-2"
            >
              <Input
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value.toUpperCase())}
                placeholder="Enter symbol (e.g. RELIANCE, INFY, NIFTY)"
                className="font-mono"
                disabled={analyzeMutation.isPending}
              />
              <Button
                type="submit"
                disabled={!inputValue.trim() || analyzeMutation.isPending || !isServiceUsable}
              >
                {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze'}
              </Button>
            </form>

            {analyzeMutation.isPending && (
              <div className="space-y-1">
                <Progress value={progress} className="h-2" />
                <div className="text-xs text-muted-foreground">{phaseLabel}</div>
              </div>
            )}

            {analyzeMutation.isError && (
              <div className="text-sm text-red-500">
                {analyzeMutation.error instanceof Error
                  ? analyzeMutation.error.message
                  : 'Analysis failed. Is AAUM running?'}
              </div>
            )}

            {!isServiceUsable && !healthQuery.isLoading && (
              <div className="text-xs text-amber-500">
                AAUM sidecar is offline. Start it:{' '}
                <code className="font-mono">
                  cd C:/Users/sakth/Desktop/aaum &amp;&amp; uvicorn aaum.server:app --port 8080
                </code>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Skeleton placeholders while analyzing */}
        {analyzeMutation.isPending && (
          <div className="space-y-4">
            <Skeleton className="h-32 w-full" />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Skeleton className="h-48" />
              <Skeleton className="h-48" />
            </div>
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        )}

        {/* Panels 2-7: Shown after analysis completes */}
        {result && !analyzeMutation.isPending && (
          <>
            <VerdictBanner result={result} />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <EquitySignalCard signal={result.equity_signal} />
              <OptionsStrategyCard strategy={result.options_strategy} />
            </div>

            {result.layers.length > 0 && <ConfluenceMap layers={result.layers} />}

            <AgentDebatePanel debate={result.agent_debate} />

            <PortfolioActions
              portfolio={result.portfolio}
              result={result}
              onExecute={handleExecute}
              isExecuting={executeMutation.isPending}
            />
          </>
        )}
      </div>

      {/* Live execute confirmation dialog — 3-layer safety */}
      <AlertDialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Execute Live Trade?</AlertDialogTitle>
            <AlertDialogDescription>
              This will place a REAL order via your connected broker.
              {result && (
                <span className="block mt-2 font-semibold">
                  {result.action} {result.symbol} — Entry ₹{result.equity_signal.entry_price.toFixed(2)},
                  SL ₹{result.equity_signal.stop_loss.toFixed(2)},
                  T1 ₹{result.equity_signal.target_1.toFixed(2)}
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setShowConfirmDialog(false)
                executeMutation.mutate({ paper: false })
              }}
              className="bg-red-600 hover:bg-red-700"
            >
              Yes, Execute Live
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
