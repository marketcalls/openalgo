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
  createChart,
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
import { runTransform } from 'openalgo-charts/transform'

type ChartInstance = ReturnType<typeof createChart>
type BuySellButtonsInstance = InstanceType<typeof BuySellButtons>
type TradeFeedInstance = InstanceType<typeof OpenAlgoTradeFeed>

import type { AppMode, ThemeMode } from '@/stores/themeStore'
import { buildChartTheme, isLightTheme, volumeColor } from './chartTheme'
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
const QUOTE_ONLY = new Set(['NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX'])
const STRATEGY = 'chart-trading'
const VISIBLE_BARS = 120

const nowSec = () => Math.floor(Date.now() / 1000)
const esc = (s: unknown) =>
  String(s).replace(
    /[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string
  )

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
  private ltpLine: PriceLine | null = null
  private posLine: PriceLine | null = null
  private tradeBtns: BuySellButtonsInstance | null = null

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
    this.interval = localStorage.getItem(`${this.sk}-interval`) || '5m'
    this.ctype = localStorage.getItem(`${this.sk}-ctype`) || 'candlestick'
    if (!CHART_TYPES[this.ctype]) this.ctype = 'candlestick'
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

  async search(query: string, exchange?: string): Promise<SearchRow[]> {
    try {
      const j = await this.api<{ data?: SearchRow[] }>('search', {
        query,
        ...(exchange ? { exchange } : {}),
      })
      return (j.data || []).slice(0, 30)
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
    if (!this.sym) {
      this.legendEl.innerHTML = ''
      return
    }
    const lots = this.sym.lots ? ` · lot ${this.sym.lotsize}` : ''
    const up = '#26a69a'
    const dn = '#ef5350'
    const col = bar && bar.close >= bar.open ? up : dn
    const chg =
      this.lastLtp != null && this.prevClose
        ? ((this.lastLtp - this.prevClose) / this.prevClose) * 100
        : null
    this.legendEl.innerHTML =
      `<b>${esc(this.sym.symbol)}</b> <span style="opacity:.55">· ${esc(this.interval)} · ${esc(this.sym.exchange)}${lots}</span>` +
      (bar
        ? ` <span style="color:${col}">O ${this.fmt(bar.open)} H ${this.fmt(bar.high)} L ${this.fmt(bar.low)} C ${this.fmt(bar.close)}</span>`
        : '') +
      (this.lastLtp != null
        ? ` <span style="color:#e0b020">LTP ${this.fmt(this.lastLtp)}</span>`
        : '') +
      (chg != null
        ? ` <span style="color:${chg >= 0 ? up : dn}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>`
        : '')
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
    if (this.chart) this.chart.destroy()
    this.container.innerHTML = ''
    const { mode, appMode } = this.getTheme()
    this.chart = createChart(this.container, {
      priceAxisWidth: 78,
      theme: buildChartTheme(mode, appMode),
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
    this.volume = this.chart.addSeries('histogram', {
      paneIndex: 1,
      style: { color: volumeColor(mode, appMode) },
    })
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
            { price: lp, color: '#e0b020', lineWidth: 1, dashed: true, id: 'ltp' },
            0
          )
        : null

    // TradingView-style mini brand mark, bottom-left (bottom pane).
    this.chart.addPrimitive(
      new LogoWatermark({
        src: '/images/openalgo-mark.svg',
        position: 'bottom-left',
        height: 34,
        margin: 10,
        opacity: 0.85,
        tint: light ? undefined : '#e4e8f4',
      }),
      1
    )

    // inline SELL · qty · BUY panel, docked top-left below the OHLC legend.
    if (!this.sym!.quoteOnly) {
      this.tradeBtns = new BuySellButtons({
        id: 'trade',
        position: 'top-left',
        margin: { x: 14, y: 52 },
        qty: this.qtyChip(),
      })
      if (lp != null) this.tradeBtns.setMark(lp)
      this.chart.addPrimitive(this.tradeBtns, 0)
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

  /* single tick path shared by WS pushes and the REST fallback */
  private onTick(e: { symbol?: string; ltp: number; ltq?: number; timeSec?: number }) {
    if (!this.sym || (e.symbol && e.symbol !== this.sym.symbol)) return
    this.lastLtp = e.ltp
    this.cb.onLtp(e.ltp)
    if (this.ltpLine) this.ltpLine.setPrice(e.ltp)
    if (this.position && this.posLine) this.posLine.setLeftLabel(this.posLabel())
    if (this.tradeBtns && !this.depthActive) this.tradeBtns.setMark(e.ltp)
    if (this.builder) {
      const u = this.builder.onTick({ time: e.timeSec || nowSec(), price: e.ltp, ltq: e.ltq })
      if (u) {
        this.liveBucket = u.bar.time
        if (u.isNew) this.rawBars.push(u.bar)
        else this.rawBars[this.rawBars.length - 1] = u.bar
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
    })
    this.ws.subscribe('LTP', this.sym.symbol, this.sym.exchange)
    if (!this.sym.quoteOnly) this.ws.subscribe('Depth', this.sym.symbol, this.sym.exchange, 5)
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
      try {
        this.ws.unsubscribe('LTP', this.sym.symbol, this.sym.exchange)
      } catch {
        /* not subscribed */
      }
      try {
        this.ws.unsubscribe('Depth', this.sym.symbol, this.sym.exchange)
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
    const lots = DERIVATIVE_EXCHANGES.has(exchange) && lotsize > 1
    const savedProduct = localStorage.getItem(`-product`)
    const productOptions = lots ? ['MIS', 'NRML'] : ['MIS', 'CNC']
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
    localStorage.setItem(
      `-symbol`,
      JSON.stringify({ symbol: this.sym.symbol, exchange: this.sym.exchange })
    )

    // history
    const to = nowSec()
    this.lastLtp = null
    this.prevClose = null
    this.liveBucket = null
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
    localStorage.setItem(`-interval`, iv)
    if (this.sym) this.reloadCurrent()
  }
  setChartType(v: string) {
    if (!CHART_TYPES[v]) return
    this.ctype = v
    localStorage.setItem(`-ctype`, v)
    if (this.rawBars.length) this.buildChart()
  }
  setProduct(p: string) {
    this.product = p
    localStorage.setItem(`-product`, p)
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

  screenshot() {
    if (!this.chart || !this.sym) return
    const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, '-')
    this.chart.downloadScreenshot(`${this.sym.symbol}-${this.interval}-${stamp}.png`)
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
    this.interval = pickInterval(groups, localStorage.getItem(`-interval`))
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
      const saved = JSON.parse(localStorage.getItem(`-symbol`) || 'null') as {
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
  }
}
