import type * as PlotlyTypes from 'plotly.js'
import { useMemo } from 'react'
import Plot from 'react-plotly.js'
import type { PayoffResult } from '@/lib/strategyMath'
import { useThemeStore } from '@/stores/themeStore'

export interface PayoffChartProps {
  title: string
  spot: number
  atmIv: number
  tYears: number
  payoff: PayoffResult
  /** If true, show a dashed "T+0" curve in addition to expiry. */
  showTplus0?: boolean
  height?: number
}

export function PayoffChart({
  title,
  spot,
  atmIv,
  tYears,
  payoff,
  showTplus0 = true,
  height = 440,
}: PayoffChartProps) {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const colors = useMemo(
    () => ({
      paper: isDark ? (isAnalyzer ? '#1a1530' : '#0f172a') : '#ffffff',
      bg: isDark ? (isAnalyzer ? '#221a3a' : '#1e293b') : '#f8fafc',
      text: isDark ? '#e2e8f0' : '#1e293b',
      mutedText: isDark ? '#94a3b8' : '#64748b',
      grid: isDark ? 'rgba(148,163,184,0.18)' : 'rgba(15,23,42,0.08)',
      profit: isDark ? 'rgba(34,197,94,0.22)' : 'rgba(34,197,94,0.18)',
      loss: isDark ? 'rgba(239,68,68,0.22)' : 'rgba(239,68,68,0.18)',
      expiryLine: isDark ? '#fb923c' : '#ea580c',
      tplus0Line: isDark ? '#60a5fa' : '#2563eb',
      zeroLine: isDark ? 'rgba(226,232,240,0.5)' : 'rgba(15,23,42,0.5)',
      spotLine: isDark ? '#f472b6' : '#db2777',
      // Stepped σ bands: inner ±1σ darker, outer ±2σ lighter.
      sigma1Band: isDark ? 'rgba(148,163,184,0.22)' : 'rgba(100,116,139,0.16)',
      sigma2Band: isDark ? 'rgba(148,163,184,0.10)' : 'rgba(100,116,139,0.07)',
      sigmaTick: isDark ? 'rgba(226,232,240,0.35)' : 'rgba(15,23,42,0.3)',
    }),
    [isDark, isAnalyzer]
  )

  const { data, layout, config } = useMemo(() => {
    const { samples } = payoff
    if (samples.length === 0) {
      return {
        data: [] as PlotlyTypes.Data[],
        layout: {} as Partial<PlotlyTypes.Layout>,
        config: {},
      }
    }

    const xs = samples.map((s) => s.underlying)
    const ysExpiry = samples.map((s) => s.expiry)
    const ysT0 = samples.map((s) => s.tplus0)

    // Per-sample "% change from spot" — pre-formatted as a signed 2-decimal
    // string so the hover template can emit it verbatim. Plotly's format
    // spec is silently dropped when customdata is accessed via bracket
    // notation (`%{customdata[0]:+.2f}`), so we format in JS instead.
    const pctFromSpot = samples.map((s) => {
      const pct = ((s.underlying - spot) / spot) * 100
      const sign = pct >= 0 ? '+' : ''
      return `${sign}${pct.toFixed(2)}%`
    })

    // Split expiry into profit/loss fills via trace thresholding.
    const profitFill = samples.map((s) => (s.expiry >= 0 ? s.expiry : 0))
    const lossFill = samples.map((s) => (s.expiry < 0 ? s.expiry : 0))

    const sigmaT = (atmIv / 100) * Math.sqrt(Math.max(tYears, 1e-6))
    const sigmaMove = spot * sigmaT
    const band = (n: number) => ({ lo: spot - n * sigmaMove, hi: spot + n * sigmaMove })
    const b1 = band(1)
    const b2 = band(2)

    const traces: PlotlyTypes.Data[] = [
      {
        x: xs,
        y: profitFill,
        type: 'scatter',
        mode: 'none',
        fill: 'tozeroy',
        fillcolor: colors.profit,
        showlegend: false,
        hoverinfo: 'skip',
        name: 'Profit zone',
      },
      {
        x: xs,
        y: lossFill,
        type: 'scatter',
        mode: 'none',
        fill: 'tozeroy',
        fillcolor: colors.loss,
        showlegend: false,
        hoverinfo: 'skip',
        name: 'Loss zone',
      },
      {
        x: xs,
        y: ysExpiry,
        type: 'scatter',
        mode: 'lines',
        name: 'At Expiry',
        line: { color: colors.expiryLine, width: 2.2 },
        // customdata carries a pre-formatted percent string per point.
        customdata: pctFromSpot as unknown as PlotlyTypes.Datum[],
        hovertemplate:
          '<b>At Expiry P&L</b> ₹%{y:,.0f}' +
          '<br>Chg. from Spot: %{customdata}' +
          '<extra></extra>',
      },
    ]

    if (showTplus0) {
      traces.push({
        x: xs,
        y: ysT0,
        type: 'scatter',
        mode: 'lines',
        name: 'T+0',
        line: { color: colors.tplus0Line, width: 2, dash: 'dash' },
        hovertemplate: '<b>T+0 P&L</b> ₹%{y:,.0f}<extra></extra>',
      })
    }

    const shapes: Partial<PlotlyTypes.Shape>[] = [
      // zero line
      {
        type: 'line',
        xref: 'paper',
        x0: 0,
        x1: 1,
        yref: 'y',
        y0: 0,
        y1: 0,
        line: { color: colors.zeroLine, width: 1 },
      },
    ]

    // Stepped σ bands: the wider 2σ band is drawn first so the 1σ band
    // overlays on top of it, producing a visually distinct inner (darker)
    // and outer (lighter) zone rather than one uniform wash.
    if (sigmaMove > 0) {
      // Left outer band: from -2σ to -1σ
      shapes.push({
        type: 'rect',
        xref: 'x',
        x0: b2.lo,
        x1: b1.lo,
        yref: 'paper',
        y0: 0,
        y1: 1,
        fillcolor: colors.sigma2Band,
        line: { width: 0 },
        layer: 'below',
      })
      // Right outer band: from +1σ to +2σ
      shapes.push({
        type: 'rect',
        xref: 'x',
        x0: b1.hi,
        x1: b2.hi,
        yref: 'paper',
        y0: 0,
        y1: 1,
        fillcolor: colors.sigma2Band,
        line: { width: 0 },
        layer: 'below',
      })
      // Inner 1σ band
      shapes.push({
        type: 'rect',
        xref: 'x',
        x0: b1.lo,
        x1: b1.hi,
        yref: 'paper',
        y0: 0,
        y1: 1,
        fillcolor: colors.sigma1Band,
        line: { width: 0 },
        layer: 'below',
      })
      // Thin vertical ticks at each σ boundary
      for (const x of [b2.lo, b1.lo, b1.hi, b2.hi]) {
        shapes.push({
          type: 'line',
          xref: 'x',
          x0: x,
          x1: x,
          yref: 'paper',
          y0: 0,
          y1: 1,
          line: { color: colors.sigmaTick, width: 1, dash: 'dot' },
          layer: 'below',
        })
      }
    }

    // Spot line (drawn on top of bands)
    shapes.push({
      type: 'line',
      xref: 'x',
      x0: spot,
      x1: spot,
      yref: 'paper',
      y0: 0,
      y1: 1,
      line: { color: colors.spotLine, width: 1.5, dash: 'dot' },
    })

    const annotations: Partial<PlotlyTypes.Annotations>[] = []

    // Spot label sits prominently above the chart at y=1.04 (above plot area)
    annotations.push({
      x: spot,
      y: 1.06,
      xref: 'x',
      yref: 'paper',
      text: `<b>${spot.toFixed(2)}</b>`,
      showarrow: false,
      yanchor: 'bottom',
      font: { size: 12, color: colors.spotLine },
    })

    if (sigmaMove > 0) {
      const sigmaLabels: Array<{ x: number; text: string }> = [
        { x: b2.lo, text: '-2σ' },
        { x: b1.lo, text: '-1σ' },
        { x: b1.hi, text: '+1σ' },
        { x: b2.hi, text: '+2σ' },
      ]
      for (const s of sigmaLabels) {
        annotations.push({
          x: s.x,
          y: 1.06,
          xref: 'x',
          yref: 'paper',
          text: s.text,
          showarrow: false,
          yanchor: 'bottom',
          font: { size: 11, color: colors.mutedText },
        })
      }
    }

    // Breakeven lines/labels removed by design — the values are already
    // surfaced in the Strategy Positions metrics panel, and the lines added
    // visual clutter across the plot area.

    // Watermark: bottom-right corner, plain text only (no symbols).
    annotations.push({
      x: 1,
      y: 0,
      xref: 'paper',
      yref: 'paper',
      text: 'openalgo.in',
      showarrow: false,
      xanchor: 'right',
      yanchor: 'top',
      // Nudge below the plot area so it sits just under the x-axis labels.
      yshift: -36,
      xshift: -6,
      font: { size: 10, color: colors.mutedText },
      opacity: 0.85,
    })

    const chartLayout: Partial<PlotlyTypes.Layout> = {
      title: {
        text: title,
        font: { color: colors.text, size: 14 },
        // Push title up slightly so the σ / spot label row sits below it.
        y: 0.98,
        yanchor: 'top',
      },
      paper_bgcolor: colors.paper,
      plot_bgcolor: colors.bg,
      font: { color: colors.text, family: 'system-ui, sans-serif' },
      hovermode: 'x unified',
      hoverlabel: {
        bgcolor: isDark ? '#0f172a' : '#ffffff',
        font: { color: colors.text, size: 12 },
        bordercolor: colors.mutedText,
      },
      margin: { l: 70, r: 30, t: 80, b: 50 },
      showlegend: true,
      legend: {
        orientation: 'h',
        x: 0.5,
        xanchor: 'center',
        y: -0.18,
        font: { color: colors.text, size: 11 },
      },
      xaxis: {
        title: { text: 'Underlying Price', font: { color: colors.text, size: 12 } },
        tickfont: { color: colors.text, size: 10 },
        gridcolor: colors.grid,
        zeroline: false,
      },
      yaxis: {
        title: { text: 'Profit / Loss (₹)', font: { color: colors.text, size: 12 } },
        tickfont: { color: colors.text, size: 10 },
        gridcolor: colors.grid,
        zeroline: true,
        zerolinecolor: colors.zeroLine,
        zerolinewidth: 1,
      },
      shapes,
      annotations,
    }

    return {
      data: traces,
      layout: chartLayout,
      config: {
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['pan2d', 'select2d', 'lasso2d', 'autoScale2d', 'toggleSpikelines'],
        responsive: true,
      } as Partial<PlotlyTypes.Config>,
    }
  }, [payoff, spot, atmIv, tYears, showTplus0, title, colors, isDark])

  return (
    <Plot
      data={data}
      layout={layout}
      config={config}
      useResizeHandler
      style={{ width: '100%', height }}
    />
  )
}
