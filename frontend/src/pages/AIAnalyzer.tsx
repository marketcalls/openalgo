import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Loader2, Search, TrendingUp, BarChart3, History, Scan } from 'lucide-react'
import {
  SignalBadge, ConfidenceGauge, SubScoresChart, IndicatorTable, ScanResultsTable,
  AdvancedSignalsPanel, LivePriceHeader, MLConfidenceBar, LevelsPanel,
  TradeActionPanel, DecisionHistory, LLMCommentary,
} from '@/components/ai-analysis'
import { useAIAnalysis, useAIScan, useAIStatus } from '@/hooks/useAIAnalysis'
import { REGIME_CONFIG } from '@/types/ai-analysis'
import { showToast } from '@/utils/toast'

const NIFTY50 = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'SBIN',
  'BHARTIARTL', 'ITC', 'KOTAKBANK', 'LT', 'AXISBANK', 'BAJFINANCE',
  'ASIANPAINT', 'MARUTI', 'TITAN', 'SUNPHARMA', 'WIPRO', 'HCLTECH', 'ULTRACEMCO',
]

export default function AIAnalyzer() {
  const [symbol, setSymbol] = useState('RELIANCE')
  const [exchange, setExchange] = useState('NSE')
  const [interval, setInterval] = useState('1d')
  const [scanSymbols, setScanSymbols] = useState('')
  const [runScan, setRunScan] = useState(false)

  const { data: analysis, isLoading, error, refetch } = useAIAnalysis(symbol, exchange, interval, !!symbol)
  const { data: statusData } = useAIStatus()

  const symbolList = runScan
    ? (scanSymbols.trim() ? scanSymbols.split(',').map((s) => s.trim()) : NIFTY50)
    : []
  const { data: scanResults, isLoading: scanLoading } = useAIScan(symbolList, exchange, interval, runScan)

  const handleAnalyze = () => {
    if (!symbol.trim()) { showToast.error('Enter a symbol'); return }
    refetch()
  }

  return (
    <div className="container mx-auto p-4 space-y-4">
      {/* Header + Controls */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5" />
          <h1 className="text-xl font-bold">AI Trading Intelligence</h1>
          {statusData && (
            <span className="text-xs text-muted-foreground hidden md:inline">
              {statusData.engine} | {statusData.indicators} indicators
            </span>
          )}
        </div>
        <div className="flex gap-2 items-end flex-wrap">
          <Input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="RELIANCE" className="w-32" />
          <Select value={exchange} onValueChange={setExchange}>
            <SelectTrigger className="w-20"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="NSE">NSE</SelectItem>
              <SelectItem value="BSE">BSE</SelectItem>
            </SelectContent>
          </Select>
          <Select value={interval} onValueChange={setInterval}>
            <SelectTrigger className="w-20"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="1d">Daily</SelectItem>
              <SelectItem value="1h">1H</SelectItem>
              <SelectItem value="15m">15m</SelectItem>
              <SelectItem value="5m">5m</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={handleAnalyze} disabled={isLoading} size="sm">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {error && <p className="text-destructive text-sm">{String(error)}</p>}

      {/* Live Price */}
      {symbol && <LivePriceHeader symbol={symbol} exchange={exchange} />}

      <Tabs defaultValue="analysis" className="w-full">
        <TabsList>
          <TabsTrigger value="analysis"><BarChart3 className="h-4 w-4 mr-1" /> Analysis</TabsTrigger>
          <TabsTrigger value="scanner"><Scan className="h-4 w-4 mr-1" /> Scanner</TabsTrigger>
          <TabsTrigger value="history"><History className="h-4 w-4 mr-1" /> History</TabsTrigger>
        </TabsList>

        {/* === ANALYSIS TAB === */}
        <TabsContent value="analysis" className="space-y-4">
          {analysis && (
            <>
              {/* Row 1: Signal + Trade Action + ML Confidence */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {/* Signal Card */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Signal</CardTitle></CardHeader>
                  <CardContent className="flex flex-col items-center gap-3">
                    <SignalBadge signal={analysis.signal} size="lg" />
                    <ConfidenceGauge confidence={analysis.confidence} />
                    <p className="text-xs text-muted-foreground">
                      {REGIME_CONFIG[analysis.regime]?.label ?? analysis.regime} | {analysis.data_points} bars
                    </p>
                  </CardContent>
                </Card>

                {/* Trade Actions */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Trade</CardTitle></CardHeader>
                  <CardContent>
                    <TradeActionPanel
                      symbol={symbol} exchange={exchange}
                      signal={analysis.signal} confidence={analysis.confidence}
                    />
                    <div className="mt-3">
                      <MLConfidenceBar
                        buyConfidence={analysis.advanced?.ml_confidence?.buy ?? 0}
                        sellConfidence={analysis.advanced?.ml_confidence?.sell ?? 0}
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* Sub-Scores */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Signal Breakdown</CardTitle></CardHeader>
                  <CardContent>
                    <SubScoresChart scores={analysis.sub_scores} />
                  </CardContent>
                </Card>

                {/* CPR Levels */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Pivot Levels</CardTitle></CardHeader>
                  <CardContent>
                    <LevelsPanel cpr={analysis.advanced?.cpr ?? {}} />
                  </CardContent>
                </Card>
              </div>

              {/* Row 2: Advanced Signals + Indicators + LLM */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Pattern Alerts</CardTitle></CardHeader>
                  <CardContent>
                    {analysis.advanced ? (
                      <AdvancedSignalsPanel signals={analysis.advanced} />
                    ) : (
                      <p className="text-xs text-muted-foreground">No advanced data</p>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Indicators</CardTitle></CardHeader>
                  <CardContent className="max-h-64 overflow-auto">
                    <IndicatorTable indicators={analysis.indicators} />
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">AI Commentary</CardTitle></CardHeader>
                  <CardContent>
                    <LLMCommentary analysis={analysis} />
                  </CardContent>
                </Card>
              </div>
            </>
          )}

          {!analysis && !isLoading && (
            <div className="text-center py-12 text-muted-foreground">
              Enter a symbol and click Analyze to get AI trading intelligence
            </div>
          )}
        </TabsContent>

        {/* === SCANNER TAB === */}
        <TabsContent value="scanner" className="space-y-4">
          <Card>
            <CardContent className="pt-4 space-y-4">
              <div className="flex gap-2 items-end">
                <div className="flex-1">
                  <Input value={scanSymbols} onChange={(e) => setScanSymbols(e.target.value.toUpperCase())}
                    placeholder="RELIANCE, TCS, INFY... (empty = NIFTY 50)" />
                </div>
                <Button onClick={() => setRunScan(true)} disabled={scanLoading}>
                  {scanLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Scan className="h-4 w-4 mr-1" />}
                  Scan
                </Button>
              </div>
              {scanResults && <ScanResultsTable results={scanResults} />}
            </CardContent>
          </Card>
        </TabsContent>

        {/* === HISTORY TAB === */}
        <TabsContent value="history">
          <Card>
            <CardContent className="pt-4">
              <DecisionHistory symbol={symbol} limit={20} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
