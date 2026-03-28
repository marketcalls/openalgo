import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Loader2, Search, TrendingUp, History, Scan,
  LineChart, Target, Brain, BookOpen, ShieldAlert, Layers, Newspaper,
  FileText, Microscope,
} from 'lucide-react'
import {
  LivePriceHeader, DecisionHistory, EnhancedScanner, DecisionCard,
} from '@/components/ai-analysis'
import { TechnicalTab } from '@/components/ai-analysis/tabs/TechnicalTab'
import { StrategiesTab } from '@/components/ai-analysis/tabs/StrategiesTab'
import { DecisionTab } from '@/components/ai-analysis/tabs/DecisionTab'
import { FundamentalTab } from '@/components/ai-analysis/tabs/FundamentalTab'
import { WhyNotTab } from '@/components/ai-analysis/tabs/WhyNotTab'
import { MultiTFTab } from '@/components/ai-analysis/tabs/MultiTFTab'
import { NewsTab } from '@/components/ai-analysis/tabs/NewsTab'
import { DailyReportTab } from '@/components/ai-analysis/tabs/DailyReportTab'
import { ResearchTab } from '@/components/ai-analysis/tabs/ResearchTab'
import { useAIAnalysis, useAIScan, useAIStatus } from '@/hooks/useAIAnalysis'
import { showToast } from '@/utils/toast'

const NIFTY50 = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'SBIN',
  'BHARTIARTL', 'ITC', 'KOTAKBANK', 'LT', 'AXISBANK', 'BAJFINANCE',
  'ASIANPAINT', 'MARUTI', 'TITAN', 'SUNPHARMA', 'WIPRO', 'HCLTECH', 'ULTRACEMCO',
]

export default function AIAnalyzer() {
  const [symbol, setSymbol] = useState('RELIANCE')
  const [exchange, setExchange] = useState('NSE')
  const [interval, setInterval] = useState('D')
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

  const handleScanSelect = (sym: string) => {
    setSymbol(sym)
    setRunScan(false)
  }

  return (
    <div className="flex-1 overflow-y-auto">
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
              <SelectItem value="D">Daily</SelectItem>
              <SelectItem value="60m">1H</SelectItem>
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

      {/* Decision Card — always visible when analysis exists */}
      {analysis?.decision && Object.keys(analysis.decision).length > 0 && (
        <DecisionCard decision={analysis.decision} symbol={symbol} exchange={exchange} />
      )}

      {/* ═══ 8-Tab Layout: 6 Analysis + Scanner + History ═══ */}
      <Tabs defaultValue="technical" className="w-full">
        <TabsList className="flex flex-wrap h-auto gap-1">
          {/* Primary Analysis Tabs */}
          <TabsTrigger value="technical" className="text-xs">
            <LineChart className="h-3.5 w-3.5 mr-1" /> Technical
          </TabsTrigger>
          <TabsTrigger value="strategies" className="text-xs">
            <Target className="h-3.5 w-3.5 mr-1" /> Strategies
          </TabsTrigger>
          <TabsTrigger value="decision" className="text-xs">
            <Brain className="h-3.5 w-3.5 mr-1" /> Decision
          </TabsTrigger>
          <TabsTrigger value="fundamental" className="text-xs">
            <BookOpen className="h-3.5 w-3.5 mr-1" /> Fundamental
            <span className="ml-1 text-[10px] bg-muted px-1 rounded">P4</span>
          </TabsTrigger>
          <TabsTrigger value="whynot" className="text-xs">
            <ShieldAlert className="h-3.5 w-3.5 mr-1" /> Why Not
          </TabsTrigger>
          <TabsTrigger value="multitf" className="text-xs">
            <Layers className="h-3.5 w-3.5 mr-1" /> Multi-TF
          </TabsTrigger>
          <TabsTrigger value="news" className="text-xs">
            <Newspaper className="h-3.5 w-3.5 mr-1" /> News
          </TabsTrigger>
          <TabsTrigger value="research" className="text-xs">
            <Microscope className="h-3.5 w-3.5 mr-1" /> Research
          </TabsTrigger>
          <TabsTrigger value="report" className="text-xs">
            <FileText className="h-3.5 w-3.5 mr-1" /> Report
          </TabsTrigger>
          {/* Utility Tabs */}
          <TabsTrigger value="scanner" className="text-xs">
            <Scan className="h-3.5 w-3.5 mr-1" /> Scanner
          </TabsTrigger>
          <TabsTrigger value="history" className="text-xs">
            <History className="h-3.5 w-3.5 mr-1" /> History
          </TabsTrigger>
        </TabsList>

        {/* ═══ TECHNICAL TAB ═══ */}
        <TabsContent value="technical" className="space-y-4">
          {analysis ? (
            <TechnicalTab
              analysis={analysis}
              symbol={symbol}
              exchange={exchange}
              interval={interval}
            />
          ) : !isLoading ? (
            <div className="text-center py-12 text-muted-foreground">
              Enter a symbol and click Analyze to get AI trading intelligence
            </div>
          ) : null}
        </TabsContent>

        {/* ═══ STRATEGIES TAB ═══ */}
        <TabsContent value="strategies" className="space-y-4">
          {analysis ? (
            <StrategiesTab
              analysis={analysis}
              symbol={symbol}
              exchange={exchange}
              interval={interval}
            />
          ) : !isLoading ? (
            <div className="text-center py-12 text-muted-foreground">
              Run analysis first to access strategy panels
            </div>
          ) : null}
        </TabsContent>

        {/* ═══ DECISION TAB ═══ */}
        <TabsContent value="decision" className="space-y-4">
          {analysis ? (
            <DecisionTab
              analysis={analysis}
              symbol={symbol}
              exchange={exchange}
              interval={interval}
            />
          ) : !isLoading ? (
            <div className="text-center py-12 text-muted-foreground">
              Run analysis first to see strategy decision
            </div>
          ) : null}
        </TabsContent>

        {/* ═══ FUNDAMENTAL TAB ═══ */}
        <TabsContent value="fundamental">
          <FundamentalTab />
        </TabsContent>

        {/* ═══ WHY NOT TAB ═══ */}
        <TabsContent value="whynot" className="space-y-4">
          {analysis ? (
            <WhyNotTab analysis={analysis} />
          ) : !isLoading ? (
            <div className="text-center py-12 text-muted-foreground">
              Run analysis first to see risk factors
            </div>
          ) : null}
        </TabsContent>

        {/* ═══ MULTI-TF TAB ═══ */}
        <TabsContent value="multitf" className="space-y-4">
          <MultiTFTab symbol={symbol} exchange={exchange} />
        </TabsContent>

        {/* ═══ NEWS TAB ═══ */}
        <TabsContent value="news" className="space-y-4">
          <NewsTab symbol={symbol} exchange={exchange} />
        </TabsContent>

        {/* ═══ RESEARCH TAB ═══ */}
        <TabsContent value="research" className="space-y-4">
          <ResearchTab symbol={symbol} exchange={exchange} />
        </TabsContent>

        {/* ═══ DAILY REPORT TAB ═══ */}
        <TabsContent value="report" className="space-y-4">
          <DailyReportTab exchange={exchange} />
        </TabsContent>

        {/* ═══ SCANNER TAB ═══ */}
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
              {scanResults && (
                <EnhancedScanner results={scanResults} onSelectSymbol={handleScanSelect} />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ═══ HISTORY TAB ═══ */}
        <TabsContent value="history">
          <Card>
            <CardContent className="pt-4">
              <DecisionHistory symbol={symbol} limit={20} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
    </div>
  )
}
