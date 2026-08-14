/**
 * Framework-agnostic controller for the charting terminal.
 *
 * Owns the openalgo-charts instance, the OpenAlgo data / WS / trade feeds, and
 * all imperative trading state (order lines, position marker, live candle
 * builder, tick handling). The React page (`Trading.tsx`) drives it through
 * plain methods and receives updates through the callback bag — so the canvas
 * chart, the 60fps tick path, and the WebSocket lifecycle stay off React's
 * render path, and unmount is a single `destroy()`.
 *
 * Ported from the standalone /trading page; the trading flow (history → live
 * candles → on-chart order lines, right-click to place, drag to modify, ✕ to
 * cancel, real-time order stream, REST fallback) is unchanged.
 */
import {
  type Bar,
  BuySellButtons,
  CandleBuilder,
  compactVolume,
  createChart,
  type IPrimitive,
  LogoWatermark,
  type LtpEvent,
  type MarketDepth,
  OpenAlgoDataFeed,
  OpenAlgoTradeFeed,
  OpenAlgoWsFeed,
  type PriceLine,
  type SeriesApi,
  type SeriesStyle,
  type SeriesType,
} from 'openalgo-charts'
import type { DrawingController } from 'openalgo-charts/draw'
import { runTransform } from 'openalgo-charts/transform'

type ChartInstance = ReturnType<typeof createChart>
type BuySellButtonsInstance = InstanceType<typeof BuySellButtons>
type TradeFeedInstance = InstanceType<typeof OpenAlgoTradeFeed>
type DrawingControllerInstance = InstanceType<typeof DrawingController>
type DrawingJson = ReturnType<DrawingControllerInstance['toJSON']>[number]

/** What the toolbar needs to enable/disable its drawing buttons. */
export interface DrawStats {
  count: number
  canUndo: boolean
  canRedo: boolean
  hasSelection: boolean
  magnet: boolean
  tool: string | null
  /**
   * Tool id -> keyboard chord, from the draw tier. Empty until the tier has
   * loaded; the rail simply renders no chord until then, rather than the rail
   * having to import the tier and undo its lazy loading.
   */
  shortcuts: Record<string, string>
}

import type { AppMode, ThemeMode } from '@/stores/themeStore'
import { buildChartTheme, isLightTheme, resolveCssColor, volumeColor } from './chartTheme'
import { CHART_TYPES } from './chartTypes'
import { fmtPrice, money, priceDp, snapTick, tickSize } from './format'
import {
  type IntervalData,
  type IntervalGroup,
  intervalGroups,
  intervalSeconds,
  lookbackDays,
  pickInterval,
} from './intervals'
import {
  buildChartLegend,
  DN,
  type LegendRun,
  LTP_NEUTRAL,
  legendHtml,
  legendToneStyle,
  lotInfoText,
  UP,
} from './legend'

export type OrderSide = 'BUY' | 'SELL'
export type OrderType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
export type ToastKind = 'ok' | 'err' | ''

/** Broker order shape stored per on-chart line (subset shared by book + WS). */
interface LineOrder {
  id: string
  side: OrderSide
  type: OrderType
  qty: number
  price: number
  triggerPrice?: number
  status: string
}

interface OrderLineRec {
  line: PriceLine
  order: LineOrder
  dragFrom?: number | null
}

interface PositionState {
  net: number
  avg: number
  product: string
}

/** Everything the toolbar needs to render for the loaded instrument. */
export interface SymbolView {
  symbol: string
  exchange: string
  name: string
  /** FnO lot-based entry (qty input means lots, × lotsize). */
  lots: boolean
  lotsize: number
  /** Instrument tick size; drives all price snapping/formatting (not shown in UI). */
  tick: number
  freezeQty: number
  quoteOnly: boolean
  productOptions: string[]
  product: string
}

export interface SearchRow {
  symbol: string
  exchange: string
  name?: string
  lotsize?: number | string
  [k: string]: unknown
}

/** A right-click order option for the context menu. */
export interface CtxItem {
  side: OrderSide
  type: OrderType
  label: string
  enabled: boolean
}

export interface TerminalCallbacks {
  onReady(info: { intervalGroups: IntervalGroup[]; interval: string; chartType: string }): void
  onToast(msg: string, kind: ToastKind): void
  onWsState(state: string): void
  onSymbolLoaded(view: SymbolView): void
  onLtp(ltp: number): void
  /** Drawing toolbar state changed (tool armed, shape added/removed, undo...). */
  onDrawChange?(stats: DrawStats): void
  /** The live indicator list changed. */
  onIndicatorsChange?(list: { id: string; name: string }[]): void
  /**
   * The gear on an indicator's on-chart legend was clicked. The engine is
   * canvas-only and ships no DOM, so the form is ours to render.
   */
  onIndicatorSettings?(req: IndicatorSettingsRequest): void
  /** A drawing was selected (or deselected), for the style popover. */
  onDrawSelect?(sel: DrawSelection | null): void
  /**
   * A text-bearing drawing needs its content. The engine renders `style.text`
   * but has no DOM to collect it with, so the host prompts.
   */
  onDrawTextEdit?(req: { id: string; tool: string; text: string }): void
}

/** Tools whose content is typed rather than dragged. */
const TEXT_TOOLS = new Set(['text', 'callout', 'price-label'])

/** Everything needed to generate an indicator settings form. */
export interface IndicatorSettingsRequest {
  instanceId: string
  name: string
  /** The descriptor's own value inputs — the "Inputs" tab. */
  inputs: IndicatorField[]
  /** Generated per-plot colour / width / dash inputs — the "Style" tab. */
  styleInputs: IndicatorField[]
  values: Record<string, unknown>
}

export interface IndicatorField {
  key: string
  type: string
  label: string
  /** Plot title the style inputs belong to, so a form can group them per plot. */
  group?: string
  options?: { label: string; value: unknown }[]
  min?: number
  max?: number
  step?: number
}

/** The selected drawing's editable style. */
export interface DrawSelection {
  id: string
  tool: string
  /** Content is typed, so the style bar offers an edit button. */
  hasText: boolean
  color: string
  lineWidth: number
  lineStyle: string
  locked: boolean
}

/**
 * Everything a text-bearing drawing's settings dialog edits. The engine renders
 * all of it already (`TEXT`'s style keys); it ships no DOM, so the form is the
 * host's and needs the current values to open populated rather than blank.
 */
export interface DrawTextStyle {
  text: string
  color: string
  fontSize: number
  bold: boolean
  italic: boolean
  background: boolean
  backgroundColor: string
  border: boolean
  borderColor: string
  wrap: boolean
}

export interface TerminalOptions {
  apiKey: string
  wsUrl: string
  container: HTMLElement
  legendEl: HTMLElement
  /** localStorage namespace so each grid pane restores independently (default 'oa-trading'). */
  storageKey?: string
  /** Reads the app's current theme so the canvas chrome tracks it. */
  getTheme: () => { mode: ThemeMode; appMode: AppMode }
  callbacks: TerminalCallbacks
}

const DERIVATIVE_EXCHANGES = new Set(['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCO', 'NCDEX'])

/**
 * Products a segment accepts. Derivative segments are NRML/MIS and cash equity
 * is CNC/MIS; the exchange alone decides, never the contract's lot size.
 */
export function productOptionsFor(exchange: string): string[] {
  return DERIVATIVE_EXCHANGES.has(exchange) ? ['MIS', 'NRML'] : ['MIS', 'CNC']
}

/** Whether quantity on this segment is entered in lots rather than units. */
export function usesLots(exchange: string): boolean {
  return DERIVATIVE_EXCHANGES.has(exchange)
}
const QUOTE_ONLY = new Set(['NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX'])
const STRATEGY = 'chart-trading'
const VISIBLE_BARS = 120

/**
 * Where the exported PNG paints the OHLC readout, in CSS px. These mirror the
 * DOM overlay's own placement in `ChartPane` (`left-3 top-1.5`, a 12px line and
 * a 10px line under it), so the saved image puts the text where the screen
 * does rather than inventing a second layout.
 */
const LEGEND_X = 12
const LEGEND_Y = 8
const LEGEND_SUB_Y = 25
/** Space between two legend runs, in CSS px (the DOM renderer joins with ' '). */
const LEGEND_GAP = 6

const nowSec = () => Math.floor(Date.now() / 1000)

/**
 * Resolve once the chart has repainted.
 *
 * The chart schedules its repaint on `requestAnimationFrame`, and rAF callbacks
 * run in registration order, so a frame requested after `removePrimitive()`
 * runs after the repaint that call triggered. Two frames are waited on because
 * an invalidation raised during a paint defers to the next one. The timeout is
 * the escape hatch for a background tab, where rAF may never fire at all.
 */
function nextPaint(): Promise<void> {
  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      resolve()
    }
    const timer = setTimeout(finish, 250)
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        clearTimeout(timer)
        finish()
      })
    )
  })
}

export class TradingTerminal {
  private readonly apiKey: string
  private readonly wsUrl: string
  private readonly container: HTMLElement
  private readonly legendEl: HTMLElement
  private readonly getTheme: () => { mode: ThemeMode; appMode: AppMode }
  private readonly cb: TerminalCallbacks
  private readonly sk: string

  private chart: ChartInstance | null = null
  private price: SeriesApi | null = null
  private volume: SeriesApi | null = null

  /* Drawing + indicator state. buildChart() throws the chart away on every
     interval / chart-type / theme change, so both round-trip through plain
     data here and are re-applied to the new chart. */
  private draw: DrawingControllerInstance | null = null
  private drawJson: DrawingJson[] = []
  private drawTool: string | null = null
  private drawMagnet = false
  /** True once a drawing control has been touched — gates the lazy tier fetch. */
  private drawEnabled = false
  private activeIndicators: { indicatorId: string; settings: Record<string, unknown> }[] = []
  private indicatorsLoaded = false
  /** Guards syncIndicators while applyIndicators is mid-flight. */
  private applyingIndicators = false
  /** History paging: in-flight guard, and whether the broker ran out. */
  private loadingOlder = false
  private noMoreHistory = false
  private volumeOn = true
  private gridV = true
  private gridH = true
  private drawShortcuts: Record<string, string> = {}
  private matchShortcut:
    | ((e: {
        key: string
        altKey?: boolean
        ctrlKey?: boolean
        metaKey?: boolean
        shiftKey?: boolean
      }) => string | null)
    | null = null
  private ltpLine: PriceLine | null = null
  private posLine: PriceLine | null = null
  private tradeBtns: BuySellButtonsInstance | null = null
  /** The bar the OHLC readout is currently showing; replayed into the export. */
  private legendBar: Bar | null = null
  /**
   * Canvas primitives that are interaction affordances rather than chart
   * content. They are detached for the duration of a screenshot and re-attached
   * straight after, so a saved image carries nothing that invites a click.
   *
   * Registering here is how an overlay opts out: the capture path matches on
   * nothing, so a future overlay only has to add itself to be left out too.
   */
  private readonly screenshotExcluded: { primitive: IPrimitive; paneIndex: number }[] = []

  private ws: InstanceType<typeof OpenAlgoWsFeed> | null = null
  private rest: InstanceType<typeof OpenAlgoDataFeed> | null = null
  private trade: TradeFeedInstance | null = null
  private builder: CandleBuilder | null = null
  private offLtp: (() => void) | null = null
  private offDepth: (() => void) | null = null
  private depthActive = false

  private rawBars: Bar[] = []
  private shownCount = 0
  private liveBucket: number | null = null
  private lastLtp: number | null = null
  private prevClose: number | null = null
  private sym: SymbolView | null = null
  private position: PositionState | null = null
  private readonly orderLines = new Map<string, OrderLineRec>()

  private interval = '5m'
  private ctype = 'candlestick'
  private product = 'MIS'
  private qty = 1

  private bookTimer: ReturnType<typeof setInterval> | null = null
  private reconcileTimer: ReturnType<typeof setTimeout> | null = null
  private ltpPollTimer: ReturnType<typeof setInterval> | null = null
  private destroyed = false

  constructor(opts: TerminalOptions) {
    this.apiKey = opts.apiKey
    this.wsUrl = opts.wsUrl
    this.container = opts.container
    this.legendEl = opts.legendEl
    this.getTheme = opts.getTheme
    this.cb = opts.callbacks
    this.sk = opts.storageKey || 'oa-trading'
    this.interval = this.lsGet('interval') || '5m'
    this.ctype = this.lsGet('ctype') || 'candlestick'
    this.restoreChartTools()
    if (!CHART_TYPES[this.ctype]) this.ctype = 'candlestick'
  }

  /**
   * Per-pane persisted state. Each grid pane namespaces its localStorage by its
   * `storageKey`, so panes restore their own symbol/interval/chart-type/product
   * independently across layouts and reloads. The primary pane (`…-p0`) also
   * inherits the pre-namespacing global key once, so a single-chart user keeps
   * their last symbol after upgrading. Writes always go to the namespaced key.
   */
  private lsGet(key: string): string | null {
    const v = localStorage.getItem(`${this.sk}-${key}`)
    if (v !== null) return v
    return this.sk.endsWith('-p0') ? localStorage.getItem(`-${key}`) : null
  }
  private lsSet(key: string, val: string): void {
    localStorage.setItem(`${this.sk}-${key}`, val)
  }

  /* ── tick-size / formatting bound to the loaded instrument ────────────── */
  private refPrice(): number {
    return this.lastLtp || (this.rawBars.length ? this.rawBars[this.rawBars.length - 1].close : 0)
  }
  private tick(): number {
    return tickSize(this.sym?.tick, this.refPrice())
  }
  private dp(): number {
    return priceDp(this.sym?.tick, this.refPrice())
  }
  private fmt(n: number): string {
    return fmtPrice(n, this.sym?.tick, this.refPrice())
  }
  private snap(n: number): number {
    return snapTick(n, this.sym?.tick, this.refPrice())
  }

  /* ── OpenAlgo REST gateway (public /api/v1, apikey in body) ───────────── */
  async api<T = { status?: string; message?: string; data?: unknown; mode?: string }>(
    path: string,
    body: Record<string, unknown> = {}
  ): Promise<T> {
    const res = await fetch(`/api/v1/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apikey: this.apiKey, ...body }),
    })
    const j = (await res.json().catch(() => ({}))) as T & { status?: string; message?: string }
    if (!res.ok || j.status === 'error')
      throw new Error(j.message || `${path} failed (${res.status})`)
    return j
  }

  async search(query: string, exchange?: string, limit = 30): Promise<SearchRow[]> {
    try {
      const j = await this.api<{ data?: SearchRow[] }>('search', {
        query,
        ...(exchange ? { exchange } : {}),
      })
      return (j.data || []).slice(0, limit)
    } catch {
      return []
    }
  }

  /* ── trader-facing error text (technical chain stripped; full to console) */
  private cleanError(e: unknown): string {
    console.error('[trading]', e)
    let m = String((e as Error)?.message || e || 'request failed')
    m = m
      .replace(/^openalgo-charts:\s*/i, '')
      .replace(/^\/api\/v1\/[\w/]+\s+failed\s+\(\d+\)(:\s*)?/i, '')
    return m.trim() || 'request failed'
  }
  private toast(msg: string, kind: ToastKind = '') {
    this.cb.onToast(msg, kind)
  }

  private tradeMode(): AppMode {
    return this.getTheme().appMode
  }

  /* ── chart types (transforms bucket volume onto their own element times) */
  private boxOf(): number {
    const c = this.rawBars.length ? this.rawBars[this.rawBars.length - 1].close : 100
    const t = this.tick()
    return Math.max(t, Number((Math.round((c * 0.0015) / t) * t).toFixed(this.dp())))
  }

  private setPriceData() {
    if (!this.price || !this.volume || !this.rawBars.length) return
    const cfg = CHART_TYPES[this.ctype] || CHART_TYPES.candlestick
    if (cfg.transform) {
      const t = runTransform(cfg.transform(this.boxOf()), this.rawBars)
      this.price.setData(t)
      this.volume.setData(this.bucketVolume(t))
      this.shownCount = t.length
    } else {
      this.price.setData(this.rawBars)
      this.volume.setData(
        this.rawBars.map((b) => ({
          time: b.time,
          open: 0,
          high: b.volume || 0,
          low: 0,
          close: b.volume || 0,
        }))
      )
      this.shownCount = this.rawBars.length
    }
  }

  private bucketVolume(tbars: Bar[]): Bar[] {
    const out: Bar[] = []
    let ri = 0
    for (const tb of tbars) {
      let v = 0
      while (ri < this.rawBars.length && this.rawBars[ri].time <= tb.time) {
        v += this.rawBars[ri].volume || 0
        ri++
      }
      out.push({ time: tb.time, open: 0, high: v, low: 0, close: v })
    }
    let rest = 0
    while (ri < this.rawBars.length) {
      rest += this.rawBars[ri].volume || 0
      ri++
    }
    if (out.length && rest) {
      const last = out[out.length - 1]
      last.high += rest
      last.close += rest
    }
    return out
  }

  /* ── legend (imperative; high-frequency, kept off React state) ────────── */
  private setLegend(bar: Bar | null) {
    this.legendBar = bar
    if (!this.sym) {
      this.legendEl.innerHTML = ''
      return
    }
    this.legendEl.innerHTML = legendHtml(this.legendModel(bar))
  }

  /**
   * The readout's content, independent of how it is drawn. The DOM overlay and
   * the PNG export both render this, which is what stops the saved image from
   * quoting different numbers than the screen it was taken from.
   */
  private legendModel(bar: Bar | null): LegendRun[] {
    const sym = this.sym
    if (!sym) return []
    return buildChartLegend({
      symbol: sym.symbol,
      interval: this.interval,
      exchange: sym.exchange,
      lotsize: sym.lots ? sym.lotsize : null,
      bar,
      ltp: this.lastLtp,
      changePct:
        this.lastLtp != null && this.prevClose
          ? ((this.lastLtp - this.prevClose) / this.prevClose) * 100
          : null,
      fmt: (n) => this.fmt(n),
      fmtVolume: compactVolume,
    })
  }

  /* ── order lines / position marker ────────────────────────────────────── */
  private makeOrderLine(o: LineOrder): PriceLine {
    return this.chart!.addPriceLine(
      {
        price: o.triggerPrice ?? o.price,
        color: o.side === 'BUY' ? '#26a69a' : '#ef5350',
        lineWidth: 1,
        dashed: true,
        id: `order:${o.id}`,
        cursor: 'ns-resize',
        extentFromRight: 0.3,
        closeButton: true,
        badge: o.side,
        qty: o.qty,
        leftLabel: o.type,
      },
      0
    )
  }

  private posLabel(): string {
    if (!this.position) return ''
    const mark = this.lastLtp != null ? this.lastLtp : this.position.avg
    const pnl = (mark - this.position.avg) * this.position.net
    return `@ ${this.fmt(this.position.avg)}  ${pnl >= 0 ? '+' : '-'}₹${money(Math.abs(pnl))}`
  }

  private renderPosition(pos: Record<string, unknown> | undefined) {
    if (this.posLine && this.chart) {
      this.chart.removePrimitive(this.posLine)
      this.posLine = null
    }
    this.position = pos
      ? {
          net: Number(pos.quantity),
          avg: Number(pos.average_price),
          product: String(pos.product ?? ''),
        }
      : null
    if (!this.position || !this.chart || this.position.net === 0) {
      this.position = this.position && this.position.net !== 0 ? this.position : null
      return
    }
    this.posLine = this.chart.addPriceLine(
      {
        price: this.position.avg,
        color: this.position.net > 0 ? '#2e7d6b' : '#a14a52',
        lineWidth: 2,
        dashed: false,
        id: 'position',
        extentFromRight: 0.3,
        closeButton: true,
        badge: this.position.net > 0 ? 'LONG' : 'SHORT',
        qty: Math.abs(this.position.net),
        leftLabel: this.posLabel(),
      },
      0
    )
  }

  private async pollBook() {
    if (!this.trade || !this.sym || !this.chart) return
    try {
      const orders = await this.trade.getOrders() // caches modify context
      const seen = new Set<string>()
      for (const o of orders) {
        if (o.status !== 'working' || o.symbol !== this.sym.symbol) continue
        seen.add(o.id)
        const px = o.triggerPrice ?? o.price
        const rec = this.orderLines.get(o.id)
        if (rec) {
          rec.order = o as LineOrder
          rec.line.setPrice(px)
        } else {
          this.orderLines.set(o.id, {
            line: this.makeOrderLine(o as LineOrder),
            order: o as LineOrder,
          })
        }
      }
      for (const [id, rec] of this.orderLines)
        if (!seen.has(id)) {
          this.chart.removePrimitive(rec.line)
          this.orderLines.delete(id)
        }
    } catch {
      /* transient */
    }
    try {
      const j = await this.api<{ data?: Record<string, unknown>[] }>('positionbook')
      this.renderPosition(
        (j.data || []).find(
          (p) =>
            p.symbol === this.sym!.symbol &&
            p.exchange === this.sym!.exchange &&
            Number(p.quantity) !== 0
        )
      )
    } catch {
      /* transient */
    }
  }

  /* real order quantity (lots × lotsize for derivatives) */
  private orderQty(): number {
    const n = Math.max(1, Math.floor(this.qty || 1))
    return this.sym?.lots ? n * this.sym.lotsize : n
  }
  /** Quantity chip text for the inline panel (lots for FnO, else qty). */
  private qtyChip(): string {
    if (!this.sym) return ''
    const n = Math.max(1, Math.floor(this.qty || 1))
    return this.sym.lots ? `${n}L` : String(n)
  }

  private marketPrice(): number | null {
    return this.lastLtp != null
      ? this.lastLtp
      : this.rawBars.length
        ? this.rawBars[this.rawBars.length - 1].close
        : null
  }

  private async placeFromMenu(side: OrderSide, type: OrderType) {
    if (!this.sym || !this.trade) {
      this.toast('search a symbol first')
      return
    }
    if (this.sym.quoteOnly) {
      this.toast(`${this.sym.exchange} is quote-only — trading is not supported`, 'err')
      return
    }
    const qty = this.orderQty()
    if (this.sym.freezeQty > 1 && qty > this.sym.freezeQty) {
      this.toast(`qty ${qty} exceeds the freeze limit ${this.sym.freezeQty} — reduce lots`, 'err')
      return
    }
    const px = type === 'MARKET' ? 0 : this.snap(this.ctxPrice)
    const m = this.marketPrice()
    if (m != null && (type === 'SL' || type === 'SL-M') && (side === 'BUY' ? px <= m : px >= m)) {
      this.toast(
        `${side} stop must be ${side === 'BUY' ? 'above' : 'below'} LTP ${this.fmt(m)}`,
        'err'
      )
      return
    }
    const lotTxt = this.sym.lots ? `${qty / this.sym.lotsize}L (${qty})` : qty
    const summary = `${side} ${type} ${lotTxt} ${this.sym.symbol}${type === 'MARKET' ? '' : ` @ ${this.fmt(px)}`} · ${this.product}`
    try {
      const r = await this.trade.place({
        symbol: this.sym.symbol,
        exchange: this.sym.exchange,
        side,
        type,
        qty,
        product: this.product as 'CNC' | 'NRML' | 'MIS',
        price: type === 'MARKET' ? undefined : px,
        triggerPrice: type === 'SL' || type === 'SL-M' ? px : undefined,
        mode: this.tradeMode(),
      })
      this.toast(`placed ${summary} (id ${r.orderId})`, 'ok')
      this.pollBook()
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  async exitPosition() {
    if (!this.trade || !this.position || !this.sym) return
    const qty = Math.abs(this.position.net)
    const side: OrderSide = this.position.net > 0 ? 'SELL' : 'BUY'
    try {
      // Square off with a plain market placeorder (opposite side, position qty) —
      // never placesmartorder.
      await this.trade.place({
        symbol: this.sym.symbol,
        exchange: this.sym.exchange,
        side,
        type: 'MARKET',
        qty,
        product: (this.position.product || this.product) as 'CNC' | 'NRML' | 'MIS',
        mode: this.tradeMode(),
      })
      this.toast('position closed', 'ok')
      this.pollBook()
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  /* ── chart build + interaction wiring ─────────────────────────────────── */
  private buildChart() {
    // Snapshot drawings before the chart they live on goes away.
    this.detachDrawing()
    if (this.chart) this.chart.destroy()
    // The primitives registered here belonged to the chart just destroyed.
    this.screenshotExcluded.length = 0
    this.container.innerHTML = ''
    const { mode, appMode } = this.getTheme()
    this.chart = createChart(this.container, {
      priceAxisWidth: 78,
      theme: buildChartTheme(mode, appMode),
      // The library's built-in screenshot command calls its own
      // `downloadScreenshot()`, which knows nothing about this terminal's DOM
      // OHLC readout or its trade panel. Unbind it and claim the same chord for
      // `screenshot()` below, so the keyboard and the toolbar button produce the
      // same image instead of two different ones.
      shortcuts: {
        disabledCommands: ['screenshot'],
        customShortcuts: [
          {
            command: 'app:screenshot',
            label: 'Screenshot (PNG)',
            combos: 'Alt+Shift+KeyS',
            onTrigger: () => {
              void this.screenshot()
            },
          },
        ],
      },
      // The pane's top-left already holds this terminal's own OHLC readout (and
      // the lot line under it). Start the canvas indicator legends below both,
      // or they land underneath and their settings / close buttons cannot be
      // seen or clicked.
      // The corner already holds this terminal's OHLC readout and, below it,
      // the SELL/qty/BUY panel (44 + 42*0.72 ~= 75). Indicator legend rows have
      // to start under both or they land on top of the buttons.
      legendOffset: { top: 80 },
    })
    const cfg = CHART_TYPES[this.ctype] || CHART_TYPES.candlestick
    const dp = this.dp()
    const light = isLightTheme(mode, appMode)
    const style: SeriesStyle = cfg.baseline
      ? { baseValue: this.rawBars.reduce((s, b) => s + b.close, 0) / (this.rawBars.length || 1) }
      : {}
    this.price = this.chart.addSeries(cfg.series as SeriesType, {
      style,
      priceFormat: { type: 'custom', formatter: (p: number) => p.toFixed(dp) },
    })
    // Volume rides an OVERLAY price scale inside the price pane rather than a
    // pane of its own: it autoscales independently but draws no axis, so the
    // right-hand column stays a clean price ladder instead of stacking a second
    // numeric scale beside it. The top margin pins the bars to the bottom fifth.
    this.volume = this.chart.addSeries('histogram', {
      paneIndex: 0,
      priceScaleId: '',
      style: { color: volumeColor(mode, appMode) },
      // Raw share counts run to nine digits; 'volume' renders 1.20M / 3.40B.
      priceFormat: { type: 'volume' },
    })
    this.volume.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 })
    // A rebuild makes a fresh series, so the preference has to be re-applied
    // rather than assumed -- switching chart type or theme would show it again.
    if (!this.volumeOn) this.volume.applyOptions({ visible: false })
    this.setPriceData()

    // Default zoom: a FIXED number of recent bars, so the visible price range
    // (and cursor→price mapping) is the same on every screen width.
    if (this.shownCount > VISIBLE_BARS) {
      const to = this.shownCount - 1 + 4
      this.chart.timeScale.setVisibleLogicalRange({ from: to - VISIBLE_BARS, to })
    } else if (this.chart.timeScale.barSpacing > 14) {
      this.chart.timeScale.setBarSpacing(14)
    }

    const lp =
      this.lastLtp != null
        ? this.lastLtp
        : this.rawBars.length
          ? this.rawBars[this.rawBars.length - 1].close
          : null
    this.ltpLine =
      lp != null
        ? this.chart.addPriceLine(
            { price: lp, color: this.ltpColor(lp), lineWidth: 1, dashed: true, id: 'ltp' },
            0
          )
        : null

    // Mini brand mark, bottom-left. On pane 0 now that volume is an overlay
    // there rather than a pane of its own — pane 1 only exists once an
    // indicator asks for one, so anchoring to it would have been conditional.
    const watermark = new LogoWatermark({
      // The symbol on its own, not the app icon: that asset is a full-bleed
      // plate with the mark filling under half of it and the wordmark
      // beneath, so scaling it up scaled the padding too. This one's square
      // viewBox is tight to the symbol, so height alone gives 32x32, and
      // 3 of plate padding puts it in a 38x38 square.
      src: '/images/openalgo-glyph.svg',
      position: 'bottom-left',
      height: 32,
      padding: 3,
      margin: 10,
      opacity: 0.85,
      // Mark alone at rest; the wording unrolls to its right on hover, so it
      // names itself when looked at without occupying the corner always. The
      // mark and text share one colour, so this sets both.
      label: 'OpenAlgo Charts',
      labelColor: light ? '#3c4354' : '#e4e8f4',
      href: 'https://openalgo.in',
    })
    this.chart.addPrimitive(watermark, 0)

    // inline SELL · qty · BUY panel, docked top-left below the OHLC legend.
    if (!this.sym!.quoteOnly) {
      this.tradeBtns = new BuySellButtons({
        id: 'trade',
        position: 'top-left',
        margin: { x: 14, y: 44 },
        qty: this.qtyChip(),
        scale: 0.72,
      })
      if (lp != null) this.tradeBtns.setMark(lp)
      // Order entry is an affordance, not chart content: it is left out of a
      // saved image (see `screenshotExcluded`).
      this.addExcludedPrimitive(this.tradeBtns, 0)
    } else this.tradeBtns = null

    this.chart.subscribeCrosshairMove((e) =>
      this.setLegend(e.bar || (this.rawBars.length ? this.rawBars[this.rawBars.length - 1] : null))
    )

    // drag-to-modify with a drag ghost; commit on release (tick-snapped)
    this.chart.subscribeDrag(
      (id, p) => {
        if (!id.startsWith('order:') || id.endsWith('::close')) return
        const rec = this.orderLines.get(id.slice(6))
        if (!rec) return
        if (rec.dragFrom == null) {
          rec.dragFrom = rec.line.price
          rec.line.setDragGhost(rec.dragFrom)
        }
        rec.line.setPrice(this.snap(p))
      },
      (id, p) => {
        if (!id.startsWith('order:') || id.endsWith('::close')) return
        const oid = id.slice(6)
        const rec = this.orderLines.get(oid)
        if (!rec) return
        rec.line.setDragGhost(null)
        rec.dragFrom = null
        const px = this.snap(p)
        const stop = rec.order.type === 'SL' || rec.order.type === 'SL-M'
        this.trade!.modify(oid, stop ? { triggerPrice: px } : { price: px })
          .then(() => this.pollBook())
          .catch((e) => {
            this.toast(this.cleanError(e), 'err')
            this.pollBook()
          })
      }
    )
    this.chart.subscribeClick((id) => {
      // The canvas cannot hold an anchor, so the mark reports the hit and the
      // host navigates. noopener/noreferrer: the opened tab must not reach back
      // into a page holding a broker session.
      if (id === 'watermark') {
        const href = watermark.href()
        if (href) window.open(href, '_blank', 'noopener,noreferrer')
        return
      }
      if (id === 'trade:buy') return void this.placeFromMenu('BUY', 'MARKET')
      if (id === 'trade:sell') return void this.placeFromMenu('SELL', 'MARKET')
      if (id === 'position::close') return void this.exitPosition()
      if (id.startsWith('order:') && id.endsWith('::close')) {
        const oid = id.slice(6, -7)
        this.trade!.cancel(oid)
          .then(() => {
            this.toast(`order ${oid} cancelled`, 'ok')
            this.pollBook()
          })
          .catch((e) => this.toast(this.cleanError(e), 'err'))
      }
    })

    this.orderLines.clear()
    this.posLine = null
    this.position = null
    if (this.trade && this.sym) this.pollBook()
    this.setLegend(this.rawBars.length ? this.rawBars[this.rawBars.length - 1] : null)

    // Re-apply everything the rebuild just discarded.
    this.chart.setGridOptions({ vertLines: this.gridV, horzLines: this.gridH })
    if (this.drawEnabled) void this.attachDrawing()
    if (this.activeIndicators.length) void this.applyIndicators()
    // The gear on an indicator's legend row. openalgo-charts is canvas-only and
    // ships no DOM, so it emits and the host renders the form.
    this.chart.on('indicatorSettings', (p) => {
      void this.emitIndicatorSettings((p as { instanceId: string }).instanceId)
    })
    // The on-chart legend's x removes an indicator without going through this
    // class. Without this the toolbar list went stale, and worse, the tracked
    // list still held it — so the next rebuild (timeframe, chart type, theme)
    // brought the deleted indicator back.
    this.chart.on('indicatorRemoved', () => this.syncIndicators())
    // Scrolling back past the loaded range pages in older bars.
    this.chart.setHistoryLoader(() => void this.loadOlderHistory())
  }

  /**
   * Rehydrate drawings, indicators, magnet and grid from this pane's own
   * storage slot. Anything malformed is dropped rather than thrown — a stale
   * entry must never stop the terminal booting.
   */
  private restoreChartTools(): void {
    try {
      const raw = this.lsGet('draw')
      const parsed = raw ? (JSON.parse(raw) as DrawingJson[]) : []
      if (Array.isArray(parsed) && parsed.length) {
        this.drawJson = parsed
        this.drawEnabled = true
      }
    } catch {
      /* ignore */
    }
    try {
      const raw = this.lsGet('indicators')
      const parsed = raw ? (JSON.parse(raw) as typeof this.activeIndicators) : []
      if (Array.isArray(parsed)) this.activeIndicators = parsed
    } catch {
      /* ignore */
    }
    this.drawMagnet = this.lsGet('magnet') === '1'
    const grid = this.lsGet('grid')
    if (grid && grid.length === 2) {
      this.gridV = grid[0] === '1'
      this.gridH = grid[1] === '1'
    }
    // Absent means shown: only an explicit '0' hides it, so existing panes and
    // a first visit both keep volume.
    this.volumeOn = this.lsGet('vol') !== '0'
  }

  /**
   * Page in the bars before the oldest one loaded, when the user scrolls back
   * to the left edge. The chart raises this once and waits for
   * `historyLoadComplete`, so every exit has to report back or paging stops for
   * the rest of the session.
   */
  private async loadOlderHistory(): Promise<void> {
    if (this.loadingOlder || this.noMoreHistory || !this.rest || !this.sym || !this.chart) {
      this.chart?.historyLoadComplete()
      return
    }
    const oldest = this.rawBars[0]?.time
    if (oldest === undefined) {
      this.chart.historyLoadComplete()
      return
    }
    this.loadingOlder = true
    try {
      const to = oldest - 1
      const older = await this.rest.getBars({
        symbol: this.sym.symbol,
        exchange: this.sym.exchange,
        interval: this.interval,
        from: to - lookbackDays(this.interval) * 86400,
        to,
      })
      if (this.destroyed || !this.chart) return
      // Trust nothing about the window the broker actually returned: keep only
      // what is genuinely older, or a re-sent overlapping page would duplicate
      // bars and grow rawBars without ever moving the left edge.
      const fresh = older.filter((b) => b.time < oldest)
      if (fresh.length === 0) {
        this.noMoreHistory = true
        return
      }
      // Prepending shifts every logical index by the inserted count, so the
      // view has to shift with it or the user is thrown back to the right edge
      // mid-scroll.
      const before = this.chart.getVisibleLogicalRange()
      const countBefore = this.shownCount
      this.rawBars = [...fresh, ...this.rawBars]
      this.setPriceData()
      // Measure the shift rather than assuming it is fresh.length: a
      // movement-driven chart type (Renko, P&F) turns raw bars into a different
      // number of elements, so the axis grows by its own amount.
      const inserted = this.shownCount - countBefore
      if (before && inserted > 0) {
        this.chart.setVisibleLogicalRange({
          from: before.from + inserted,
          to: before.to + inserted,
        })
      }
    } catch (e) {
      // A failed page must not poison the session; the next scroll retries.
      console.error('[trading] history paging', e)
    } finally {
      this.loadingOlder = false
      this.chart?.historyLoadComplete()
    }
  }

  /* ── drawing tools (additive: the trading controls above are untouched) ── */

  /**
   * Snapshot the drawings and drop the controller. Called before the chart is
   * rebuilt and on destroy — the anchors are data, so they survive as JSON and
   * come back on the next chart.
   */
  private detachDrawing(): void {
    if (!this.draw) return
    try {
      this.drawJson = this.draw.toJSON()
      this.draw.destroy()
    } catch {
      /* chart already gone; keep the last snapshot we have */
    }
    this.draw = null
  }

  /**
   * Attach the drawing tier to the current chart, fetching it on first use so a
   * pane that never draws never pays for the bundle.
   */
  private async attachDrawing(): Promise<void> {
    if (this.draw || !this.chart) return
    const { DrawingController, drawingShortcuts, matchDrawingShortcut } = await import(
      'openalgo-charts/draw'
    )
    // The await is a real suspension point: the pane can be destroyed, or the
    // chart rebuilt again, while the tier is in flight.
    if (this.destroyed || !this.chart || this.draw) return
    const draw = new DrawingController(this.chart, {
      magnet: this.drawMagnet,
      stayInDrawingMode: false,
    })
    this.draw = draw
    this.drawShortcuts = drawingShortcuts()
    this.matchShortcut = matchDrawingShortcut
    if (this.drawJson.length) {
      try {
        draw.fromJSON(this.drawJson)
      } catch {
        this.drawJson = [] // a shape from an older build; better empty than broken
      }
    }
    if (this.drawTool) draw.setTool(this.drawTool)
    this.chart.on('draw:tool', () => this.afterDrawChange())
    this.chart.on('draw:select', () => this.afterDrawChange())
    // A text tool is useless until it has text, so placing one asks straight
    // away rather than leaving an empty box on the chart.
    this.chart.on('draw:add', (p) => {
      const d = (p as { drawing?: { id: string; tool: string; style?: { text?: string } } }).drawing
      if (d && TEXT_TOOLS.has(d.tool)) {
        this.cb.onDrawTextEdit?.({ id: d.id, tool: d.tool, text: d.style?.text ?? '' })
      }
    })
    this.chart.on('draw:add', () => this.afterDrawChange())
    this.chart.on('draw:remove', () => this.afterDrawChange())
    // Double-click a text drawing to open its settings. The chart's own
    // double-click resets the view, which it must not do when the gesture was
    // aimed at a drawing -- editSelectedText() reports whether it claimed it.
    this.chart.on('dblclick', () => {
      this.editSelectedText()
    })
    this.chart.on('draw:update', () => this.afterDrawChange())
  }

  private afterDrawChange(): void {
    if (!this.draw) return
    this.drawTool = this.draw.activeTool()
    this.drawJson = this.draw.toJSON()
    this.lsSet('draw', JSON.stringify(this.drawJson))
    this.cb.onDrawChange?.(this.drawStats())
    this.cb.onDrawSelect?.(this.drawSelection())
  }

  /** The selected drawing's editable style, or null when nothing is selected. */
  drawSelection(): DrawSelection | null {
    const id = this.draw?.selected()
    if (!this.draw || !id) return null
    const d = this.draw.get(id)
    if (!d) return null
    return {
      id: d.id,
      tool: d.tool,
      hasText: TEXT_TOOLS.has(d.tool),
      color: d.style.color ?? '#4f8cff',
      lineWidth: d.style.lineWidth ?? 1.5,
      lineStyle: d.style.lineStyle ?? 'solid',
      locked: d.locked === true,
    }
  }

  /** Whether a drawing's content is typed (so the host can offer an edit). */
  isTextDrawing(id: string): boolean {
    const d = this.draw?.get(id)
    return d !== undefined && TEXT_TOOLS.has(d.tool)
  }

  /**
   * Open the selected drawing's text settings, if it is a text-bearing one.
   * Returns whether it did, so a double-click handler knows not to also reset
   * the view. The engine's `dblclick` carries no id -- a press selects first,
   * so the selection is the target.
   */
  editSelectedText(): boolean {
    const id = this.draw?.selected()
    if (!id) return false
    const d = this.draw?.get(id)
    if (!d || !TEXT_TOOLS.has(d.tool)) return false
    this.requestDrawTextEdit(id)
    return true
  }

  /** Ask the host to edit a drawing's text — the style bar's T button. */
  requestDrawTextEdit(id: string): void {
    const d = this.draw?.get(id)
    if (!d || !TEXT_TOOLS.has(d.tool)) return
    this.cb.onDrawTextEdit?.({ id: d.id, tool: d.tool, text: d.style.text ?? '' })
  }

  /**
   * The current text style of a drawing, for opening its settings populated.
   * Background and border default OFF, matching the engine's own defaults —
   * text dropped on a chart should be the words, not a filled plate.
   */
  drawTextStyle(id: string): DrawTextStyle | null {
    const d = this.draw?.get(id)
    if (!d) return null
    const st = (d.style ?? {}) as Record<string, unknown>
    return {
      text: (st.text as string) ?? '',
      color: (st.color as string) ?? '#e4e8f4',
      fontSize: (st.fontSize as number) ?? 14,
      bold: st.fontWeight === 'bold',
      italic: st.fontStyle === 'italic',
      background: st.background === true,
      // Never the chart's own background: a plate in that colour is invisible,
      // which reads as "Background does nothing". A neutral grey shows on both
      // the dark and light themes.
      backgroundColor: (st.backgroundColor as string) ?? '#434651',
      border: st.border === true,
      borderColor: (st.borderColor as string) ?? (st.color as string) ?? '#e4e8f4',
      wrap: st.wrap === true,
    }
  }

  /**
   * Apply the text dialog's result. Empty text removes the drawing rather than
   * leaving an invisible box behind, the same rule `setDrawingText` follows.
   */
  applyDrawText(id: string, v: DrawTextStyle): void {
    if (!this.draw) return
    const trimmed = v.text.trim()
    if (trimmed === '') {
      this.draw.remove(id)
      this.afterDrawChange()
      return
    }
    this.draw.update(id, {
      style: {
        text: trimmed,
        color: v.color,
        fontSize: v.fontSize,
        fontWeight: v.bold ? 'bold' : 'normal',
        fontStyle: v.italic ? 'italic' : 'normal',
        background: v.background,
        backgroundColor: v.backgroundColor,
        border: v.border,
        borderColor: v.borderColor,
        wrap: v.wrap,
      },
    })
    this.afterDrawChange()
  }

  /** Set a drawing's text. Empty text removes it rather than leaving a blank. */
  setDrawingText(id: string, text: string): void {
    if (!this.draw) return
    const trimmed = text.trim()
    if (trimmed === '') this.draw.remove(id)
    else this.draw.update(id, { style: { text: trimmed } })
    this.afterDrawChange()
  }

  /** Restyle the selected drawing (colour, width, dash, lock). */
  styleSelectedDrawing(patch: {
    color?: string
    lineWidth?: number
    lineStyle?: 'solid' | 'dashed' | 'dotted'
    locked?: boolean
  }): void {
    const id = this.draw?.selected()
    if (!this.draw || !id) return
    const { locked, ...style } = patch
    if (Object.keys(style).length > 0) this.draw.update(id, { style })
    if (locked !== undefined) this.draw.update(id, { locked })
    this.afterDrawChange()
  }

  /** Arm a drawing tool, or pass null to return to the cursor. */
  async setDrawTool(id: string | null): Promise<void> {
    this.drawEnabled = true
    this.drawTool = id
    await this.attachDrawing()
    this.draw?.setTool(id)
    this.cb.onDrawChange?.(this.drawStats())
  }

  /** Toolbar state: counts and what is currently possible. */
  /**
   * Arm the tool bound to this key event, reporting whether one matched so the
   * caller can swallow the key. The tier owns the chord table, so this is a
   * no-op until drawing has been attached.
   */
  armByShortcut(e: {
    key: string
    altKey?: boolean
    ctrlKey?: boolean
    metaKey?: boolean
    shiftKey?: boolean
  }): boolean {
    const id = this.matchShortcut?.(e) ?? null
    if (id === null) return false
    void this.setDrawTool(id)
    return true
  }

  drawStats(): DrawStats {
    const d = this.draw
    return {
      count: d ? d.drawings().length : this.drawJson.length,
      canUndo: d ? d.canUndo() : false,
      canRedo: d ? d.canRedo() : false,
      hasSelection: d ? d.selected() !== null : false,
      magnet: this.drawMagnet,
      tool: this.drawTool,
      shortcuts: this.drawShortcuts,
    }
  }

  undoDraw(): void {
    this.draw?.undo()
    this.afterDrawChange()
  }

  redoDraw(): void {
    this.draw?.redo()
    this.afterDrawChange()
  }

  /** Remove the selected drawing, or every drawing when `all` is set. */
  removeDrawings(all: boolean): void {
    if (!this.draw) return
    if (all) this.draw.clear()
    else {
      const id = this.draw.selected()
      if (id) this.draw.remove(id)
    }
    this.afterDrawChange()
  }

  /** Snap drawing anchors to the hovered bar's O/H/L/C. */
  setMagnet(on: boolean): void {
    this.drawMagnet = on
    this.draw?.setOptions({ magnet: on })
    this.lsSet('magnet', on ? '1' : '0')
    this.cb.onDrawChange?.(this.drawStats())
  }

  /* ── indicators + grid (top-menu extras) ───────────────────────────────── */

  /** The registered indicator catalogue, loading the tier on first use. */
  async indicatorCatalog(): Promise<{ id: string; name: string; category: string }[]> {
    await this.loadIndicators()
    const { registeredIndicators } = await import('openalgo-charts')
    return registeredIndicators().map((d) => ({
      id: d.id,
      name: d.name,
      category: d.category ?? 'Other',
    }))
  }

  private async loadIndicators(): Promise<void> {
    if (this.indicatorsLoaded) return
    await import('openalgo-charts/indicators')
    this.indicatorsLoaded = true
  }

  /** Re-add the tracked indicators to a freshly built chart. */
  private async applyIndicators(): Promise<void> {
    await this.loadIndicators()
    if (this.destroyed || !this.chart) return
    // Re-adding walks the tracked list, so a sync mid-loop would read a
    // half-applied chart and truncate it.
    this.applyingIndicators = true
    try {
      for (const rec of this.activeIndicators) {
        try {
          this.chart.addIndicator(rec.indicatorId, rec.settings)
        } catch {
          /* an id that is no longer registered — skip rather than break the chart */
        }
      }
    } finally {
      this.applyingIndicators = false
    }
    this.syncIndicators()
  }

  /** Gather a settings form for one live indicator and hand it to the host. */
  private async emitIndicatorSettings(instanceId: string): Promise<void> {
    if (!this.chart || !this.cb.onIndicatorSettings) return
    const inst = this.chart.indicators().find((i) => i.id === instanceId)
    if (!inst) return
    const { registeredIndicators, indicatorStyleInputs } = await import('openalgo-charts')
    const descriptor = registeredIndicators().find((d) => d.id === inst.indicatorId)
    if (!descriptor) return
    // Value inputs and generated style inputs stay separate so the form can tab
    // them the way a charting package does; one component covers every
    // indicator without a line of indicator-specific code.
    const toField = (f: {
      key: string
      type: string
      label?: string
      group?: string
    }): IndicatorField => ({
      key: f.key,
      type: f.type,
      label: f.label ?? f.key,
      group: (f as { group?: string }).group,
      options: (f as { options?: { label: string; value: unknown }[] }).options,
      min: (f as { min?: number }).min,
      max: (f as { max?: number }).max,
      step: (f as { step?: number }).step,
    })
    this.cb.onIndicatorSettings({
      instanceId,
      name: inst.name,
      values: { ...inst.settings() },
      inputs: descriptor.inputs.map(toField),
      styleInputs: indicatorStyleInputs(descriptor).map(toField),
    })
  }

  /** The descriptor's default settings, for the form's Defaults action. */
  async indicatorDefaultsFor(instanceId: string): Promise<Record<string, unknown> | null> {
    const inst = this.chart?.indicators().find((i) => i.id === instanceId)
    if (!inst) return null
    const { registeredIndicators, indicatorDefaults } = await import('openalgo-charts')
    const d = registeredIndicators().find((x) => x.id === inst.indicatorId)
    return d ? { ...indicatorDefaults(d) } : null
  }

  /** Apply a settings patch to a live indicator. */
  updateIndicatorSettings(instanceId: string, patch: Record<string, unknown>): void {
    const inst = this.chart?.indicators().find((i) => i.id === instanceId)
    if (!inst) return
    inst.setSettings(patch)
    this.syncIndicators()
  }

  /** Open the settings form for an indicator from the host's own UI. */
  openIndicatorSettings(instanceId: string): void {
    void this.emitIndicatorSettings(instanceId)
  }

  /**
   * Re-read the tracked list from the chart, which is the only thing that knows
   * the truth — indicators can also be removed from their own on-chart legend.
   * Reading the whole list rather than patching it also keeps duplicates right:
   * two SMAs differ only by instance id, so "remove the one with this
   * indicatorId" would drop an arbitrary one of them.
   */
  private syncIndicators(): void {
    if (!this.chart || this.applyingIndicators) return
    this.activeIndicators = this.chart.indicators().map((i) => ({
      indicatorId: i.indicatorId,
      settings: { ...i.settings() },
    }))
    this.lsSet('indicators', JSON.stringify(this.activeIndicators))
    this.cb.onIndicatorsChange?.(this.listIndicators())
  }

  async addIndicatorById(indicatorId: string): Promise<void> {
    await this.loadIndicators()
    if (!this.chart) return
    try {
      this.chart.addIndicator(indicatorId, {})
      this.syncIndicators()
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  removeIndicatorById(instanceId: string): void {
    if (!this.chart) return
    this.chart.removeIndicator(instanceId)
    this.syncIndicators()
  }

  listIndicators(): { id: string; name: string }[] {
    return this.chart ? this.chart.indicators().map((i) => ({ id: i.id, name: i.name })) : []
  }

  /** Grid visibility, independently per axis. */
  setGrid(vertical: boolean, horizontal: boolean): void {
    this.gridV = vertical
    this.gridH = horizontal
    this.chart?.setGridOptions({ vertLines: vertical, horzLines: horizontal })
    this.lsSet('grid', `${vertical ? 1 : 0}${horizontal ? 1 : 0}`)
  }

  gridState(): { vertical: boolean; horizontal: boolean } {
    return { vertical: this.gridV, horizontal: this.gridH }
  }

  /**
   * Show or hide the built-in volume histogram, remembered per pane.
   *
   * Hidden rather than removed: the series keeps taking data, so toggling back
   * is instant and no history has to be refetched. It also keeps the overlay
   * price scale in place, which is what the bars are measured against.
   */
  setVolumeVisible(on: boolean): void {
    this.volumeOn = on
    this.volume?.applyOptions({ visible: on })
    this.lsSet('vol', on ? '1' : '0')
  }

  volumeVisible(): boolean {
    return this.volumeOn
  }

  /* ── WS-down fallback: poll quotes so LTP + the forming candle stay live ─ */
  private startLtpFallback() {
    if (this.ltpPollTimer) return
    this.ltpPollTimer = setInterval(async () => {
      if (!this.sym) return
      try {
        const j = await this.api<{ data?: { ltp?: number; bid?: number; ask?: number } }>(
          'quotes',
          {
            symbol: this.sym.symbol,
            exchange: this.sym.exchange,
          }
        )
        const q = j.data || {}
        if (typeof q.ltp === 'number' && q.ltp > 0)
          this.onTick({ symbol: this.sym.symbol, ltp: q.ltp, timeSec: nowSec() })
        if (
          this.tradeBtns &&
          typeof q.bid === 'number' &&
          typeof q.ask === 'number' &&
          q.bid > 0 &&
          q.ask > 0
        ) {
          this.depthActive = true
          this.tradeBtns.setPrices(q.bid, q.ask)
        }
        this.cb.onWsState('fallback')
      } catch {
        /* next cycle */
      }
    }, 4000)
  }
  private stopLtpFallback() {
    if (this.ltpPollTimer) {
      clearInterval(this.ltpPollTimer)
      this.ltpPollTimer = null
    }
  }

  /**
   * Colour for the last-price line: the direction of the bar it sits in, so it
   * matches that candle and the OHLC legend. Amber only until a bar exists to
   * compare against.
   */
  private ltpColor(price: number): string {
    const bar = this.rawBars.length ? this.rawBars[this.rawBars.length - 1] : null
    if (!bar) return LTP_NEUTRAL
    return price >= bar.open ? UP : DN
  }

  /* single tick path shared by WS pushes and the REST fallback */
  private onTick(e: { symbol?: string; ltp: number; ltq?: number; timeSec?: number }) {
    if (!this.sym || (e.symbol && e.symbol !== this.sym.symbol)) return
    this.lastLtp = e.ltp
    this.cb.onLtp(e.ltp)
    // Recolour with the price: the line belongs to the forming candle, so it
    // follows that candle's direction rather than sitting amber forever.
    if (this.ltpLine) this.ltpLine.setOptions({ price: e.ltp, color: this.ltpColor(e.ltp) })
    if (this.position && this.posLine) this.posLine.setLeftLabel(this.posLabel())
    if (this.tradeBtns && !this.depthActive) this.tradeBtns.setMark(e.ltp)
    if (this.builder) {
      const u = this.builder.onTick({ time: e.timeSec || nowSec(), price: e.ltp, ltq: e.ltq })
      if (u) {
        this.liveBucket = u.bar.time
        // Key the upsert on time rather than the builder's isNew flag, so a
        // builder that ever disagrees with rawBars about the current bucket
        // overwrites that bar instead of appending a duplicate of it.
        const last = this.rawBars[this.rawBars.length - 1]
        if (last && last.time === u.bar.time) this.rawBars[this.rawBars.length - 1] = u.bar
        else this.rawBars.push(u.bar)
        this.setPriceData()
      }
    }
    this.setLegend(this.rawBars.length ? this.rawBars[this.rawBars.length - 1] : null)
  }

  /* ── live data: WS ticks → candles; depth → bid/ask ───────────────────── */
  private connectLive() {
    if (!this.ws || !this.sym) return
    const sec = intervalSeconds(this.interval)
    this.builder = sec ? new CandleBuilder({ intervalSec: sec, volumeMode: 'ltq-sum' }) : null
    // History normally ends *inside* the bar currently forming. An unseeded
    // builder has no current bar, so its first tick opens a second one for that
    // same bucket -- opening at whatever tick price arrives first instead of the
    // bucket's true open, restarting volume at 0, and leaving rawBars with two
    // entries for one time. Seeding hands it the last bar so ticks fold into it.
    if (this.builder && this.rawBars.length) {
      this.builder.seed(this.rawBars[this.rawBars.length - 1])
    }
    this.depthActive = false
    if (this.offLtp) {
      this.offLtp()
      this.offLtp = null
    }
    if (this.offDepth) {
      this.offDepth()
      this.offDepth = null
    }
    this.offLtp = this.ws.onLtp((e: LtpEvent) => {
      this.cb.onWsState('live')
      this.stopLtpFallback()
      this.onTick(e)
    })
    this.offDepth = this.ws.onDepth((symbol: string, _exchange: string, depth: MarketDepth) => {
      if (!this.sym || symbol !== this.sym.symbol) return
      const bid = depth.bids?.[0]?.price
      const ask = depth.asks?.[0]?.price
      if (typeof bid === 'number' && typeof ask === 'number' && bid > 0 && ask > 0) {
        this.depthActive = true
        if (this.tradeBtns) this.tradeBtns.setPrices(bid, ask)
      }
      // Depth is the terminal's ONLY subscription for tradeable instruments,
      // so the chart ticks off depth.ltp -- a first-class field in every mode-3
      // payload per the WebSocket protocol (docs/prompt/websockets-format.md).
      // This replaced the old dual LTP+Depth subscribe, which broke on brokers
      // whose adapters track one mode per symbol (Depth overwrote LTP and the
      // chart froze while depth kept flowing -- issue #1664).
      if (typeof depth.ltp === 'number' && depth.ltp > 0) {
        this.cb.onWsState('live')
        this.stopLtpFallback()
        this.onTick({ ltp: depth.ltp })
      }
    })
    // One subscription per symbol, mode picked by instrument type: indices
    // have no order book (LTP), tradeables get Depth which embeds ltp.
    if (this.sym.quoteOnly) {
      this.ws.subscribe('LTP', this.sym.symbol, this.sym.exchange)
    } else {
      this.ws.subscribe('Depth', this.sym.symbol, this.sym.exchange, 5)
    }
  }

  /* periodic history reconcile: snap completed bars to broker OHLC/volume */
  private scheduleReconcile() {
    if (this.reconcileTimer) clearTimeout(this.reconcileTimer)
    this.reconcileTimer = setTimeout(
      async () => {
        try {
          if (this.sym && this.rest) {
            const to = nowSec()
            const fresh = await this.rest.getBars({
              symbol: this.sym.symbol,
              exchange: this.sym.exchange,
              interval: this.interval,
              from: to - Math.min(3, lookbackDays(this.interval)) * 86400,
              to,
            })
            const byTime = new Map(fresh.map((b) => [b.time, b]))
            let changed = false
            for (let i = 0; i < this.rawBars.length; i++) {
              const f = byTime.get(this.rawBars[i].time)
              if (f && (this.liveBucket == null || f.time < this.liveBucket)) {
                this.rawBars[i] = f
                changed = true
              }
            }
            if (changed) this.setPriceData()
          }
        } catch {
          /* next cycle retries */
        }
        this.scheduleReconcile()
      },
      25000 + Math.random() * 10000
    )
  }

  /* ── symbol selection ─────────────────────────────────────────────────── */
  async loadSymbol(pick: SearchRow, opts: { silent?: boolean } = {}): Promise<boolean> {
    if (!this.rest) return false
    // swap the live stream: drop the previous symbol's subscription
    if (
      this.ws &&
      this.sym &&
      (this.sym.symbol !== pick.symbol || this.sym.exchange !== pick.exchange)
    ) {
      // Mirror connectLive's single-subscription model: the outgoing symbol
      // holds exactly one mode -- LTP when quote-only, Depth otherwise.
      try {
        if (this.sym.quoteOnly) {
          this.ws.unsubscribe('LTP', this.sym.symbol, this.sym.exchange)
        } else {
          this.ws.unsubscribe('Depth', this.sym.symbol, this.sym.exchange)
        }
      } catch {
        /* not subscribed */
      }
    }
    // authoritative metadata (lotsize / tick_size / freeze_qty)
    let info: Record<string, unknown> = { ...pick }
    try {
      const j = await this.api<{ data?: Record<string, unknown> }>('symbol', {
        symbol: pick.symbol,
        exchange: pick.exchange,
      })
      info = { ...pick, ...(j.data || {}) }
    } catch {
      /* search row already carries the essentials */
    }
    const exchange = String(info.exchange)
    const lotsize = Number(info.lotsize) || 1
    // The segment decides this, never the lot size. Every MCX, NCO and CDS
    // contract carries lotsize 1 in the master, so a `lotsize > 1` guard read
    // them as cash equity and offered CNC — which those segments do not accept,
    // so the broker rejected the order. Quantity is unaffected: orderQty() is
    // lots × lotsize, and multiplying by a lot size of 1 sends the same number.
    const lots = usesLots(exchange)
    const savedProduct = this.lsGet('product')
    const productOptions = productOptionsFor(exchange)
    this.product = productOptions.includes(savedProduct || '')
      ? (savedProduct as string)
      : productOptions[0]
    this.sym = {
      symbol: String(info.symbol),
      exchange,
      name: String(info.name || ''),
      lotsize,
      lots,
      tick: Number(info.tick_size) || 0.05,
      freezeQty: Number(info.freeze_qty) || 1,
      quoteOnly: QUOTE_ONLY.has(exchange),
      productOptions,
      product: this.product,
    }
    this.qty = 1
    this.lsSet('symbol', JSON.stringify({ symbol: this.sym.symbol, exchange: this.sym.exchange }))

    // history
    const to = nowSec()
    this.lastLtp = null
    this.prevClose = null
    this.liveBucket = null
    this.noMoreHistory = false
    try {
      this.rawBars = await this.rest.getBars({
        symbol: this.sym.symbol,
        exchange: this.sym.exchange,
        interval: this.interval,
        from: to - lookbackDays(this.interval) * 86400,
        to,
      })
    } catch (e) {
      this.rawBars = []
      if (!opts.silent) this.toast(`history error: ${this.cleanError(e)}`, 'err')
      return false // caller may fall back (e.g. to the default symbol)
    }
    if (!this.rawBars.length) {
      if (!opts.silent)
        this.toast(`no history for ${this.sym.symbol} ${this.sym.exchange} ${this.interval}`, 'err')
      return false
    }
    this.prevClose =
      this.rawBars.length > 1
        ? this.rawBars[this.rawBars.length - 2].close
        : this.rawBars[this.rawBars.length - 1].open
    this.lastLtp = this.rawBars[this.rawBars.length - 1].close
    this.buildChart()
    this.cb.onLtp(this.lastLtp)
    this.cb.onSymbolLoaded(this.sym)

    // live subscription (swap the previous symbol's stream)
    this.connectLive()
    this.scheduleReconcile()
    this.pollBook()
    return true
  }

  /* ── toolbar setters (called by the React page) ───────────────────────── */
  setInterval(iv: string) {
    this.interval = iv
    this.lsSet('interval', iv)
    if (this.sym) this.reloadCurrent()
  }
  setChartType(v: string) {
    if (!CHART_TYPES[v]) return
    this.ctype = v
    this.lsSet('ctype', v)
    if (this.rawBars.length) this.buildChart()
  }
  setProduct(p: string) {
    this.product = p
    this.lsSet('product', p)
  }
  setQty(n: number) {
    this.qty = Math.max(1, Math.floor(n || 1))
    if (this.tradeBtns) this.tradeBtns.setQty(this.qtyChip())
  }
  private reloadCurrent() {
    if (!this.sym) return
    this.loadSymbol({ symbol: this.sym.symbol, exchange: this.sym.exchange, name: this.sym.name })
  }

  /** Rebuild the canvas with the current app theme (called on theme toggle). */
  applyTheme() {
    if (this.chart && this.rawBars.length) this.buildChart()
  }

  resetScale() {
    this.chart?.resetScale()
  }

  /* ── PNG export ───────────────────────────────────────────────────────── */

  /**
   * Attach a primitive that must never appear in an exported image.
   *
   * Anything an image cannot be used for — a button, a drag handle — belongs
   * here rather than on `addPrimitive` directly. See `screenshotExcluded`.
   */
  private addExcludedPrimitive(primitive: IPrimitive, paneIndex = 0) {
    this.chart?.addPrimitive(primitive, paneIndex)
    this.screenshotExcluded.push({ primitive, paneIndex })
  }

  /**
   * Save the chart as a PNG.
   *
   * openalgo-charts' own `downloadScreenshot()` is deliberately not used. It
   * composites the pane canvases and nothing else, which gets both halves of
   * this wrong: the OHLC readout is a DOM overlay this terminal owns, so it is
   * invisible to a canvas composite and vanished from the saved image, while
   * the SELL/qty/BUY panel *is* a canvas primitive, so it was baked in — a
   * static image with order buttons on it. So the export is driven from here:
   * detach the interaction-only overlays, take the composite, paint the readout
   * onto it, restore. Filename convention and canvas theme are unchanged.
   */
  async screenshot(): Promise<void> {
    const chart = this.chart
    if (!chart || !this.sym) return
    const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, '-')
    const filename = `${this.sym.symbol}-${this.interval}-${stamp}.png`
    try {
      const canvas = await this.captureCanvas(chart)
      if (!canvas) return
      const a = document.createElement('a')
      a.href = canvas.toDataURL('image/png')
      a.download = filename
      a.click()
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  /**
   * Composite the chart into an offscreen canvas with the export excluded
   * overlays taken down, then paint the OHLC readout into the corner the DOM
   * overlay occupies on screen.
   *
   * The detach/re-attach is why this is async: `removePrimitive` only marks the
   * pane dirty, so the buttons are still in the canvas bitmap until the chart
   * repaints on the next frame.
   */
  private async captureCanvas(chart: ChartInstance): Promise<HTMLCanvasElement | null> {
    const hidden = [...this.screenshotExcluded]
    for (const o of hidden) chart.removePrimitive(o.primitive)
    // Selection handles are grab targets; the drawing itself stays.
    const selected = this.draw?.selected() ?? null
    if (selected) this.draw?.select(null)
    try {
      await nextPaint()
      // A theme toggle or an interval change during that frame rebuilds the
      // chart, and the one captured here would no longer be on screen.
      if (this.destroyed || this.chart !== chart) return null
      const shot = chart.takeScreenshot()
      this.paintLegend(shot)
      return shot
    } finally {
      if (!this.destroyed && this.chart === chart) {
        for (const o of hidden) chart.addPrimitive(o.primitive, o.paneIndex)
        if (selected) this.draw?.select(selected)
      }
    }
  }

  /**
   * Paint the OHLC readout onto a captured canvas, where the DOM overlay sits
   * on screen and in the colours it is showing.
   *
   * The capture is device-pixel sized, and the ratio is derived from the canvas
   * against the container rather than read from `devicePixelRatio` — that is
   * the ratio the chart actually rendered at, which is what has to be matched
   * for the text to land in the right place on a fractional-scaling display.
   *
   * The foreground goes through `resolveCssColor` because the app's theme
   * tokens are oklch, which a canvas is not guaranteed to parse: assigning one
   * to `fillStyle` is silently ignored and the text would paint in whatever
   * colour was set last (black, on a dark chart).
   */
  private paintLegend(canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext('2d')
    if (!ctx || !this.sym) return
    const cssWidth = this.container.clientWidth || canvas.width
    const ratio = canvas.width / cssWidth
    const css = getComputedStyle(this.legendEl)
    const family = css.fontFamily || 'system-ui, sans-serif'
    const foreground = css.color ? resolveCssColor(css.color) : '#e4e8f4'
    ctx.save()
    ctx.scale(ratio, ratio)
    ctx.textBaseline = 'top'
    ctx.font = `500 12px ${family}`
    let x = LEGEND_X
    for (const run of this.legendModel(this.legendBar)) {
      const tone = legendToneStyle(run.tone, foreground)
      ctx.fillStyle = tone.color
      ctx.globalAlpha = tone.alpha
      ctx.fillText(run.text, x, LEGEND_Y)
      x += ctx.measureText(run.text).width + LEGEND_GAP
    }
    const sub = lotInfoText(this.sym, this.qty)
    if (sub) {
      ctx.font = `10px ${family}`
      ctx.fillStyle = foreground
      ctx.globalAlpha = 0.65
      ctx.fillText(sub, LEGEND_X, LEGEND_SUB_Y)
    }
    ctx.restore()
  }

  /* ── right-click order menu ───────────────────────────────────────────── */
  private ctxPrice = 0
  /** Build the context-menu items for a right-click at container-local y. */
  contextMenuAt(localY: number): { price: number; items: CtxItem[] } | null {
    if (!this.chart || !this.sym || this.sym.quoteOnly) return null
    const p = this.chart.coordinateToPrice(localY, 0)
    if (p == null) return null
    this.ctxPrice = this.snap(p)
    const m = this.marketPrice()
    const lotTxt = this.sym.lots ? `${Math.max(1, Math.floor(this.qty || 1))}L` : this.orderQty()
    const defs: [OrderSide, OrderType][] = [
      ['BUY', 'MARKET'],
      ['BUY', 'LIMIT'],
      ['BUY', 'SL'],
      ['SELL', 'MARKET'],
      ['SELL', 'LIMIT'],
      ['SELL', 'SL'],
    ]
    const items = defs.map(([side, type]) => {
      const v = side === 'BUY' ? 'Buy' : 'Sell'
      const label =
        type === 'MARKET'
          ? `${v} ${lotTxt} Market`
          : type === 'LIMIT'
            ? `${v} ${lotTxt} Limit @ ${this.fmt(this.ctxPrice)}`
            : `${v} ${lotTxt} Stop @ ${this.fmt(this.ctxPrice)}`
      let enabled = true
      if (m != null) {
        if (type === 'SL') enabled = side === 'BUY' ? this.ctxPrice > m : this.ctxPrice < m
        else if (type === 'LIMIT') enabled = side === 'BUY' ? this.ctxPrice < m : this.ctxPrice > m
      }
      return { side, type, label, enabled }
    })
    return { price: this.ctxPrice, items }
  }
  placeCtx(side: OrderSide, type: OrderType) {
    void this.placeFromMenu(side, type)
  }

  /* ── bootstrap + teardown ─────────────────────────────────────────────── */
  async init() {
    this.rest = new OpenAlgoDataFeed({ baseUrl: '', apiKey: this.apiKey })
    this.trade = new OpenAlgoTradeFeed({ baseUrl: '', apiKey: this.apiKey, strategy: STRATEGY })

    // broker-supported intervals → the timeframe dropdown
    let groups: IntervalGroup[]
    try {
      const j = await this.api<{ data?: IntervalData }>('intervals')
      groups = intervalGroups(j.data || {})
    } catch {
      groups = intervalGroups({ minutes: ['1m', '5m', '15m'], hours: ['1h'], days: ['D'] })
    }
    this.interval = pickInterval(groups, this.lsGet('interval'))
    this.cb.onReady({ intervalGroups: groups, interval: this.interval, chartType: this.ctype })

    // one WebSocket for ticks + the account-level order stream.
    this.ws = new OpenAlgoWsFeed({ url: this.wsUrl, apiKey: this.apiKey })
    this.ws.onState((s) => {
      this.cb.onWsState(s)
      if (s === 'closed' || s === 'error' || s === 'reconnecting') this.startLtpFallback()
    })
    this.ws.onControl((m) => {
      if (m.type === 'auth' && m.status !== 'success') this.cb.onWsState('auth failed')
    })
    this.ws.onOrderUpdate((e) => {
      if (!this.sym || e.symbol !== this.sym.symbol || !this.chart) return
      const working =
        e.status === 'open' || e.status === 'trigger pending' || e.status === 'pending'
      const rec = this.orderLines.get(e.orderId)
      const o: LineOrder = {
        id: e.orderId,
        side: e.action,
        type: e.pricetype as OrderType,
        qty: e.quantity,
        price: e.price,
        triggerPrice: e.triggerPrice,
        status: working ? 'working' : e.status,
      }
      if (working) {
        if (rec) {
          rec.order = o
          rec.line.setPrice(e.triggerPrice ?? e.price)
        } else this.orderLines.set(e.orderId, { line: this.makeOrderLine(o), order: o })
      } else if (rec) {
        this.chart.removePrimitive(rec.line)
        this.orderLines.delete(e.orderId)
      }
      if (e.status === 'rejected')
        this.toast(`rejected: ${e.rejectionReason || 'see order book'}`, 'err')
      if (e.status === 'complete')
        this.toast(
          `filled: ${e.action} ${e.quantity} @ ${this.fmt(e.averagePrice || e.price)}`,
          'ok'
        )
      if (!working) this.pollBook() // fills/cancels move the position book too
    })
    this.ws.connect()
    this.ws.subscribeOrders()

    if (this.bookTimer) clearInterval(this.bookTimer)
    this.bookTimer = setInterval(() => this.pollBook(), 8000)

    // restore the last symbol; fall back to BHEL/NSE if it's gone or has no data.
    let loaded = false
    try {
      const saved = JSON.parse(this.lsGet('symbol') || 'null') as {
        symbol?: string
        exchange?: string
      } | null
      if (saved?.symbol) {
        const rows = await this.search(saved.symbol, saved.exchange)
        const row = rows.find((r) => r.symbol === saved.symbol && r.exchange === saved.exchange)
        if (row) loaded = await this.loadSymbol(row, { silent: true })
      }
    } catch {
      /* fall through to the default */
    }
    if (!loaded && !this.destroyed) {
      try {
        const rows = await this.search('BHEL', 'NSE')
        const bhel = rows.find((r) => r.symbol === 'BHEL' && r.exchange === 'NSE')
        if (bhel) await this.loadSymbol(bhel)
      } catch {
        /* leave the chart empty; the user can search */
      }
    }
  }

  destroy() {
    this.destroyed = true
    this.detachDrawing()
    if (this.bookTimer) clearInterval(this.bookTimer)
    if (this.reconcileTimer) clearTimeout(this.reconcileTimer)
    this.stopLtpFallback()
    if (this.offLtp) this.offLtp()
    if (this.offDepth) this.offDepth()
    try {
      this.ws?.close()
    } catch {
      /* already closed */
    }
    try {
      this.chart?.destroy()
    } catch {
      /* already gone */
    }
    this.chart = null
    this.ws = null
    this.screenshotExcluded.length = 0
  }
}
