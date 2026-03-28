import { useState, useEffect, useRef } from 'react'
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts'
import type { IChartApi } from 'lightweight-charts'
import { Brain, TrendingUp, ShieldCheck, Activity } from 'lucide-react'
import { toCandlestickData, toChartTime } from '@/lib/lightweightCharts'

/**
 * 🚀 INSTITUTIONAL ML ADVISOR - SUPER DEMO
 * This version is 100% self-contained to bypass pathing and auth errors.
 */

// --- MOCK DATA ---
const MOCK_SIGNAL = {
  symbol: "RELIANCE",
  trade_intent: { action: "BUY", entry: 1414.00, target_1: 1418.63, target_2: 1423.26, stop_loss: 1407.06, confidence: 0.36 },
  intelligence: { market_regime: "BEAR REGIME 📉", strategy_logic: ["Trend: Negative Momentum", "VIX: High Volatility Expansion", "Sector: Energy Underperforming"] },
  risk_moderator: { score: 25, status: "REJECTED", vetoes: ["Low R:R Ratio (0.67 < 1.5)", "Negative Expectancy (R:R < 1)", "Low Model Confidence (< 60%)"] }
}

export default function MLAdvisorDemo() {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any>(null)
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const candlestickSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null)
  
  useEffect(() => {
    if (!chartContainerRef.current) return
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#09090b' }, textColor: '#d4d4d8' },
      grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
      width: chartContainerRef.current.clientWidth,
      height: 400,
    })
    const candlestickSeries = chart.addSeries(CandlestickSeries, { upColor: '#22c55e', downColor: '#ef4444' })
    
    // Generate simple candles
    const mockCandles = []
    let price = 1410
    for (let i = 0; i < 60; i++) {
        const open = price + (Math.random() - 0.5) * 4
        const close = open + (Math.random() - 0.5) * 4
        mockCandles.push({
          time: toChartTime(Math.floor(Date.now() / 1000) - (60 - i) * 900),
          open,
          high: Math.max(open, close) + 1,
          low: Math.min(open, close) - 1,
          close,
        })
        price = close
    }
    candlestickSeries.setData(toCandlestickData(mockCandles))
    candlestickSeriesRef.current = candlestickSeries
    return () => chart.remove()
  }, [])

  const runDemo = () => {
    setLoading(true)
    setTimeout(() => {
      setData(MOCK_SIGNAL)
      if (candlestickSeriesRef.current) {
        candlestickSeriesRef.current.createPriceLine({ price: 1414, color: '#3b82f6', lineStyle: 2, title: 'ENTRY' })
        candlestickSeriesRef.current.createPriceLine({ price: 1418.63, color: '#22c55e', title: 'T1' })
        candlestickSeriesRef.current.createPriceLine({ price: 1407.06, color: '#ef4444', title: 'SL' })
      }
      setLoading(false)
    }, 800)
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#000', color: 'white', padding: '2rem', fontFamily: 'sans-serif' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <div>
          <h1 style={{ fontSize: '1.875rem', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '0.75rem', margin: 0 }}>
            <Brain size={40} color="#a855f7" /> OpenAlgo ML Advisor 
            <span style={{ fontSize: '0.75rem', backgroundColor: '#3b0764', color: '#d8b4fe', padding: '0.25rem 0.75rem', borderRadius: '9999px', marginLeft: '1rem' }}>DEMO MODE</span>
          </h1>
          <p style={{ color: '#71717a', marginTop: '0.5rem' }}>Institutional Intelligence Node (Fully Standalone)</p>
        </div>
        <button onClick={runDemo} style={{ backgroundColor: '#9333ea', color: 'white', padding: '0.75rem 2rem', borderRadius: '0.5rem', fontWeight: 'bold', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {loading ? <Activity className="animate-spin" /> : <TrendingUp size={20} />} RUN ANALYTICS
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2rem' }}>
        <div style={{ backgroundColor: '#18181b', borderRadius: '0.75rem', border: '1px solid #27272a', padding: '1.5rem' }}>
          <p style={{ color: '#71717a', fontSize: '0.875rem', marginBottom: '1rem', textTransform: 'uppercase' }}>ML Signal Overlay - RELIANCE (15m)</p>
          <div ref={chartContainerRef} style={{ borderRadius: '0.5rem', overflow: 'hidden', border: '1px solid #27272a' }} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Risk Card */}
          <div style={{ backgroundColor: '#18181b', borderRadius: '0.75rem', borderLeft: '4px solid #ef4444', borderTop: '1px solid #27272a', borderRight: '1px solid #27272a', borderBottom: '1px solid #27272a', padding: '1.5rem' }}>
            <p style={{ color: '#71717a', fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}><ShieldCheck size={16} /> RISK MODERATOR</p>
            {data ? (
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '4rem', fontWeight: '900', color: '#ef4444' }}>{data.risk_moderator.score}</div>
                <div style={{ backgroundColor: '#7f1d1d', color: '#fca5a5', padding: '0.25rem 1rem', borderRadius: '0.25rem', display: 'inline-block', fontWeight: 'bold', marginBottom: '1rem' }}>{data.risk_moderator.status}</div>
                <div style={{ textAlign: 'left', marginTop: '1rem' }}>
                  <p style={{ fontSize: '0.75rem', fontWeight: 'bold', color: '#f87171', marginBottom: '0.5rem' }}>🚫 VETO TRIGGERS:</p>
                  {data.risk_moderator.vetoes.map((v: any, i: number) => (
                    <div key={i} style={{ fontSize: '0.75rem', color: '#fca5a5', backgroundColor: '#450a0a', padding: '0.5rem', borderRadius: '0.25rem', marginBottom: '0.25rem', border: '1px solid #7f1d1d' }}>{v}</div>
                  ))}
                </div>
              </div>
            ) : <p style={{ textAlign: 'center', color: '#3f3f46', padding: '4rem 0' }}>Waiting for analytics...</p>}
          </div>

          {/* Trade Intent */}
          <div style={{ backgroundColor: '#18181b', borderRadius: '0.75rem', border: '1px solid #27272a', padding: '1.5rem' }}>
            <p style={{ color: '#71717a', fontSize: '0.875rem' }}>TRADE INTENT</p>
            {data ? (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}><span>Action</span><span style={{ color: '#22c55e', fontWeight: 'bold' }}>BUY</span></div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.875rem', fontFamily: 'monospace' }}>
                  <span style={{ color: '#71717a' }}>ENTRY:</span><span style={{ textAlign: 'right' }}>1414.00</span>
                  <span style={{ color: '#71717a' }}>TARGET:</span><span style={{ textAlign: 'right', color: '#22c55e' }}>1418.63</span>
                  <span style={{ color: '#71717a' }}>STOP:</span><span style={{ textAlign: 'right', color: '#ef4444' }}>1407.06</span>
                </div>
              </div>
            ) : <p style={{ textAlign: 'center', color: '#3f3f46' }}>No Intent</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
