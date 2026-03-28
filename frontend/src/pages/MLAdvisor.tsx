import { useState, useEffect, useRef } from 'react'
import { createChart, ColorType, CrosshairMode, CandlestickSeries } from 'lightweight-charts'
import type { IChartApi } from 'lightweight-charts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Brain, TrendingUp, ShieldCheck, ShieldAlert, ChevronRight, Activity } from 'lucide-react'
import { showToast } from '@/utils/toast'
import { cn } from '@/lib/utils'
import { toCandlestickData } from '@/lib/lightweightCharts'
import { useThemeStore } from '@/stores/themeStore'

// Types for the ML Advisor response
interface RiskModerator {
  score: number
  status: 'APPROVED' | 'WARNING' | 'REJECTED'
  vetoes: string[]
}

interface TradeIntent {
  action: 'BUY' | 'SELL'
  entry: number
  stop_loss: number
  target_1: number
  target_2: number
  confidence: number
}

interface Intelligence {
  market_regime: string
  strategy_logic: string[]
}

interface RecommendationResponse {
  symbol: string
  model_version: string
  timestamp: string
  trade_intent: TradeIntent
  intelligence: Intelligence
  risk_moderator: RiskModerator
}

export default function MLAdvisor() {
  const { mode } = useThemeStore()
  const isDarkMode = mode === 'dark'
  
  const [symbol, setSymbol] = useState('RELIANCE')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<RecommendationResponse | null>(null)
  
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlestickSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  
  // --- Chart Initialization ---
  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: isDarkMode ? '#09090b' : '#ffffff' },
        textColor: isDarkMode ? '#d4d4d8' : '#18181b',
      },
      grid: {
        vertLines: { color: isDarkMode ? '#27272a' : '#e4e4e7' },
        horzLines: { color: isDarkMode ? '#27272a' : '#e4e4e7' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false },
    })

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    chartRef.current = chart
    candlestickSeriesRef.current = candlestickSeries

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth })
      }
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [isDarkMode])

  // --- Run Analytics (Call Backend) ---
  const runAnalytics = async () => {
    setLoading(true)
    try {
      // 1. Fetch ML Recommendation
      const response = await fetch(`/api/ml/recommend/${symbol}`)
      const json = await response.json()
      
      if (json.status === 'error') {
        showToast.error(json.message)
        return
      }
      
      const rec = json.data as RecommendationResponse
      setData(rec)
      
      // 2. Fetch Candle Data (Reuse existing API or add logic here to fetch form historify)
      // For this demo, we'll fetch from the existing historify API
      const histResponse = await fetch(`/api/historify/${symbol}/15m?limit=100`)
      const histJson = await histResponse.json()
      
      if (histJson.data && candlestickSeriesRef.current && chartRef.current) {
         const candles = histJson.data.map((c: any) => ({
            time: c.timestamp,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
         })).sort((a: any, b: any) => a.time - b.time)
         
         candlestickSeriesRef.current.setData(toCandlestickData(candles))
         
         // 3. Draw ML Levels (Price Lines)
         // Clear previous lines (not directly supported, so we recreate series or just add new ones)
         // Simpler approach: Create PriceLines
         
         const { trade_intent } = rec
         
         candlestickSeriesRef.current.createPriceLine({
            price: trade_intent.entry,
            color: '#3b82f6', // Blue
            lineWidth: 2,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: 'ENTRY',
         })
         
         candlestickSeriesRef.current.createPriceLine({
            price: trade_intent.target_1,
            color: '#22c55e', // Green
            lineWidth: 2,
            axisLabelVisible: true,
            title: 'TARGET 1',
         })

         candlestickSeriesRef.current.createPriceLine({
            price: trade_intent.target_2,
            color: '#22c55e', // Green
            lineWidth: 1,
            axisLabelVisible: true,
            title: 'TARGET 2',
         })
         
         candlestickSeriesRef.current.createPriceLine({
            price: trade_intent.stop_loss,
            color: '#ef4444', // Red
            lineWidth: 2,
            axisLabelVisible: true,
            title: 'STOP LOSS',
         })
         
         chartRef.current.timeScale().fitContent()
      }
      
      showToast.success(`Generated recommendation for ${symbol}`)
      
    } catch (error) {
      console.error(error)
      showToast.error('Failed to run analytics')
    } finally {
      setLoading(false)
    }
  }

  // Helper for Survival Score Color
  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-500'
    if (score >= 60) return 'text-yellow-500'
    return 'text-red-500'
  }

  return (
    <div className="container mx-auto p-4 space-y-6">
      {/* Header / Control Bar */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Brain className="h-8 w-8 text-purple-500" />
            ML Advisor <span className="text-xs font-normal text-muted-foreground border px-2 py-0.5 rounded-full">v2.1 (Swing)</span>
          </h1>
          <p className="text-muted-foreground text-sm">Institutional-Grade Intelligence Node</p>
        </div>
        
        <div className="flex items-center gap-3">
            <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="Symbol" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="RELIANCE">RELIANCE</SelectItem>
              <SelectItem value="INFY" disabled>INFY (Coming Soon)</SelectItem>
              <SelectItem value="TCS" disabled>TCS (Coming Soon)</SelectItem>
            </SelectContent>
          </Select>
          
          <Button onClick={runAnalytics} disabled={loading} className="bg-purple-600 hover:bg-purple-700">
            {loading ? <Activity className="mr-2 h-4 w-4 animate-spin" /> : <TrendingUp className="mr-2 h-4 w-4" />}
            Run Analytics
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Chart Area */}
        <Card className="lg:col-span-2 shadow-md border-muted">
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground flex justify-between">
                    <span>ML SIGNAL OVERLAY (15m)</span>
                    {data && <span className="text-xs">Model: {data.model_version}</span>}
                </CardTitle>
            </CardHeader>
            <CardContent>
                <div ref={chartContainerRef} className="w-full h-[400px] rounded-lg border bg-card/50" />
            </CardContent>
        </Card>

        {/* Intelligence Panel (Risk Moderator) */}
        <div className="space-y-6">
            {/* Survival Score Card */}
            <Card className="border-l-4 border-l-purple-500 shadow-md">
                <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                        <ShieldCheck className="h-4 w-4" />
                        RISK MODERATOR (SURVIVAL SCORE)
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    {data ? (
                        <div className="text-center py-4">
                            <div className={cn("text-5xl font-bold mb-2", getScoreColor(data.risk_moderator.score))}>
                                {data.risk_moderator.score}
                            </div>
                            <Badge variant={data.risk_moderator.status === 'APPROVED' ? 'default' : 'destructive'} className="text-md px-4 py-1">
                                {data.risk_moderator.status}
                            </Badge>
                            
                            {data.risk_moderator.vetoes.length > 0 && (
                                <div className="mt-4 text-left bg-red-500/10 p-3 rounded-md border border-red-500/20">
                                    <p className="text-xs font-bold text-red-500 mb-1 flex items-center gap-1">
                                        <ShieldAlert className="h-3 w-3" /> VETO TRIGGERS:
                                    </p>
                                    <ul className="list-disc list-inside text-xs text-red-400 space-y-1">
                                        {data.risk_moderator.vetoes.map((v, i) => (
                                            <li key={i}>{v}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="text-center py-10 text-muted-foreground">Run analytics to see score</div>
                    )}
                </CardContent>
            </Card>

            {/* Trade Plan Card */}
            <Card className="shadow-md">
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">TRADE INTENT</CardTitle>
                </CardHeader>
                <CardContent>
                    {data ? (
                        <div className="space-y-3">
                            <div className="flex justify-between items-center pb-2 border-b">
                                <span className="text-sm">Action</span>
                                <span className={cn("font-bold text-lg", data.trade_intent.action === 'BUY' ? 'text-green-500' : 'text-red-500')}>
                                    {data.trade_intent.action}
                                </span>
                            </div>
                            
                            <div className="grid grid-cols-2 gap-2 text-sm">
                                <div className="text-muted-foreground">Entry:</div>
                                <div className="font-mono text-right">{data.trade_intent.entry.toFixed(2)}</div>
                                
                                <div className="text-muted-foreground">Target 1:</div>
                                <div className="font-mono text-right text-green-500">{data.trade_intent.target_1.toFixed(2)}</div>
                                
                                <div className="text-muted-foreground">Target 2:</div>
                                <div className="font-mono text-right text-green-500">{data.trade_intent.target_2.toFixed(2)}</div>
                                
                                <div className="text-muted-foreground">Stop Loss:</div>
                                <div className="font-mono text-right text-red-500">{data.trade_intent.stop_loss.toFixed(2)}</div>
                            </div>
                            
                            <div className="pt-2 border-t mt-2">
                                <div className="flex justify-between text-xs text-muted-foreground mb-1">
                                    <span>Model Confidence</span>
                                    <span>{(data.trade_intent.confidence * 100).toFixed(1)}%</span>
                                </div>
                                <div className="h-2 bg-secondary rounded-full overflow-hidden">
                                    <div 
                                        className={cn("h-full rounded-full", data.trade_intent.confidence > 0.7 ? "bg-green-500" : "bg-yellow-500")} 
                                        style={{ width: `${data.trade_intent.confidence * 100}%` }} 
                                    />
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="text-center py-10 text-muted-foreground">No active signal</div>
                    )}
                </CardContent>
            </Card>
            
            {/* Market Regime Card */}
             <Card className="shadow-md">
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">MARKET REGIME</CardTitle>
                </CardHeader>
                <CardContent>
                    {data ? (
                         <div>
                            <div className="text-lg font-semibold mb-2">{data.intelligence.market_regime}</div>
                            <div className="space-y-1">
                                {data.intelligence.strategy_logic.map((reason, i) => (
                                    <div key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                                        <ChevronRight className="h-3 w-3 mt-0.5 shrink-0" />
                                        <span>{reason}</span>
                                    </div>
                                ))}
                            </div>
                         </div>
                    ) : (
                        <div className="text-center py-4 text-muted-foreground">-</div>
                    )}
                </CardContent>
            </Card>
        </div>
      </div>
    </div>
  )
}
