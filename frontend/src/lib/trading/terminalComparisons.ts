import {
  type Bar,
  type BarsRequest,
  CandleBuilder,
  type Chart,
  type ComparisonController,
  type ComparisonHandle,
  comparisonController,
  type DataFeed,
  DataLoadingController,
  type DataLoadingSnapshot,
  type DataLoadingStatus,
  isValidTimezone,
  type LtpEvent,
  type OpenAlgoWsConfig,
  OpenAlgoWsFeed,
  PaneLegend,
  type PriceScale,
  type PriceScaleMode,
  tryResolveInterval,
} from 'openalgo-charts'
import type { WorkspaceComparison } from 'openalgo-charts/workspace'
import { nextComparisonColor } from './comparisonColors'
import {
  type ComparisonScale,
  comparisonReading,
  comparisonScaleOf,
  isComparisonScale,
  rebasingMode,
  SharedPriceAxis,
  type StoredComparisonMode,
  storedComparisonMode,
} from './comparisonScale'
import { intervalSeconds } from './intervals'
import { replayTiming } from './replayTiming'

export interface ComparisonContext {
  interval: string
  from?: number
  to?: number
  timezone: string
}

export interface TerminalComparisonRow extends WorkspaceComparison {
  status: DataLoadingStatus
  error: string | null
  close: number | null
  /** Percent change of `close` from the comparison's bar before, or null. */
  change: number | null
}

interface Options {
  feed: DataFeed
  ws: OpenAlgoWsConfig
  onChange?: () => void
  now?: () => number
  /** How a comparison's price reads in its legend row. Two decimals by default. */
  formatPrice?: (value: number) => string
}

/** Where a comparison's legend row is addressed: `cmp:<id>`, then `::hide` or `::close`. */
const LEGEND_PREFIX = 'cmp:'
const UP = '#26a69a'
const DOWN = '#ef5350'

interface Entry {
  spec: WorkspaceComparison
  data: DataLoadingController
  handle: ComparisonHandle
  legend: PaneLegend | null
  builder: CandleBuilder | null
  off: () => void
  work: Promise<void>
  subscribed: boolean
  shown: readonly Bar[] | null
  status: DataLoadingStatus
  error: string | null
  streamError: string | null
}

function supportedInterval(context: ComparisonContext): boolean {
  if (tryResolveInterval(context.interval)) return true
  try {
    // Broker calendar aliases stay intact on history requests. This only validates
    // the token; comparison ticks never use a made-up fixed month length.
    replayTiming(context.interval, context.timezone)
    return true
  } catch {
    return false
  }
}

/** Report the first failure after attempting every independent release. */
function cleanup(actions: (() => void)[]): void {
  let failed = false
  let failure: unknown
  for (const action of actions) {
    try {
      action()
    } catch (error) {
      if (!failed) {
        failed = true
        failure = error
      }
    }
  }
  if (failed) throw failure
}

/** One terminal owns its comparison history, chart generation and separate stream. */
export class TerminalComparisons {
  private readonly options: Options
  private readonly history: DataFeed
  private definitions: WorkspaceComparison[] = []
  private selectedMode: ComparisonScale = 'percent'
  private basePriceMode: PriceScaleMode | null = null
  private chart: Chart | null = null
  private context: ComparisonContext | null = null
  private controller: ComparisonController | null = null
  private entries = new Map<string, Entry>()
  private socket: OpenAlgoWsFeed | null = null
  private socketOff: (() => void)[] = []
  private chartOff: (() => void) | null = null
  private axis: SharedPriceAxis | null = null
  /** The bar time the legend rows read, or null for the latest bar. */
  private readoutTime: number | null = null
  private visible = true
  private destroyed = false

  constructor(options: Options) {
    this.options = options
    // The helper alone owns streaming, even when its supplied history feed is live.
    this.history = {
      getBars: (request) => options.feed.getBars(request),
      ...(options.feed.getCachedBars
        ? { getCachedBars: (request: BarsRequest) => options.feed.getCachedBars!(request) }
        : {}),
    }
  }

  /** The mode as a saved chart records it: only `price` or `percent` fit there. */
  get mode(): StoredComparisonMode {
    return storedComparisonMode(this.selectedMode)
  }

  /** The scale the trader chose, of the four. */
  get scale(): ComparisonScale {
    return this.selectedMode
  }

  specs(): WorkspaceComparison[] {
    return this.definitions.map((item) => ({ ...item }))
  }

  /** Capture the user's scale mode without briefly repainting an unrebased chart. */
  captureBaseState(): ReturnType<Chart['getState']> {
    this.assertAlive()
    if (!this.chart) throw new Error('Comparison chart is not available')
    this.rememberBaseMode()
    const state = this.chart.getState()
    const primary = state.panes?.[0]?.priceScale
    const applied = rebasingMode(this.selectedMode)
    if (
      primary &&
      this.entries.size &&
      applied !== null &&
      primary.mode === applied &&
      this.basePriceMode !== null
    ) {
      primary.mode = this.basePriceMode
    }
    return state
  }

  rows(time?: number): TerminalComparisonRow[] {
    const { at, before } = this.readoutTimes(time)
    return this.definitions.map((spec) => {
      const entry = this.entries.get(spec.id)
      const reading =
        spec.visible && entry && at !== undefined
          ? comparisonReading(
              entry.handle.barAt(at)?.close ?? null,
              before === undefined ? null : (entry.handle.barAt(before)?.close ?? null)
            )
          : null
      return {
        ...spec,
        status:
          entry?.streamError && entry.status === 'ready' ? 'stale' : (entry?.status ?? 'idle'),
        error: entry?.error ?? entry?.streamError ?? null,
        close: reading?.close ?? null,
        change: reading?.change ?? null,
      }
    })
  }

  /**
   * The bar the legend rows read: the one under the crosshair, else the latest.
   * Called by the terminal every time its own readout moves, so the two agree.
   */
  setReadout(time: number | null): void {
    if (this.readoutTime === time) return
    this.readoutTime = time
    this.refreshLegends()
  }

  /** The primary bar time a reading is for, and the bar time before it. */
  private readoutTimes(time?: number): { at?: number; before?: number } {
    const bars = this.chart?.primaryBars() ?? []
    const wanted = time ?? this.readoutTime ?? bars.at(-1)?.time
    if (wanted === undefined) return {}
    let lo = 0
    let hi = bars.length - 1
    while (lo <= hi) {
      const mid = (lo + hi) >>> 1
      if (bars[mid].time === wanted) return { at: wanted, before: bars[mid - 1]?.time }
      if (bars[mid].time < wanted) lo = mid + 1
      else hi = mid - 1
    }
    return { at: wanted }
  }

  async bind(chart: Chart, context: ComparisonContext): Promise<void> {
    this.assertAlive()
    if (
      !supportedInterval(context) ||
      !isValidTimezone(context.timezone) ||
      (context.from !== undefined && !Number.isFinite(context.from)) ||
      (context.to !== undefined && !Number.isFinite(context.to)) ||
      (context.from !== undefined && context.to !== undefined && context.from > context.to)
    ) {
      throw new Error('Invalid comparison history context')
    }
    this.detach()
    this.chart = chart
    this.context = { ...context }
    this.controller = comparisonController(chart, { baseline: 'common', mode: this.engineMode() })
    this.controller.setBaseline('common')
    this.controller.setMode(this.engineMode())
    const offDestroy = chart.on('destroy', () => this.detach())
    const offClick = chart.on('click', (event) => this.legendAction(event.id))
    this.chartOff = () => {
      offDestroy()
      offClick()
    }
    this.syncAxis()
    await Promise.all(this.definitions.map((spec) => this.attach(spec)))
  }

  /** Retain portable definitions while releasing everything owned by this chart. */
  detach(): void {
    this.rememberBaseMode()
    const scale = this.chart?.panes()[0]?.priceScale
    const off = this.chartOff
    const entries = [...this.entries.values()]
    const chart = this.chart
    const axis = this.axis
    this.chartOff = null
    this.axis = null
    try {
      cleanup([
        () => off?.(),
        () => {
          if (axis && chart) this.dropAxis(chart, axis)
        },
        ...entries.map((entry) => () => this.release(entry, scale)),
        () => this.closeSocket(),
      ])
    } finally {
      this.chart = null
      this.context = null
      this.controller = null
      this.entries.clear()
      this.basePriceMode = null
    }
  }

  /**
   * Replace every comparison and the scale they are read on.
   *
   * `mode` is what a saved chart recorded; `scale` the finer choice kept beside
   * it, when there is one. Without it a saved `price` is Own scale, which is
   * what it drew before the other choices existed.
   */
  async replace(
    specs: readonly WorkspaceComparison[],
    mode: StoredComparisonMode,
    scale?: ComparisonScale
  ): Promise<void> {
    this.assertAlive()
    const incoming = this.validate(specs)
    if (mode !== 'price' && mode !== 'percent') throw new Error('Invalid comparison mode')
    if (scale !== undefined && !isComparisonScale(scale)) throw new Error('Invalid comparison mode')
    for (const entry of [...this.entries.values()]) {
      const next = incoming.find((item) => item.id === entry.spec.id)
      if (!next || next.symbol !== entry.spec.symbol || next.exchange !== entry.spec.exchange)
        this.release(entry)
      else {
        entry.spec = next
        entry.handle.series.applyOptions({
          visible: next.visible,
          ...(next.color ? { color: next.color } : {}),
        })
        entry.legend?.setOptions({ hidden: !next.visible, color: next.color })
      }
    }
    this.definitions = incoming
    this.applyMode(comparisonScaleOf(mode, scale))
    this.notify()
    if (this.chart)
      await Promise.all(
        incoming.map((spec) => this.entries.get(spec.id)?.work ?? this.attach(spec))
      )
  }

  add(spec: WorkspaceComparison): Promise<void> {
    return this.replace([...this.definitions, spec], this.mode, this.selectedMode)
  }

  /**
   * Load a comparison again from scratch: for one whose history failed, once the
   * broker or the connection has had a moment to recover.
   */
  async retry(id: string): Promise<void> {
    this.assertAlive()
    const spec = this.definitions.find((item) => item.id === id)
    if (!spec) return
    const entry = this.entries.get(id)
    if (entry) this.release(entry)
    this.notify()
    if (this.chart) await this.attach(spec)
  }

  remove(id: string): void {
    if (this.destroyed) return
    const entry = this.entries.get(id)
    if (entry) this.release(entry)
    this.definitions = this.definitions.filter((spec) => spec.id !== id)
    this.notify()
  }

  setVisible(id: string, visible: boolean): void {
    this.assertAlive()
    const spec = this.definitions.find((item) => item.id === id)
    if (!spec || spec.visible === visible) return
    spec.visible = visible
    const entry = this.entries.get(id)
    entry?.handle.series.applyOptions({ visible })
    entry?.legend?.setOptions({ hidden: !visible })
    this.notify()
    this.refreshLegends()
  }

  setMode(mode: ComparisonScale): void {
    this.assertAlive()
    if (!isComparisonScale(mode)) throw new Error('Invalid comparison mode')
    if (mode === this.selectedMode) return
    this.applyMode(mode)
    this.notify()
  }

  setVisibleHost(visible: boolean): void {
    this.visible = visible
    for (const entry of this.entries.values()) entry.data.setVisible(visible)
  }

  async refresh(): Promise<void> {
    if (this.destroyed) return
    await Promise.all(
      [...this.entries.values()].map(async (entry) => {
        await entry.data.refresh()
        if (this.current(entry)) this.subscribe(entry)
      })
    )
  }

  destroy(): void {
    if (this.destroyed) return
    this.destroyed = true
    try {
      this.detach()
    } finally {
      this.definitions = []
    }
  }

  private attach(spec: WorkspaceComparison): Promise<void> {
    const context = this.context
    if (!this.controller || !context) return Promise.resolve()
    this.rememberBaseMode()
    const data = new DataLoadingController(this.history, {
      now: this.options.now,
      timeoutMs: 30_000,
      maxBars: 100_000,
      pollIntervalMs: 30_000,
      refreshOnBarClose: true,
      refreshOnGap: true,
      refreshWindowBars: 5,
    })
    data.setVisible(this.visible)
    const handle = this.controller.add({
      symbol: spec.symbol,
      bars: [],
      color: spec.color,
      style: { visible: spec.visible, lineWidth: 1.5 },
    })
    const entry: Entry = {
      spec,
      data,
      handle,
      legend: this.addLegend(spec),
      builder: null,
      off: () => {},
      work: Promise.resolve(),
      subscribed: false,
      shown: null,
      status: 'idle',
      error: null,
      streamError: null,
    }
    this.entries.set(spec.id, entry)
    entry.off = data.subscribe((snapshot) => this.snapshot(entry, snapshot))
    const work = (async () => {
      await data.load({
        symbol: spec.symbol,
        exchange: spec.exchange,
        interval: context.interval,
        from: context.from,
        to: context.to,
      })
      if (!this.current(entry)) return
      this.subscribe(entry)
      const state = data.getState()
      if (state.status !== 'ready')
        throw state.error ?? new Error(`${spec.symbol}: No comparison history for this interval`)
    })()
    entry.work = work
    const settled = () => {
      if (entry.work === work) entry.work = Promise.resolve()
    }
    void work.then(settled, settled)
    return work
  }

  private snapshot(entry: Entry, snapshot: DataLoadingSnapshot): void {
    if (!this.current(entry)) return
    if (snapshot.bars !== entry.shown) {
      entry.shown = snapshot.bars
      entry.handle.setBars(snapshot.bars)
      this.refreshLegend(entry)
      if (snapshot.reason !== 'live') {
        const seconds = this.context && intervalSeconds(this.context.interval)
        const last = snapshot.bars.at(-1)
        entry.builder =
          seconds && last
            ? new CandleBuilder({
                intervalSec: seconds,
                volumeMode: 'ltq-sum',
                sessionAnchorSec: last.time,
                lateTickPolicy: 'dropOlderThanPrevBar',
              })
            : null
        if (last) entry.builder?.seed(last)
      }
    }
    const error =
      snapshot.error?.message ??
      (snapshot.status === 'empty' ? 'No comparison history for this interval' : null)
    if (entry.status !== snapshot.status || entry.error !== error) {
      entry.status = snapshot.status
      entry.error = error
      this.notify()
    }
  }

  private subscribe(entry: Entry): void {
    if (!this.current(entry) || entry.subscribed || !entry.builder) return
    const socket = this.ensureSocket()
    entry.subscribed = true
    socket.subscribe('LTP', entry.spec.symbol, entry.spec.exchange)
  }

  private ensureSocket(): OpenAlgoWsFeed {
    if (this.socket) return this.socket
    const socket = new OpenAlgoWsFeed(this.options.ws)
    this.socket = socket
    this.socketOff = [
      socket.onLtp((event) => this.tick(event)),
      socket.onControl((message) => {
        if (message.code === 'STREAM_RESYNC') void this.refresh()
      }),
      socket.onState((state) => {
        if (state === 'connecting') return
        const error =
          state === 'open' ? null : 'Comparison stream disconnected; history polling continues'
        let changed = false
        for (const entry of this.entries.values()) {
          if (entry.streamError !== error) {
            entry.streamError = error
            changed = true
          }
        }
        if (changed) this.notify()
      }),
    ]
    socket.connect()
    return socket
  }

  private tick(event: LtpEvent): void {
    if (this.destroyed || !this.chart) return
    if (!Number.isFinite(event.ltp) || event.ltp <= 0) return
    const time =
      Number.isFinite(event.timeSec) && event.timeSec > 0
        ? event.timeSec
        : (this.options.now?.() ?? Math.floor(Date.now() / 1000))
    for (const entry of this.entries.values()) {
      if (event.symbol !== entry.spec.symbol || event.exchange !== entry.spec.exchange) continue
      const update = entry.builder?.onTick({ time, price: event.ltp, ltq: event.ltq })
      if (update) entry.data.pushBar(update.bar, { provisional: update.provisional })
    }
  }

  private release(entry: Entry, scale = this.chart?.panes()[0]?.priceScale): void {
    this.rememberBaseMode(scale)
    const applied = rebasingMode(this.selectedMode)
    const restoreMode =
      this.entries.size === 1 && applied !== null && scale?.options.mode === applied
        ? this.basePriceMode
        : null
    this.entries.delete(entry.spec.id)
    const off = entry.off
    const subscribed = entry.subscribed
    const legend = entry.legend
    const chart = this.chart
    entry.off = () => {}
    entry.subscribed = false
    entry.legend = null
    cleanup([
      off,
      () => entry.data.destroy(),
      () => entry.handle.remove(),
      () => {
        if (!legend || !chart) return
        try {
          chart.removePrimitive(legend)
        } catch {
          // A chart already torn down has taken its legend rows with it.
        }
      },
      () => {
        if (restoreMode !== null && scale?.options.mode !== restoreMode)
          scale?.setOptions({ mode: restoreMode })
      },
      () => {
        if (subscribed) this.socket?.unsubscribe('LTP', entry.spec.symbol, entry.spec.exchange)
      },
      () => {
        if (![...this.entries.values()].some((item) => item.subscribed)) this.closeSocket()
      },
    ])
  }

  private closeSocket(): void {
    const off = this.socketOff.splice(0)
    const socket = this.socket
    this.socket = null
    cleanup([...off, () => socket?.close()])
  }

  private current(entry: Entry): boolean {
    return !this.destroyed && this.entries.get(entry.spec.id) === entry
  }
  private engineMode() {
    return rebasingMode(this.selectedMode) ?? ('none' as const)
  }
  private rememberBaseMode(
    scale: PriceScale | undefined = this.chart?.panes()[0]?.priceScale
  ): void {
    const applied = rebasingMode(this.selectedMode)
    if (scale && (!this.entries.size || applied === null || scale.options.mode !== applied)) {
      this.basePriceMode = scale.options.mode
    }
  }
  private applyMode(mode: ComparisonScale): void {
    this.rememberBaseMode()
    const scale = this.chart?.panes()[0]?.priceScale
    const applied = rebasingMode(this.selectedMode)
    const restoreMode =
      this.entries.size && applied !== null && scale?.options.mode === applied
        ? this.basePriceMode
        : null
    // The shared axis comes off before the engine changes mode, so the scales it
    // matched to the price axis are plain again when the engine takes them.
    if (this.axis && this.chart && mode !== 'price') {
      this.dropAxis(this.chart, this.axis)
      this.axis = null
    }
    this.selectedMode = mode
    this.controller?.setMode(this.engineMode())
    if (rebasingMode(mode) === null && restoreMode !== null && scale?.options.mode !== restoreMode) {
      scale?.setOptions({ mode: restoreMode })
    }
    this.syncAxis()
  }

  /** Put the shared price axis on the chart while Price is chosen, and only then. */
  private syncAxis(): void {
    const chart = this.chart
    if (!chart || this.selectedMode !== 'price' || this.axis) return
    const axis = new SharedPriceAxis(
      chart,
      () => chart.panes()[chart.primaryPaneIndex()]?.priceScale ?? null,
      () =>
        [...this.entries.values()].map((entry) => ({
          visible: entry.spec.visible,
          scale: entry.handle.priceScale(),
          closeAt: (time: number) => entry.handle.barAt(time)?.close ?? null,
        }))
    )
    this.axis = axis
    chart.addPrimitive(axis, chart.primaryPaneIndex())
  }

  private dropAxis(chart: Chart, axis: SharedPriceAxis): void {
    try {
      axis.release()
      chart.removePrimitive(axis)
    } catch {
      // A chart already torn down has nothing left to put back.
    }
  }

  /**
   * A row in the chart's own legend stack: the symbol in its line colour, its
   * close and change, an eye to hide the line and a cross to remove it. Added as
   * the engine's own legend primitive, so it stacks with the study rows and is
   * painted into a saved image like them.
   */
  private addLegend(spec: WorkspaceComparison): PaneLegend | null {
    const chart = this.chart
    if (!chart) return null
    try {
      const legend = new PaneLegend({
        id: `${LEGEND_PREFIX}${spec.id}`,
        title: spec.symbol,
        params: spec.exchange,
        color: spec.color,
        actions: ['hide', 'close'],
        hidden: !spec.visible,
      })
      chart.addPrimitive(legend, chart.primaryPaneIndex())
      return legend
    } catch {
      // The line still draws; only its legend row is missing.
      return null
    }
  }

  private legendAction(id: string | null): void {
    if (!id?.startsWith(LEGEND_PREFIX) || this.destroyed) return
    const cut = id.lastIndexOf('::')
    if (cut < 0) return
    const specId = id.slice(LEGEND_PREFIX.length, cut)
    const action = id.slice(cut + 2)
    const spec = this.definitions.find((item) => item.id === specId)
    if (!spec) return
    if (action === 'hide') this.setVisible(specId, !spec.visible)
    else if (action === 'close') this.remove(specId)
  }

  private refreshLegends(): void {
    for (const entry of this.entries.values()) this.refreshLegend(entry)
  }

  private refreshLegend(entry: Entry): void {
    const legend = entry.legend
    if (!legend) return
    const row = this.rows().find((item) => item.id === entry.spec.id)
    if (!row || row.close === null) {
      legend.setValues([])
      return
    }
    const format = this.options.formatPrice ?? ((value: number) => value.toFixed(2))
    legend.setValues([
      { text: format(row.close), color: entry.spec.color, field: 'ohlc' },
      ...(row.change === null
        ? []
        : [
            {
              text: `${row.change >= 0 ? '+' : ''}${row.change.toFixed(2)}%`,
              color: row.change >= 0 ? UP : DOWN,
              field: 'change' as const,
            },
          ]),
    ])
  }
  private assertAlive(): void {
    if (this.destroyed) throw new Error('Comparisons are no longer available')
  }
  private notify(): void {
    if (!this.destroyed) this.options.onChange?.()
  }

  private validate(specs: readonly WorkspaceComparison[]): WorkspaceComparison[] {
    if (specs.length > 32) throw new Error('A chart supports at most 32 comparisons')
    const ids = new Set<string>(),
      sources = new Set<string>(),
      // Colours already spoken for in this batch, so two comparisons added in
      // one `replace` cannot be handed the same one.
      colours = new Set<string>()
    return specs.map((spec) => {
      if (
        ![spec.id, spec.symbol, spec.exchange].every(
          (value) => typeof value === 'string' && value.trim().length > 0
        ) ||
        typeof spec.visible !== 'boolean' ||
        (spec.color !== undefined && typeof spec.color !== 'string')
      ) {
        throw new Error('Invalid comparison definition')
      }
      const source = JSON.stringify([spec.symbol, spec.exchange])
      if (ids.has(spec.id) || sources.has(source))
        throw new Error('Duplicate comparison source or ID')
      ids.add(spec.id)
      sources.add(source)
      // Every comparison leaves here with a colour, whether it arrived with
      // one or not. This is the only path into `definitions`, so it is the one
      // place that can promise it: a spec restored from a workspace saved
      // before comparisons had colours, or written by hand, would otherwise
      // reach the chart uncoloured and be painted the engine's default line
      // blue, which is the colour a comparison must never be.
      const colour =
        typeof spec.color === 'string' && spec.color.trim()
          ? spec.color
          : nextComparisonColor(colours)
      colours.add(colour)
      return {
        id: spec.id,
        symbol: spec.symbol,
        exchange: spec.exchange,
        visible: spec.visible,
        color: colour,
      }
    })
  }
}
