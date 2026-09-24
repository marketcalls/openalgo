/**
 * What this pins.
 *
 * The engine is stubbed, not the wiring around it: the real `buildChartTheme`
 * bridge runs, so a theme token that stopped resolving would fail here. Only
 * `createWidget` is a stub, because the assertions are about what this
 * component asks the engine for.
 *
 * Three of these matter more than the rest.
 *
 * Disposal, because a chart per pane that never destroys is a leak that is
 * invisible until an afternoon of switching symbols has a canvas and a frame
 * loop for each one.
 *
 * `onOrder`, because its absence is the entire no-trading guarantee. If a
 * future edit ever passes it through, the right-click menu grows live trade
 * rows on a page built to be read only, and nothing else in the codebase would
 * notice.
 *
 * `pollIntervalMs: 0`, because its absence is the entire no-live guarantee on
 * the controller side. A default poll would quietly re-read the store forever.
 */

import { render, waitFor } from '@testing-library/react'
import type { DataFeed } from 'openalgo-charts'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OpenAlgoChart } from './OpenAlgoChart'

interface WidgetStub {
  options: Record<string, unknown>
  destroyed: number
  reloads: number
  themes: unknown[]
  symbols: Array<[string, string | undefined]>
  intervals: string[]
  chartTypes: string[]
  handlers: Record<string, Array<(payload: unknown) => void>>
  ranges: Array<{ from: number; to: number }>
  symbol: () => string
  exchange: () => string
  interval: () => string
  chartType: () => string
  setSymbol: (symbol: string, exchange?: string) => void
  setInterval: (code: string) => void
  setChartType: (id: string) => void
  setTheme: (theme: unknown) => void
  reload: () => Promise<void>
  chart: {
    dataLayer: { length: number }
    getVisibleLogicalRange: () => { from: number; to: number } | null
    setVisibleLogicalRange: (r: { from: number; to: number }) => void
  }
  on: (event: string, cb: (payload: unknown) => void) => () => void
  destroy: () => void
}

const harness = vi.hoisted(() => {
  const widgets: WidgetStub[] = []
  const createWidget = vi.fn((_host: HTMLElement, options: Record<string, unknown>) => {
    let symbol = String(options.symbol ?? '')
    let exchange = String(options.exchange ?? '')
    let interval = String(options.interval ?? '')
    let chartType = String(options.chartType ?? '')
    const widget: WidgetStub = {
      options,
      destroyed: 0,
      reloads: 0,
      themes: [],
      symbols: [],
      intervals: [],
      chartTypes: [],
      handlers: {},
      ranges: [],
      isDestroyed: false,
      chart: {
        dataLayer: { length: 0 },
        getVisibleLogicalRange: () => widget.__range,
        setVisibleLogicalRange: (r: { from: number; to: number }) => {
          widget.ranges.push(r)
          widget.__range = r
        },
      },
      __range: null as { from: number; to: number } | null,
      symbol: () => symbol,
      exchange: () => exchange,
      interval: () => interval,
      chartType: () => chartType,
      setSymbol: (next: string, nextExchange?: string) => {
        widget.symbols.push([next, nextExchange])
        symbol = next
        if (nextExchange) exchange = nextExchange
      },
      setInterval: (code: string) => {
        if (harness.rejectInterval) throw new Error(`unknown interval "${code}"`)
        widget.intervals.push(code)
        interval = code
      },
      setChartType: (id: string) => {
        widget.chartTypes.push(id)
        chartType = id
      },
      setTheme: (theme: unknown) => {
        widget.themes.push(theme)
      },
      on: (event: string, cb: (payload: unknown) => void) => {
        widget.handlers[event] = [...(widget.handlers[event] ?? []), cb]
        return () => {
          widget.handlers[event] = (widget.handlers[event] ?? []).filter((h) => h !== cb)
        }
      },
      reload: async () => {
        widget.reloads += 1
      },
      destroy: () => {
        widget.destroyed += 1
      },
    }
    widgets.push(widget)
    return widget
  })
  const loadCustomIndicators = vi.fn(async () => ({ loaded: [], errors: [] }))
  return { widgets, createWidget, loadCustomIndicators, rejectInterval: false }
})

vi.mock('openalgo-charts/widget', () => ({ createWidget: harness.createWidget }))
vi.mock('@/lib/trading/customIndicators', () => ({
  loadCustomIndicators: harness.loadCustomIndicators,
}))

const feed: DataFeed = { getBars: async () => [] }

const latest = () => harness.widgets[harness.widgets.length - 1]

beforeEach(() => {
  harness.widgets.length = 0
  harness.createWidget.mockClear()
  harness.loadCustomIndicators.mockClear()
  harness.rejectInterval = false
})

describe('OpenAlgoChart', () => {
  it('never hands the engine an order callback', async () => {
    render(<OpenAlgoChart feed={feed} symbol="RELIANCE" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())
    expect('onOrder' in latest().options).toBe(false)
  })

  it('closes the history poll, so nothing re-reads the store in the background', async () => {
    render(<OpenAlgoChart feed={feed} symbol="RELIANCE" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())
    expect(latest().options.loading).toMatchObject({ pollIntervalMs: 0 })
  })

  it('forwards stream-driven repair options and still keeps the poll closed', async () => {
    render(
      <OpenAlgoChart
        feed={feed}
        symbol="RELIANCE"
        exchange="NSE"
        interval="1m"
        loading={{ refreshOnBarClose: true, refreshWindowBars: 5 }}
      />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())
    expect(latest().options.loading).toMatchObject({
      refreshOnBarClose: true,
      refreshWindowBars: 5,
      pollIntervalMs: 0,
    })
  })

  it('drives both engine clocks from the data horizon, not the wall clock', async () => {
    // Two separate failures came from the wall clock. The opening window is
    // built backwards from it, so a store whose newest candle is days old,
    // which is every store over a weekend, opened empty and reported having no
    // bars. And a refresh asks for a window ending at max(originalTo, now()),
    // throwing "History refresh returned no bars" when that is past the data,
    // which painted a stale error over 463,612 good candles on every tab focus.
    const endsAt = 1_789_120_740
    render(
      <OpenAlgoChart
        feed={feed}
        dataEndsAt={endsAt}
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="1m"
      />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())

    const options = latest().options as {
      now?: () => number
      loading?: { now?: () => number }
    }
    // The widget's clock is milliseconds; the controller's is seconds.
    expect(options.now?.()).toBe(endsAt * 1000)
    expect(options.loading?.now?.()).toBe(endsAt)
  })

  it('falls back to the wall clock for a live source with no horizon', async () => {
    const before = Math.floor(Date.now() / 1000)
    render(<OpenAlgoChart feed={feed} symbol="RELIANCE" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())

    const loading = latest().options.loading as { now?: () => number }
    expect(loading.now?.()).toBeGreaterThanOrEqual(before)
  })

  it('builds one widget and destroys it on unmount', async () => {
    const view = render(<OpenAlgoChart feed={feed} symbol="RELIANCE" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    view.unmount()
    await waitFor(() => expect(latest().destroyed).toBe(1))
  })

  it('loads user indicator modules before building, so the picker lists them', async () => {
    render(<OpenAlgoChart feed={feed} symbol="RELIANCE" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())
    expect(harness.loadCustomIndicators).toHaveBeenCalled()
  })

  it('still builds a chart when a user indicator module will not load', async () => {
    harness.loadCustomIndicators.mockRejectedValueOnce(new Error('bad module'))
    render(<OpenAlgoChart feed={feed} symbol="RELIANCE" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
  })

  it('applies a symbol change through the handle rather than rebuilding', async () => {
    // A rebuild would throw away the viewport, the drawings and the indicator
    // panes the user just set up.
    const view = render(<OpenAlgoChart feed={feed} symbol="RELIANCE" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))

    view.rerender(<OpenAlgoChart feed={feed} symbol="SBIN" exchange="NSE" interval="D" />)
    await waitFor(() => expect(latest().symbols).toEqual([['SBIN', 'NSE']]))
    expect(harness.createWidget).toHaveBeenCalledTimes(1)
    expect(latest().destroyed).toBe(0)
  })

  it('applies interval and chart type through the handle too', async () => {
    const view = render(
      <OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" chartType="candlestick" />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))

    view.rerender(
      <OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="25m" chartType="line" />
    )
    await waitFor(() => expect(latest().intervals).toEqual(['25m']))
    expect(latest().chartTypes).toEqual(['line'])
    expect(harness.createWidget).toHaveBeenCalledTimes(1)
  })

  it('does not re-apply a value the engine already holds', async () => {
    const view = render(<OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    view.rerender(<OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" />)
    expect(latest().symbols).toEqual([])
    expect(latest().intervals).toEqual([])
  })

  it('survives a host that declares its callbacks inline', async () => {
    // An inline arrow is a new identity every render. If the callbacks were in
    // the build effect's deps this would rebuild the chart on every keystroke.
    const view = render(
      <OpenAlgoChart
        feed={feed}
        symbol="X"
        exchange="NSE"
        interval="D"
        onSymbolChange={() => {}}
        onData={() => {}}
      />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    view.rerender(
      <OpenAlgoChart
        feed={feed}
        symbol="X"
        exchange="NSE"
        interval="D"
        onSymbolChange={() => {}}
        onData={() => {}}
      />
    )
    expect(harness.createWidget).toHaveBeenCalledTimes(1)
  })

  it('rebuilds when the data source itself changes', async () => {
    const view = render(<OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    const first = latest()

    const other: DataFeed = { getBars: async () => [] }
    view.rerender(<OpenAlgoChart feed={other} symbol="X" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(2))
    expect(first.destroyed).toBe(1)
  })

  it('re-themes without rebuilding', async () => {
    const { useThemeStore } = await import('@/stores/themeStore')
    render(<OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    const before = latest().themes.length

    await waitFor(() => expect(latest().options.theme).toBeTruthy())
    useThemeStore.setState({ mode: useThemeStore.getState().mode === 'dark' ? 'light' : 'dark' })

    await waitFor(() => expect(latest().themes.length).toBeGreaterThan(before))
    expect(harness.createWidget).toHaveBeenCalledTimes(1)
  })

  it('reports a finished load so the host can explain an empty chart', async () => {
    const onData = vi.fn()
    render(<OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="W" onData={onData} />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())

    for (const handler of latest().handlers.data ?? []) {
      handler({ symbol: 'X', interval: 'W', bars: 0 })
    }
    expect(onData).toHaveBeenCalledWith({ symbol: 'X', interval: 'W', bars: 0 })
  })

  it('hands the host the live handle, then null on teardown', async () => {
    const onReady = vi.fn()
    const view = render(
      <OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" onReady={onReady} />
    )
    await waitFor(() =>
      expect(onReady).toHaveBeenCalledWith(
        expect.objectContaining({ destroy: expect.any(Function) })
      )
    )
    view.unmount()
    await waitFor(() => expect(onReady).toHaveBeenLastCalledWith(null))
  })

  it('passes a persist namespace through, and omits it when there is none', async () => {
    const view = render(
      <OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" persistKey="historify-p1" />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    expect(latest().options.persist).toBe('historify-p1')

    view.unmount()
    render(<OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(2))
    expect('persist' in latest().options).toBe(false)
  })
  /**
   * The engine keeps its own interval vocabulary and throws on a code outside
   * it. These pin the crash that found: a month token reached setInterval from
   * an effect and unwound through React to the error boundary.
   */
  it('teaches the engine a calendar timeframe instead of failing on it', async () => {
    render(<OpenAlgoChart feed={feed} symbol="NIFTY" exchange="NSE_INDEX" interval="M" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())
    // Registered, so it is used as asked rather than silently downgraded.
    expect(latest().options.interval).toBe('M')
  })

  it('opens on daily, and says so, when the timeframe cannot be resolved at all', async () => {
    const onIntervalRejected = vi.fn()
    render(
      <OpenAlgoChart
        feed={feed}
        symbol="X"
        exchange="NSE"
        interval="MO"
        onIntervalRejected={onIntervalRejected}
      />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())
    expect(latest().options.interval).toBe('D')
    expect(onIntervalRejected).toHaveBeenCalledWith('MO')
  })

  it('survives the engine refusing a timeframe, keeping the one it had', async () => {
    const onIntervalRejected = vi.fn()
    const view = render(
      <OpenAlgoChart
        feed={feed}
        symbol="X"
        exchange="NSE"
        interval="D"
        onIntervalRejected={onIntervalRejected}
      />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))

    harness.rejectInterval = true
    // Would previously throw out of the effect and unmount the tree.
    view.rerender(
      <OpenAlgoChart
        feed={feed}
        symbol="X"
        exchange="NSE"
        interval="4h"
        onIntervalRejected={onIntervalRejected}
      />
    )

    await waitFor(() => expect(onIntervalRejected).toHaveBeenCalledWith('4h'))
    expect(latest().destroyed).toBe(0)
    expect(latest().interval()).toBe('D')
  })
  it('reloads once the horizon arrives, since the catalog lands after the build', async () => {
    // The catalog is fetched after mount, so the first build runs with no
    // horizon and loads against the wall clock. Without this the chart sat on
    // "No bars" over half a million stored candles.
    const view = render(
      <OpenAlgoChart feed={feed} symbol="NIFTY" exchange="NSE_INDEX" interval="1m" />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    expect(latest().reloads).toBe(0)

    view.rerender(
      <OpenAlgoChart
        feed={feed}
        dataEndsAt={1_789_120_740}
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="1m"
      />
    )
    await waitFor(() => expect(latest().reloads).toBe(1))
    // Reloaded, not rebuilt: drawings and studies survive.
    expect(harness.createWidget).toHaveBeenCalledTimes(1)
  })

  it('does not reload when the horizon has not moved', async () => {
    const view = render(
      <OpenAlgoChart
        feed={feed}
        dataEndsAt={1_789_120_740}
        symbol="X"
        exchange="NSE"
        interval="D"
      />
    )
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalledTimes(1))
    view.rerender(
      <OpenAlgoChart
        feed={feed}
        dataEndsAt={1_789_120_740}
        symbol="X"
        exchange="NSE"
        interval="D"
      />
    )
    expect(latest().reloads).toBe(0)
  })
  it('puts the viewport back when the first load lands outside it', async () => {
    // The widget fixes its range at build time, before the first load
    // resolves, and never re-anchors. With 750 stored bars the saved viewport
    // was {from: 749, to: 1503}: past the end of its own data, so the chart
    // read as blank with one candle at the edge.
    render(<OpenAlgoChart feed={feed} symbol="NIFTY" exchange="NSE_INDEX" interval="1m" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())

    const w = latest()
    w.chart.dataLayer.length = 750
    w.chart.setVisibleLogicalRange({ from: 749, to: 1503 })
    w.ranges.length = 0

    for (const h of w.handlers.data ?? []) h({ symbol: 'NIFTY', interval: '1m', bars: 750 })

    expect(w.ranges).toHaveLength(1)
    // The newest 500 bars, plus a little clear air past the last candle.
    expect(w.ranges[0].from).toBe(250)
    expect(w.ranges[0].to).toBeGreaterThan(749)
  })

  it('leaves a viewport that already overlaps the data alone', async () => {
    // Scrolling back through history must not be yanked to the right edge.
    render(<OpenAlgoChart feed={feed} symbol="NIFTY" exchange="NSE_INDEX" interval="1m" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())

    const w = latest()
    w.chart.dataLayer.length = 750
    w.chart.setVisibleLogicalRange({ from: 10, to: 120 })
    w.ranges.length = 0

    for (const h of w.handlers.data ?? []) h({ symbol: 'NIFTY', interval: '1m', bars: 750 })
    expect(w.ranges).toEqual([])
  })

  it('does nothing when a load brought no bars', async () => {
    render(<OpenAlgoChart feed={feed} symbol="X" exchange="NSE" interval="D" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())
    const w = latest()
    w.ranges.length = 0
    for (const h of w.handlers.data ?? []) h({ symbol: 'X', interval: 'D', bars: 0 })
    expect(w.ranges).toEqual([])
  })
  it('does not fight a user who scrolled back through history', async () => {
    // A second load, for instance paging older bars in, must leave the view
    // exactly where the reader put it.
    render(<OpenAlgoChart feed={feed} symbol="NIFTY" exchange="NSE_INDEX" interval="1m" />)
    await waitFor(() => expect(harness.createWidget).toHaveBeenCalled())

    const w = latest()
    w.chart.dataLayer.length = 750
    w.chart.setVisibleLogicalRange({ from: 749, to: 1503 })
    for (const h of w.handlers.data ?? []) h({ symbol: 'NIFTY', interval: '1m', bars: 750 })
    w.ranges.length = 0

    // Reader scrolls off to the far left, then more history arrives.
    w.chart.setVisibleLogicalRange({ from: -900, to: -400 })
    w.ranges.length = 0
    for (const h of w.handlers.data ?? []) h({ symbol: 'NIFTY', interval: '1m', bars: 1500 })
    expect(w.ranges).toEqual([])
  })
})
