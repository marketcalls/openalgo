/**
 * A stand-in for the shared chart, for tests of the hosts that mount it.
 *
 * jsdom has no canvas, so the real widget cannot be built here. The point of
 * this fake is that it keeps the one behaviour a host actually depends on: the
 * chart is what calls `getBars`, and it calls it again whenever the host asks
 * it to reload. A host tested against a chart that never fetches would pass
 * with its feed wired to nothing.
 *
 * What it deliberately does not fake is drawing. Nothing here proves a series
 * appeared on screen, and no assertion in a jsdom test should claim it did.
 */

import type { Bar, LiveBarMeta } from 'openalgo-charts'
import { useEffect, useRef, useState } from 'react'
import type { OpenAlgoChartProps } from '@/components/chart/OpenAlgoChart'

/** Series a host created, so a test can read back what it asked for. */
export interface FakeSeries {
  options: Record<string, unknown>
  data: { time: number; value?: number }[]
  style: Record<string, unknown>
  removed: boolean
}

export interface FakeWidgetState {
  series: FakeSeries[]
  indicators: { id: string; name: string }[]
  /** Style patches applied to the primary series. */
  primaryStyle: Record<string, unknown>
  crosshair: ((payload: unknown) => void)[]
  /** Oldest bar the feed has delivered, the anchor a page is fetched before. */
  loadedFrom?: number
  /** Ask the feed for the window before what is held, as scrolling left does. */
  pageOlder: () => Promise<void>
  /** What the fake controller holds: the last load's bars and request. */
  bars: Bar[]
  request: { symbol: string; exchange: string; interval: string } | null
  /** Live bars a host pushed into the controller, with their metadata. */
  pushed: Array<[Bar, LiveBarMeta | undefined]>
  /** Snapshot listeners a host registered on the controller. */
  dataListeners: Array<(snapshot: unknown) => void>
}

/** Hand every controller listener a snapshot, the way a load or a repair does. */
export function publishData(state: FakeWidgetState, reason: 'load' | 'refresh', bars: Bar[]): void {
  state.bars = bars
  const snapshot = {
    request: state.request,
    bars,
    status: 'ready',
    historyStatus: 'idle',
    hasMore: null,
    reason,
    paused: false,
  }
  for (const cb of state.dataListeners) cb(snapshot)
}

function makeWidget(state: FakeWidgetState, reload: () => Promise<void>) {
  const listeners = new Set<() => void>()
  // The real widget always exposes its root element, and hosts reach through it
  // for chrome the engine owns, such as the drawing rail. A fake without one
  // makes those hosts throw on mount rather than exercising them.
  const root = document.createElement('div')
  const rail = document.createElement('div')
  rail.className = 'oac-rail'
  root.appendChild(rail)

  const widget = {
    isDestroyed: false,
    root,
    reload,
    openSettings: () => true,
    openIndicatorPicker: () => true,
    dataController: {
      subscribe: (cb: (snapshot: unknown) => void) => {
        state.dataListeners.push(cb)
        return () => {
          state.dataListeners = state.dataListeners.filter((fn) => fn !== cb)
        }
      },
      getState: () => ({
        request: state.request,
        bars: state.bars,
        status: 'ready',
        historyStatus: 'idle',
        hasMore: null,
        reason: 'load',
        paused: false,
      }),
      bars: () => state.bars,
      pushBar: (bar: Bar, meta?: LiveBarMeta) => {
        state.pushed.push([bar, meta])
      },
    },
    series: {
      applyOptions: (style: Record<string, unknown>) => {
        Object.assign(state.primaryStyle, style)
      },
    },
    objects: {
      subscribe: (cb: () => void) => {
        listeners.add(cb)
        return () => listeners.delete(cb)
      },
      list: () => [],
      openSettings: () => true,
    },
    chart: {
      indicators: () => state.indicators,
      addIndicator: (id: string) => {
        state.indicators.push({ id, name: id })
        for (const cb of listeners) cb()
      },
      removeIndicator: (id: string) => {
        state.indicators = state.indicators.filter((i) => i.id !== id)
        for (const cb of listeners) cb()
      },
      addSeries: (type: string, options: Record<string, unknown> = {}) => {
        const record: FakeSeries = {
          options: { type, ...options },
          data: [],
          style: { ...((options.style as Record<string, unknown>) ?? {}) },
          removed: false,
        }
        state.series.push(record)
        return {
          setData: (data: { time: number; value?: number }[]) => {
            record.data = data
          },
          applyOptions: (style: Record<string, unknown>) => {
            Object.assign(record.style, style)
          },
          remove: () => {
            record.removed = true
          },
        }
      },
      on: (event: string, cb: (payload: unknown) => void) => {
        if (event === 'crosshair:move') state.crosshair.push(cb)
        return () => {
          state.crosshair = state.crosshair.filter((fn) => fn !== cb)
        }
      },
      takeScreenshot: () => null,
    },
  }
  return widget
}

/** A fresh recorder for one test. */
export function fakeWidgetState(): FakeWidgetState {
  return {
    series: [],
    indicators: [],
    primaryStyle: {},
    crosshair: [],
    pageOlder: async () => {},
    bars: [],
    request: null,
    pushed: [],
    dataListeners: [],
  }
}

/**
 * Move the crosshair onto a bar, or off the data when `time` is null.
 *
 * The engine sends all-null fields on pointer leave, so the off-the-data case
 * has to be the real shape and not merely a missing time.
 */
export function moveCrosshair(
  state: FakeWidgetState,
  time: number | null,
  point: { x: number; y: number } = { x: 320, y: 180 }
): void {
  const payload =
    time === null
      ? { time: null, index: null, price: null, bar: null, point: null }
      : { time, index: 0, price: 0, bar: null, point }
  for (const cb of state.crosshair) cb(payload)
}

/**
 * Build the module replacement for `@/components/chart/OpenAlgoChart`.
 *
 * The component loads on mount, reloads when the timeframe or the instrument
 * changes, and reloads when the host calls `widget.reload()`, which is what the
 * real one does. Failures reach the host through `onData`, as they do there.
 */
export function fakeOpenAlgoChart(state: FakeWidgetState) {
  return function FakeOpenAlgoChart(props: OpenAlgoChartProps) {
    const [, bump] = useState(0)
    const latest = useRef(props)
    latest.current = props

    const load = useRef<() => Promise<void>>(async () => {})
    load.current = async () => {
      const p = latest.current
      try {
        const bars = await p.feed.getBars({
          symbol: p.symbol,
          exchange: p.exchange,
          interval: p.interval,
        })
        state.loadedFrom = bars[0]?.time ?? state.loadedFrom
        // The real controller publishes the load to its subscribers before the
        // host hears about it through onData.
        state.request = { symbol: p.symbol, exchange: p.exchange, interval: p.interval }
        publishData(state, 'load', bars as Bar[])
        p.onData?.({ symbol: p.symbol, interval: p.interval, bars: bars.length })
      } catch (error) {
        p.onData?.({
          symbol: p.symbol,
          interval: p.interval,
          bars: 0,
          error: error instanceof Error ? error.message : String(error),
        })
      }
      bump((n) => n + 1)
    }

    // What the engine does when the reader scrolls past the left edge: ask the
    // same feed for the window before what is already held. `before` is what
    // marks a request as a page rather than a fresh load.
    state.pageOlder = async () => {
      const p = latest.current
      const held = state.loadedFrom ?? Math.floor(Date.now() / 1000)
      try {
        await p.feed.getBars({
          symbol: p.symbol,
          exchange: p.exchange,
          interval: p.interval,
          from: held - 86_400,
          to: held - 0.000001,
          before: held,
          countBack: 300,
        } as never)
      } catch {
        // The engine reports a failed page in its own status row.
      }
      bump((n) => n + 1)
    }

    const widget = useRef<ReturnType<typeof makeWidget> | null>(null)
    if (widget.current === null) {
      widget.current = makeWidget(state, () => load.current())
    }

    // Mount: hand the host its handle, then fetch, in that order, so a host
    // that creates overlay series in `onReady` has them before any data lands.
    useEffect(() => {
      const instance = widget.current
      latest.current.onReady?.(instance as never)
      void load.current()
      return () => {
        if (instance) instance.isDestroyed = true
        latest.current.onReady?.(null)
      }
    }, [])

    // The real widget refetches when either of these changes. The mount effect
    // above already did the first load, so this one skips its own first run.
    const first = useRef(true)
    // biome-ignore lint/correctness/useExhaustiveDependencies: the identity of the request is exactly these three
    useEffect(() => {
      if (first.current) {
        first.current = false
        return
      }
      void load.current()
    }, [props.symbol, props.exchange, props.interval])

    return (
      <div
        data-testid="openalgo-chart"
        data-symbol={props.symbol}
        data-interval={props.interval}
        data-chart-type={props.chartType}
        data-persist-key={props.persistKey}
        data-topbar={String(props.topbar ?? true)}
      />
    )
  }
}
