import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Brain,
  Cloud,
  Loader2,
  Monitor,
  Search,
  ShieldAlert,
  ShieldCheck,
  Target,
  TestTube2,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
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
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { aaumApi } from '@/api/aaumAdvisor'
import type {
  AgentOutput,
  LayerSignal,
  TradeAction,
} from '@/types/aaum'
import { showToast } from '@/utils/toast'

// --- Helpers ---

const ANALYSIS_PHASES = [
  'Fetching market data...',
  'Running technical layers...',
  'Scanning options flow...',
  'Analyzing sentiment...',
  'Agent debate in progress...',
  'Risk assessment...',
  'Generating verdict...',
]

function actionColor(action: TradeAction) {
  switch (action) {
    case 'BUY':
      return 'bg-emerald-600 text-white'
    case 'SELL':
      return 'bg-red-600 text-white'
    case 'HOLD':
      return 'bg-amber-500 text-black'
    case 'NO_ACTION':
      return 'bg-zinc-800 text-zinc-300'
  }
}

function actionBorder(action: TradeAction) {
  switch (action) {
    case 'BUY':
      return 'border-emerald-600'
    case 'SELL':
      return 'border-red-600'
    case 'HOLD':
      return 'border-amber-500'
    case 'NO_ACTION':
      return 'border-zinc-600'
  }
}

function signalIcon(signal: LayerSignal) {
  switch (signal) {
    case 'bullish':
      return <TrendingUp className="h-4 w-4 text-emerald-500" />
    case 'bearish':
      return <TrendingDown className="h-4 w-4 text-red-500" />
    case 'neutral':
      return <Target className="h-4 w-4 text-zinc-400" />
  }
}

function signalColor(signal: LayerSignal) {
  switch (signal) {
    case 'bullish':
      return 'text-emerald-500'
    case 'bearish':
      return 'text-red-500'
    case 'neutral':
      return 'text-zinc-400'
  }
}

function formatNum(n: number | null | undefined, decimals = 2): string {
  if (n == null) return '-'
  return n.toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function formatPnl(n: number): string {
  const prefix = n >= 0 ? '+' : ''
  return `${prefix}${formatNum(n)}`
}

// --- Main Component ---

export default function AAUMAdvisor() {
  const [symbol, setSymbol] = useState('')
  const [progress, setProgress] = useState(0)
  const [phaseIndex, setPhaseIndex] = useState(0)
  const [showDebate, setShowDebate] = useState(true)
  const [showEquity, setShowEquity] = useState(true)
  const [showOptions, setShowOptions] = useState(true)
  const [showConfluence, setShowConfluence] = useState(true)
  const [showPortfolio, setShowPortfolio] = useState(true)
  const abortRef = useRef<AbortController | null>(null)
  const startTimeRef = useRef(0)

  // Health check — polls every 30s
  const healthQuery = useQuery({
    queryKey: ['aaum-health'],
    queryFn: aaumApi.health,
    refetchInterval: 30_000,
    retry: 1,
  })

  const isOnline = healthQuery.data?.status === 'healthy'

  // Derive which backend is active: colab / local / mock
  const backendLabel: 'colab' | 'local' | 'mock' | 'offline' = (() => {
    if (!healthQuery.data || healthQuery.data.status === 'offline') return 'offline'
    if (healthQuery.data.is_colab && healthQuery.data.colab?.reachable) return 'colab'
    if (healthQuery.data.local?.reachable) return 'local'
    return 'mock'
  })()

  // Analysis mutation
  const analyzeMutation = useMutation({
    mutationFn: (sym: string) => {
      abortRef.current?.abort()
      abortRef.current = new AbortController()
      return aaumApi.analyze(sym, abortRef.current.signal)
    },
    onSuccess: () => {
      setProgress(100)
      showToast.success('Analysis complete')
    },
    onError: (err) => {
      if (err.name !== 'CanceledError' && err.name !== 'AbortError') {
        showToast.error(err.message || 'Analysis failed')
      }
    },
    onSettled: () => {
      abortRef.current = null
    },
  })

  // Execute mutation
  const executeMutation = useMutation({
    mutationFn: (params: { symbol: string; paper: boolean; analysis_id: string }) =>
      aaumApi.execute(params.symbol, params.paper, params.analysis_id),
    onSuccess: (data) => {
      if (data.status === 'success') {
        showToast.success(data.message || 'Order placed')
      } else {
        showToast.error(data.message || 'Execution failed')
      }
    },
    onError: (err) => showToast.error(err.message || 'Execution failed'),
  })

  // Abort on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  // Asymptotic progress — never stalls, always moves
  useEffect(() => {
    if (!analyzeMutation.isPending) {
      if (!analyzeMutation.isSuccess) setProgress(0)
      return
    }
    startTimeRef.current = Date.now()
    setProgress(0)
    setPhaseIndex(0)

    const id = setInterval(() => {
      const elapsed = (Date.now() - startTimeRef.current) / 1000
      // Asymptotic: approaches 95% but never reaches it
      const target = 95 * (1 - Math.exp(-elapsed / 30))
      setProgress(target)
      // Advance phase labels
      const phase = Math.min(
        Math.floor((elapsed / 60) * ANALYSIS_PHASES.length),
        ANALYSIS_PHASES.length - 1,
      )
      setPhaseIndex(phase)
    }, 250)

    return () => clearInterval(id)
  }, [analyzeMutation.isPending, analyzeMutation.isSuccess])

  const handleAnalyze = () => {
    const trimmed = symbol.trim().toUpperCase()
    if (!trimmed) {
      showToast.warning('Enter a symbol')
      return
    }
    analyzeMutation.mutate(trimmed)
  }

  const result = analyzeMutation.data
  const isVeto = result?.action === 'NO_ACTION' || result?.risk_decision === 'REJECT'
  const bullCount = result?.layers.filter((l) => l.signal === 'bullish').length ?? 0

  return (
    <div className="flex min-h-screen flex-col">
      {/* --- Mini Toolbar --- */}
      <div className="flex items-center justify-between h-12 px-4 border-b bg-background/95 backdrop-blur">
        <Link
          to="/dashboard"
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Dashboard
        </Link>
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-primary" />
          <span className="font-semibold">AAUM Intelligence</span>
        </div>
        <Badge variant={isOnline ? 'default' : 'destructive'} className="text-xs">
          {healthQuery.isLoading ? 'Checking...' : isOnline ? 'Online' : 'Offline'}
        </Badge>
      </div>

      {/* --- Content --- */}
      <div className="flex-1 px-4 py-6 max-w-7xl mx-auto w-full space-y-4">
        {/* Panel 1: Search Bar */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Enter symbol (e.g., RELIANCE, NIFTY, SBIN)"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                  className="pl-10"
                  disabled={analyzeMutation.isPending}
                />
              </div>
              {/* Backend status badge */}
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge
                      variant={backendLabel === 'offline' ? 'destructive' : 'secondary'}
                      className={cn(
                        'cursor-default text-xs gap-1 shrink-0',
                        backendLabel === 'colab' && 'bg-violet-600/20 text-violet-400 border-violet-600/30',
                        backendLabel === 'local' && 'bg-emerald-600/20 text-emerald-400 border-emerald-600/30',
                        backendLabel === 'mock' && 'bg-amber-600/20 text-amber-400 border-amber-600/30',
                      )}
                    >
                      {backendLabel === 'colab' && <Cloud className="h-3 w-3" />}
                      {backendLabel === 'local' && <Monitor className="h-3 w-3" />}
                      {backendLabel === 'mock' && <TestTube2 className="h-3 w-3" />}
                      {backendLabel === 'offline' && <ShieldAlert className="h-3 w-3" />}
                      {backendLabel.charAt(0).toUpperCase() + backendLabel.slice(1)}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>
                      {backendLabel === 'colab' && 'Connected to AAUM via Colab tunnel'}
                      {backendLabel === 'local' && 'Connected to AAUM on localhost:8080'}
                      {backendLabel === 'mock' && 'No AAUM backend — using mock data'}
                      {backendLabel === 'offline' && 'AAUM backend unreachable'}
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>

              <Button
                onClick={handleAnalyze}
                disabled={analyzeMutation.isPending || !symbol.trim()}
                className="min-w-[120px]"
              >
                {analyzeMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Analyzing
                  </>
                ) : (
                  <>
                    <Zap className="mr-2 h-4 w-4" />
                    Analyze
                  </>
                )}
              </Button>
            </div>

            {/* Progress bar during analysis */}
            {analyzeMutation.isPending && (
              <div className="mt-4 space-y-2">
                <Progress value={progress} className="h-2" />
                <p className="text-sm text-muted-foreground text-center">
                  {ANALYSIS_PHASES[phaseIndex]}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Loading skeleton */}
        {analyzeMutation.isPending && (
          <div className="space-y-4">
            <Skeleton className="h-24 w-full" />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Skeleton className="h-48" />
              <Skeleton className="h-48" />
            </div>
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {/* Error state */}
        {analyzeMutation.isError && !analyzeMutation.isPending && (
          <Card className="border-destructive">
            <CardContent className="pt-6 text-center">
              <ShieldAlert className="h-8 w-8 mx-auto text-destructive mb-2" />
              <p className="font-semibold text-destructive">Analysis Failed</p>
              <p className="text-sm text-muted-foreground mt-1">
                {analyzeMutation.error?.message || 'Unknown error'}
              </p>
              <Button variant="outline" className="mt-4" onClick={handleAnalyze}>
                Retry
              </Button>
            </CardContent>
          </Card>
        )}

        {/* --- Results --- */}
        {result && !analyzeMutation.isPending && (
          <div className="space-y-4 animate-in fade-in-0 duration-500">
            {/* Panel 2: Verdict Banner — STICKY */}
            <Card
              className={cn(
                'sticky top-12 z-40 border-2',
                actionBorder(result.action),
              )}
            >
              <CardContent className="py-4">
                <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <span
                      className={cn(
                        'px-4 py-2 rounded-md text-3xl md:text-4xl font-black font-mono tracking-tight',
                        actionColor(result.action),
                      )}
                    >
                      {result.action}
                    </span>
                    <div className="text-center sm:text-left">
                      <p className="text-xl font-bold">{result.symbol}</p>
                      <p className="text-sm text-muted-foreground">
                        {new Date(result.timestamp).toLocaleString('en-IN')}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-6">
                    {/* Confidence */}
                    <div className="text-center">
                      <p className="text-2xl font-bold">{Math.round(result.confidence)}%</p>
                      <p className="text-xs text-muted-foreground">Confidence</p>
                    </div>

                    {/* Confluence */}
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger>
                          <div className="text-center">
                            <p className="text-2xl font-bold">
                              {bullCount}/{result.total_layers}
                            </p>
                            <p className="text-xs text-muted-foreground">Confluence</p>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>{bullCount} of {result.total_layers} layers are bullish</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>

                    {/* Regime */}
                    <Badge variant="secondary" className="text-sm capitalize">
                      {result.regime}
                    </Badge>

                    {/* Risk */}
                    {result.risk_decision === 'APPROVE' ? (
                      <Badge variant="default" className="gap-1">
                        <ShieldCheck className="h-3 w-3" /> Approved
                      </Badge>
                    ) : (
                      <Badge variant="destructive" className="gap-1">
                        <ShieldAlert className="h-3 w-3" /> {result.risk_decision}
                      </Badge>
                    )}
                  </div>
                </div>

                {/* Confidence progress bar */}
                <Progress
                  value={result.confidence}
                  className={cn('mt-3 h-2', result.confidence < 50 && '[&>div]:bg-amber-500')}
                />
              </CardContent>
            </Card>

            {/* Veto Warning Banner — shown but panels remain visible */}
            {isVeto && (
              <Card className="border-red-600/50 bg-red-950/20">
                <CardContent className="py-4 flex items-center gap-3">
                  <ShieldAlert className="h-6 w-6 text-red-500 shrink-0" />
                  <div>
                    <p className="font-semibold text-red-400">Trade Vetoed by Risk Manager</p>
                    <p className="text-sm text-muted-foreground">
                      {result.veto_reason || 'Insufficient confluence or conflicting signals. Review all panels below.'}
                    </p>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Panel Visibility Toggles */}
            <div className="flex flex-wrap gap-2">
              <Button
                variant={showEquity ? 'default' : 'outline'}
                size="sm"
                onClick={() => setShowEquity(!showEquity)}
              >
                Equity Signal
              </Button>
              <Button
                variant={showOptions ? 'default' : 'outline'}
                size="sm"
                onClick={() => setShowOptions(!showOptions)}
              >
                Options Strategy
              </Button>
              <Button
                variant={showConfluence ? 'default' : 'outline'}
                size="sm"
                onClick={() => setShowConfluence(!showConfluence)}
              >
                Confluence Map
              </Button>
              <Button
                variant={showDebate ? 'default' : 'outline'}
                size="sm"
                onClick={() => setShowDebate(!showDebate)}
              >
                Agent Debate
              </Button>
              <Button
                variant={showPortfolio ? 'default' : 'outline'}
                size="sm"
                onClick={() => setShowPortfolio(!showPortfolio)}
              >
                Portfolio
              </Button>
            </div>

            {/* Panels 3 + 4: Equity Signal + Options Strategy */}
            {(showEquity || showOptions) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Panel 3: Equity Signal Card */}
                {showEquity && <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <TrendingUp className="h-4 w-4" />
                      Equity Signal
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableBody>
                        <TableRow>
                          <TableCell className="font-medium">Entry</TableCell>
                          <TableCell className="text-right">{formatNum(result.equity_signal.entry_price)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium text-red-500">Stop Loss</TableCell>
                          <TableCell className="text-right text-red-500">{formatNum(result.equity_signal.stop_loss)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium text-emerald-500">T1</TableCell>
                          <TableCell className="text-right text-emerald-500">{formatNum(result.equity_signal.target_1)}</TableCell>
                        </TableRow>
                        {result.equity_signal.target_2 != null && (
                          <TableRow>
                            <TableCell className="font-medium text-emerald-500">T2</TableCell>
                            <TableCell className="text-right text-emerald-500">{formatNum(result.equity_signal.target_2)}</TableCell>
                          </TableRow>
                        )}
                        {result.equity_signal.target_3 != null && (
                          <TableRow>
                            <TableCell className="font-medium text-emerald-500">T3</TableCell>
                            <TableCell className="text-right text-emerald-500">{formatNum(result.equity_signal.target_3)}</TableCell>
                          </TableRow>
                        )}
                        <TableRow>
                          <TableCell className="font-medium">R:R</TableCell>
                          <TableCell className="text-right">{formatNum(result.equity_signal.rr_ratio, 1)}x</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium">Qty</TableCell>
                          <TableCell className="text-right">
                            {result.equity_signal.quantity}
                            {result.equity_signal.lot_size != null && (
                              <span className="text-xs text-muted-foreground ml-1">
                                (lot: {result.equity_signal.lot_size})
                              </span>
                            )}
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="font-medium">Position Size</TableCell>
                          <TableCell className="text-right">{formatNum(result.equity_signal.position_size_pct, 1)}%</TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>}

                {/* Panel 4: Options Strategy Card */}
                {showOptions && <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Zap className="h-4 w-4" />
                      {result.options_strategy?.strategy_name || 'Options Strategy'}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {result.options_strategy ? (
                      <>
                        {/* Legs Table */}
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Action</TableHead>
                              <TableHead>Strike</TableHead>
                              <TableHead>Type</TableHead>
                              <TableHead className="text-right">Premium</TableHead>
                              <TableHead className="text-right">Qty</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {result.options_strategy.legs.map((leg, i) => (
                              <TableRow key={i}>
                                <TableCell>
                                  <Badge variant={leg.action === 'BUY' ? 'default' : 'destructive'} className="text-xs">
                                    {leg.action}
                                  </Badge>
                                </TableCell>
                                <TableCell>{formatNum(leg.strike, 0)}</TableCell>
                                <TableCell>{leg.option_type}</TableCell>
                                <TableCell className="text-right">{formatNum(leg.premium)}</TableCell>
                                <TableCell className="text-right">{leg.quantity}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>

                        {/* Greeks + Risk */}
                        <div className="grid grid-cols-4 gap-2 mt-4 text-center">
                          <div>
                            <p className="text-xs text-muted-foreground">Delta</p>
                            <p className="font-mono text-sm">{formatNum(result.options_strategy.greeks.delta, 3)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Gamma</p>
                            <p className="font-mono text-sm">{formatNum(result.options_strategy.greeks.gamma, 4)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Theta</p>
                            <p className="font-mono text-sm">{formatNum(result.options_strategy.greeks.theta, 2)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Vega</p>
                            <p className="font-mono text-sm">{formatNum(result.options_strategy.greeks.vega, 2)}</p>
                          </div>
                        </div>

                        <Separator className="my-3" />

                        <div className="grid grid-cols-3 gap-2 text-center text-sm">
                          <div>
                            <p className="text-xs text-muted-foreground">PoP</p>
                            <p className="font-semibold">{Math.round(result.options_strategy.pop)}%</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Max Profit</p>
                            <p className="font-semibold text-emerald-500">{formatNum(result.options_strategy.max_profit)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Max Loss</p>
                            <p className="font-semibold text-red-500">{formatNum(result.options_strategy.max_loss)}</p>
                          </div>
                        </div>
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground text-center py-4">
                        No options strategy generated for this symbol.
                      </p>
                    )}
                  </CardContent>
                </Card>}
              </div>
            )}

            {/* Panel 5: 12-Layer Confluence Map */}
            {showConfluence && <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">12-Layer Confluence Map</CardTitle>
                  <Badge variant="outline">
                    {bullCount}/{result.total_layers} Bullish
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                {/* Sticky summary while scrolling through layers */}
                <Accordion type="single" collapsible className="space-y-1">
                  {result.layers.map((layer) => (
                    <AccordionItem key={layer.layer_number} value={String(layer.layer_number)}>
                      <AccordionTrigger className="text-sm hover:no-underline py-2">
                        <div className="flex items-center gap-3 flex-1">
                          <span className="text-xs text-muted-foreground w-5">
                            {layer.layer_number}
                          </span>
                          {signalIcon(layer.signal)}
                          <span className="font-medium">{layer.layer_name}</span>
                          <Badge
                            variant="outline"
                            className={cn('ml-auto mr-2 text-xs', signalColor(layer.signal))}
                          >
                            {layer.signal} {Math.round(layer.confidence)}%
                          </Badge>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent className="text-sm text-muted-foreground max-h-48 overflow-y-auto pl-8">
                        {layer.reasoning}
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>}

            {/* Panel 6: Agent Debate */}
            {showDebate && result.agent_debate && (
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">Agent Debate</CardTitle>
                    <Badge variant="outline">
                      Conviction: {Math.round(result.agent_debate.conviction_pct)}%
                    </Badge>
                  </div>
                </CardHeader>
                  <CardContent>
                    {/* Desktop: 3 columns */}
                    <div className="hidden md:grid md:grid-cols-3 gap-4">
                      <AgentColumn
                        title="Bulls"
                        agents={result.agent_debate.bulls}
                        color="text-emerald-500"
                      />
                      <AgentColumn
                        title="Bears"
                        agents={result.agent_debate.bears}
                        color="text-red-500"
                      />
                      <AgentColumn
                        title="Neutral"
                        agents={result.agent_debate.neutral}
                        color="text-zinc-400"
                      />
                    </div>

                    {/* Mobile: Tabs */}
                    <div className="md:hidden">
                      <Tabs defaultValue="bulls">
                        <TabsList className="grid grid-cols-3 w-full">
                          <TabsTrigger value="bulls">
                            Bulls ({result.agent_debate.bulls.length})
                          </TabsTrigger>
                          <TabsTrigger value="bears">
                            Bears ({result.agent_debate.bears.length})
                          </TabsTrigger>
                          <TabsTrigger value="neutral">
                            Neutral ({result.agent_debate.neutral.length})
                          </TabsTrigger>
                        </TabsList>
                        <TabsContent value="bulls">
                          <AgentColumn
                            title="Bulls"
                            agents={result.agent_debate.bulls}
                            color="text-emerald-500"
                          />
                        </TabsContent>
                        <TabsContent value="bears">
                          <AgentColumn
                            title="Bears"
                            agents={result.agent_debate.bears}
                            color="text-red-500"
                          />
                        </TabsContent>
                        <TabsContent value="neutral">
                          <AgentColumn
                            title="Neutral"
                            agents={result.agent_debate.neutral}
                            color="text-zinc-400"
                          />
                        </TabsContent>
                      </Tabs>
                    </div>
                  </CardContent>
              </Card>
            )}

            {/* Panel 7: Portfolio */}
            {showPortfolio && <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Current Portfolio</CardTitle>
              </CardHeader>
              <CardContent>
                {/* Current positions */}
                {result.portfolio && result.portfolio.positions.length > 0 && (
                  <div className="mb-4">
                    <ScrollArea className="max-h-48">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Symbol</TableHead>
                            <TableHead>Exchange</TableHead>
                            <TableHead className="text-right">Qty</TableHead>
                            <TableHead className="text-right">Avg</TableHead>
                            <TableHead className="text-right">LTP</TableHead>
                            <TableHead className="text-right">P&L</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {result.portfolio.positions.map((pos, i) => (
                            <TableRow key={i}>
                              <TableCell className="font-medium">{pos.symbol}</TableCell>
                              <TableCell>{pos.exchange}</TableCell>
                              <TableCell className="text-right">{pos.quantity}</TableCell>
                              <TableCell className="text-right">{formatNum(pos.avg_price)}</TableCell>
                              <TableCell className="text-right">{formatNum(pos.ltp)}</TableCell>
                              <TableCell
                                className={cn(
                                  'text-right font-medium',
                                  pos.pnl >= 0 ? 'text-emerald-500' : 'text-red-500',
                                )}
                              >
                                {formatPnl(pos.pnl)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </ScrollArea>
                    {result.portfolio.total_pnl !== 0 && (
                      <p className={cn(
                        'text-sm font-semibold mt-2 text-right',
                        result.portfolio.total_pnl >= 0 ? 'text-emerald-500' : 'text-red-500',
                      )}>
                        Total P&L: {formatPnl(result.portfolio.total_pnl)}
                      </p>
                    )}
                    <Separator className="my-4" />
                  </div>
                )}

              </CardContent>
            </Card>}

            {/* Action Buttons (always visible when results exist) */}
            <Card>
              <CardContent className="pt-6">
                <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
                  {/* Execute Live — RED, requires confirmation */}
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        className="bg-red-600 hover:bg-red-700 text-white font-bold px-8"
                        disabled={executeMutation.isPending}
                      >
                        {executeMutation.isPending ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : null}
                        Execute Live
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Confirm Live Trade</AlertDialogTitle>
                        <AlertDialogDescription>
                          This will place a real order for{' '}
                          <span className="font-semibold">{result.symbol}</span> — {result.action}{' '}
                          {result.equity_signal.quantity} shares at{' '}
                          {formatNum(result.equity_signal.entry_price)}.
                          <br />
                          <span className="text-red-500 font-semibold">
                            Stop Loss: {formatNum(result.equity_signal.stop_loss)}
                          </span>
                          {isVeto && (
                            <>
                              <br />
                              <span className="text-red-500 font-bold">
                                WARNING: Risk Manager VETOED this trade!
                              </span>
                            </>
                          )}
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel autoFocus>Go Back</AlertDialogCancel>
                        <AlertDialogAction
                          className="bg-red-600 hover:bg-red-700"
                          onClick={() =>
                            executeMutation.mutate({
                              symbol: result.symbol,
                              paper: false,
                              analysis_id: result.analysis_id,
                            })
                          }
                        >
                          Confirm — Place Order
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>

                  <Separator orientation="vertical" className="h-8 hidden sm:block" />

                  {/* Paper Trade — outline green */}
                  <Button
                    variant="outline"
                    className="border-emerald-600 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950 px-6"
                    disabled={executeMutation.isPending}
                    onClick={() =>
                      executeMutation.mutate({
                        symbol: result.symbol,
                        paper: true,
                        analysis_id: result.analysis_id,
                      })
                    }
                  >
                    Paper Trade
                  </Button>

                  {/* Skip */}
                  <Button
                    variant="ghost"
                    className="text-zinc-500"
                    onClick={() => {
                      analyzeMutation.reset()
                      setSymbol('')
                    }}
                  >
                    Skip
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Empty state */}
        {!analyzeMutation.isPending && !result && !analyzeMutation.isError && (
          <div className="text-center py-16 text-muted-foreground">
            <Brain className="h-12 w-12 mx-auto mb-4 opacity-30" />
            <p className="text-lg font-medium">Enter a symbol to begin analysis</p>
            <p className="text-sm mt-1">
              AAUM runs 12 analytical layers across 9 AI agents to generate a comprehensive verdict.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

// --- Agent Column Sub-component ---

function AgentColumn({
  title,
  agents,
  color,
}: {
  title: string
  agents: AgentOutput[]
  color: string
}) {
  if (agents.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground py-4">
        No {title.toLowerCase()} agents
      </div>
    )
  }

  return (
    <ScrollArea className="max-h-[400px]">
      <div className="space-y-3">
        {agents.map((agent, i) => (
          <Card key={i} className="p-3">
            <div className="flex items-center justify-between mb-2">
              <span className={cn('font-medium text-sm', color)}>{agent.agent_name}</span>
              <Badge variant="outline" className="text-xs">
                {Math.round(agent.confidence)}%
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">{agent.reasoning}</p>
          </Card>
        ))}
      </div>
    </ScrollArea>
  )
}
