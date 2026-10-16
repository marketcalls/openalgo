/**
 * Trading visualization API (ARCHITECTURE.md §9). A data-driven layer on top of
 * the chart: your app pushes exchange state (positions, orders, trades) and the
 * chart renders labelled price-line "pills" (with a cancel/close button and
 * drag-to-modify) plus trade-fill markers; user interaction is relayed back as
 * `trading:*` events for the app to send to the exchange. Original,
 * framework-free API.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from '../primitives/primitive';
import { PriceLine, type PriceLineOptions } from '../primitives/price-line';
import type { TickSchedule } from '../feed/tick-schedule';
import { contrastText, roundRectPath } from '../render/pill';
import { dispatch } from '../helpers/dispatch';
import type { ChartEventMap } from './chart-events';
import type { LooseOptional } from '../helpers/types';

export type PositionSide = 'long' | 'short';
export type TradingOrderSide = 'buy' | 'sell';
export type TradingOrderType = 'limit' | 'stop' | 'stop_limit';
export type TradeMarkerVariant = 'chevron' | 'bubble' | 'count';
export type TradingLineVariant = 'standard' | 'line-only';
export type TradingLineStyle = 'solid' | 'dashed' | 'dotted';

export interface TradingPosition {
  id: string;
  side: PositionSide;
  entryPrice: number;
  size: number;
  pnlText?: string;
  pnlPercent?: string;
  color?: string;
  readOnly?: boolean;
  variant?: TradingLineVariant;
}

export interface TradingOrder {
  id: string;
  type: TradingOrderType;
  side: TradingOrderSide;
  price: number;
  size: number;
  parentId?: string;
  bracketRole?: 'tp' | 'sl';
  color?: string;
  lineStyle?: TradingLineStyle;
  lineWidth?: number;
  readOnly?: boolean;
  draggable?: boolean;
  variant?: TradingLineVariant;
}

export interface TradingTrade {
  id: string;
  side: TradingOrderSide;
  price: number;
  size: number;
  /** Execution time in milliseconds. */
  timestamp: number;
  variant?: TradeMarkerVariant;
  color?: string;
  label?: string;
}

export interface TradingSyncPayload {
  positions?: TradingPosition[];
  orders?: TradingOrder[];
  trades?: TradingTrade[];
}

/** Payload of `trading:order_modify`: an order line was dragged and released. */
export interface TradingOrderModifyEvent {
  orderId: string;
  newPrice: number;
  previousPrice: number;
}

/** Payload of `trading:bracket_modify`: a take-profit or stop-loss leg was dragged and released. */
export interface TradingBracketModifyEvent {
  parentId: string | undefined;
  bracketRole: 'tp' | 'sl';
  newPrice: number;
}

export interface TradingColors {
  long: string;
  short: string;
  order: string;
  tp: string;
  sl: string;
  buy: string;
  sell: string;
}

export interface TradingSettings {
  longColor?: string;
  shortColor?: string;
  orderColor?: string;
  tpColor?: string;
  slColor?: string;
  buyColor?: string;
  sellColor?: string;
}

/** What the controller needs from the chart (the Chart implements this). */
export interface TradingHost {
  addPrimitive(p: IPrimitive): void;
  removePrimitive(p: IPrimitive): void;
  subscribeClick(cb: (externalId: string) => void): void;
  subscribeDrag(onDrag: (externalId: string, price: number) => void, onDragEnd?: (externalId: string, price: number) => void): void;
  /** Optional: route trading events onto the chart's unified `chart.on(...)` bus. */
  emit?(event: string, payload: unknown): void;
  /**
   * Optional: the instrument's tick schedule when the layer is built. The
   * layer is built on first use, often after the instrument was applied, and
   * applying one does not build it early: building it subscribes to drags,
   * which makes every `ns-resize` price line on the chart draggable.
   */
  tickSchedule?(): TickSchedule | null;
}

export const DEFAULT_TRADING_COLORS: TradingColors = {
  long: '#2f6df6',
  short: '#ef5350',
  order: '#3b82f6',
  tp: '#26a69a',
  sl: '#ef5350',
  buy: '#26a69a',
  sell: '#ef5350',
};

const CLOSE_SUFFIX = '::close';

/** Nearest bar index to a UTC-seconds time (binary search over the sorted times). */
function snapToIndex(dl: { length: number; indexToTime(i: number): number | undefined }, timeSec: number): number | undefined {
  const n = dl.length;
  if (n === 0) return undefined;
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    const tm = dl.indexToTime(mid);
    if (tm !== undefined && tm <= timeSec) lo = mid; else hi = mid - 1;
  }
  const t0 = dl.indexToTime(lo);
  if (t0 === undefined) return undefined;
  if (lo + 1 < n) {
    const t1 = dl.indexToTime(lo + 1);
    if (t1 !== undefined && Math.abs(t1 - timeSec) < Math.abs(t0 - timeSec)) return lo + 1;
  }
  return lo;
}

function drawChevron(ctx: CanvasRenderingContext2D, x: number, y: number, side: TradingOrderSide, color: string, dpr: number): void {
  const s = 5 * dpr;
  ctx.fillStyle = color;
  ctx.beginPath();
  if (side === 'buy') { ctx.moveTo(x, y - s * 1.5); ctx.lineTo(x - s, y); ctx.lineTo(x + s, y); }
  else { ctx.moveTo(x, y + s * 1.5); ctx.lineTo(x - s, y); ctx.lineTo(x + s, y); }
  ctx.closePath();
  ctx.fill();
}

function drawBubble(ctx: CanvasRenderingContext2D, x: number, y: number, color: string, text: string, dpr: number): void {
  const r = 9 * dpr;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  if (text !== '') {
    ctx.fillStyle = contrastText(color);
    ctx.font = `500 ${9 * dpr}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, x, y + 0.5 * dpr);
  }
}

function drawCount(ctx: CanvasRenderingContext2D, x: number, y: number, count: number, color: string, dpr: number): void {
  const text = String(count);
  ctx.font = `500 ${9 * dpr}px system-ui, sans-serif`;
  const w = ctx.measureText(text).width + 10 * dpr;
  const h = 15 * dpr;
  ctx.fillStyle = color;
  ctx.beginPath();
  roundRectPath(ctx, Math.round(x - w / 2), Math.round(y - h / 2), Math.round(w), Math.round(h), 3 * dpr);
  ctx.fill();
  ctx.fillStyle = contrastText(color);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x, y + 0.5 * dpr);
}

/** Self-contained trade-fill markers (chevron / bubble / count) over the plot. */
export class TradeMarkersPrimitive implements IPrimitive {
  private _trades: TradingTrade[] = [];
  private _colors: TradingColors;
  private _host: PrimitiveHost | null = null;

  public constructor(colors: TradingColors) { this._colors = colors; }
  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }
  public autoscaleInfo(): null { return null; }

  public setTrades(trades: TradingTrade[]): void { this._trades = trades; this._host?.requestUpdate(); }
  public setColors(colors: TradingColors): void { this._colors = colors; this._host?.requestUpdate(); }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    if (this._trades.length === 0) return;
    const dpr = rc.dpr;
    const groups = new Map<string, { index: number; sumPS: number; sumS: number; n: number; color: string }>();
    ctx.save();
    for (const t of this._trades) {
      const idx = snapToIndex(rc.dataLayer, Math.floor(t.timestamp / 1000));
      if (idx === undefined) continue;
      const x = Math.round(rc.timeScale.indexToX(idx) * dpr);
      const color = t.color ?? (t.side === 'buy' ? this._colors.buy : this._colors.sell);
      const variant = t.variant ?? 'chevron';
      if (variant === 'count') {
        const key = `${idx}:${t.side}`;
        let g = groups.get(key);
        if (g === undefined) { g = { index: idx, sumPS: 0, sumS: 0, n: 0, color }; groups.set(key, g); }
        g.sumPS += t.price * t.size; g.sumS += t.size; g.n += 1;
        continue;
      }
      const y = Math.round(rc.priceScale.priceToY(t.price) * dpr);
      if (variant === 'bubble') drawBubble(ctx, x, y, color, t.label ?? (t.side === 'buy' ? 'B' : 'S'), dpr);
      else drawChevron(ctx, x, y, t.side, color, dpr);
    }
    for (const g of groups.values()) {
      const vwap = g.sumS > 0 ? g.sumPS / g.sumS : 0;
      const x = Math.round(rc.timeScale.indexToX(g.index) * dpr);
      const y = Math.round(rc.priceScale.priceToY(vwap) * dpr);
      drawCount(ctx, x, y, g.n, g.color, dpr);
    }
    ctx.restore();
  }
}

interface Tracked<E> { entity: E; line: PriceLine; sig: string; }

export class TradingController {
  private readonly _host: TradingHost;
  private readonly _positions = new Map<string, Tracked<TradingPosition>>();
  private readonly _orders = new Map<string, Tracked<TradingOrder>>();
  private readonly _trades = new Map<string, TradingTrade>();
  private readonly _listeners = new Map<string, Set<(payload: unknown) => void>>();
  private readonly _dragPrev = new Map<string, number>();
  private _colors: TradingColors = { ...DEFAULT_TRADING_COLORS };
  private _markers: TradeMarkersPrimitive | null = null;
  private _ticks: TickSchedule | null;

  public constructor(host: TradingHost) {
    this._host = host;
    this._ticks = host.tickSchedule?.() ?? null;
    host.subscribeClick((externalId) => this._onClick(externalId));
    host.subscribeDrag(
      (externalId, price) => this._onDrag(externalId, price),
      (externalId, price) => this._onDragEnd(externalId, price),
    );
  }

  // ── events ────────────────────────────────────────────────────────────────
  public on(event: string, cb: (payload: unknown) => void): () => void {
    let set = this._listeners.get(event);
    if (set === undefined) { set = new Set(); this._listeners.set(event, set); }
    set.add(cb);
    return () => { this._listeners.get(event)?.delete(cb); };
  }

  public off(event: string, cb: (payload: unknown) => void): void {
    this._listeners.get(event)?.delete(cb);
  }

  private _emit<K extends keyof ChartEventMap & `trading:${string}`>(event: K, payload: ChartEventMap[K]): void {
    // A throwing listener runs out its turn here too: this is called from the
    // chart's pointer handling, and the mirror below is how `chart.on` hears it.
    dispatch(this._listeners.get(event), payload);
    // Mirror onto the chart's unified bus so `chart.on('trading:...')` works too.
    this._host.emit?.(event, payload);
  }

  // ── settings ────────────────────────────────────────────────────────────────
  public setSettings(settings: TradingSettings): void {
    if (settings.longColor !== undefined) this._colors.long = settings.longColor;
    if (settings.shortColor !== undefined) this._colors.short = settings.shortColor;
    if (settings.orderColor !== undefined) this._colors.order = settings.orderColor;
    if (settings.tpColor !== undefined) this._colors.tp = settings.tpColor;
    if (settings.slColor !== undefined) this._colors.sl = settings.slColor;
    if (settings.buyColor !== undefined) this._colors.buy = settings.buyColor;
    if (settings.sellColor !== undefined) this._colors.sell = settings.sellColor;
    // re-render existing entities with the new colors
    this.setPositions(this.getPositions());
    this.setOrders(this.getOrders());
    this._markers?.setColors(this._colors);
  }

  public getSettings(): TradingColors { return { ...this._colors }; }

  /**
   * Snap dragged order and bracket lines, and the price their modify events
   * carry, to the instrument's ticks. Null, the default, passes the pointer's
   * price through unrounded, as it always has. The host's own validation stays
   * authoritative either way; this only stops a drag previewing a price the
   * instrument cannot trade at. `Instrument.applyTo` and
   * `chart.setTickSchedule` set it, so call this after either to override it.
   */
  public setTickSchedule(schedule: TickSchedule | null): void {
    // Refused here, where the host made the mistake, rather than as a pointer
    // handler error on the first drag.
    if (schedule != null && typeof (schedule as Partial<TickSchedule>).round !== 'function') {
      throw new TypeError('chart.trading.setTickSchedule takes a schedule built with new TickSchedule(bands), or null');
    }
    this._ticks = schedule ?? null;
  }

  // ── data ──────────────────────────────────────────────────────────────────
  public setPositions(positions: readonly TradingPosition[]): void { this._sync(this._positions, positions, 'pos'); }
  public setOrders(orders: readonly TradingOrder[]): void { this._sync(this._orders, orders, 'ord'); }

  public setTrades(trades: readonly TradingTrade[]): void {
    this._trades.clear();
    for (const t of trades) this._trades.set(t.id, t);
    this._renderTrades();
  }

  public addTrade(trade: TradingTrade): void {
    this._trades.set(trade.id, trade);
    this._renderTrades();
  }

  public upsertOrder(order: TradingOrder): void {
    const next = this.getOrders().filter((o) => o.id !== order.id);
    next.push(order);
    this.setOrders(next);
  }

  public removeOrder(id: string): void {
    const next = this.getOrders().filter((o) => o.id !== id && o.parentId !== id);
    this.setOrders(next);
  }

  public syncState(payload: TradingSyncPayload): void {
    if (payload.positions !== undefined) this.setPositions(payload.positions);
    if (payload.orders !== undefined) this.setOrders(payload.orders);
    if (payload.trades !== undefined) this.setTrades(payload.trades);
  }

  /**
   * Refresh a position's P&L pill in place, without recreating its line: the
   * pill reads `pnlText`, then `pnlPercent` in brackets. Either one left out
   * keeps what the pill showed. The host formats both, since only it knows
   * the account's currency and how it rounds.
   */
  public updatePositionPnl(id: string, pnlText?: string, pnlPercent?: string): void;
  /**
   * The form that also takes the P&L as a number, which nothing ever read:
   * the pill shows `pnlText` and `pnlPercent` only.
   *
   * @deprecated Removed in 3.0.0. Leave the number out: `updatePositionPnl(id, pnlText, pnlPercent)` (since
   * 2.6.0) sets the same pill.
   */
  public updatePositionPnl(id: string, unrealizedPnl: number, pnlText?: string, pnlPercent?: string): void;
  public updatePositionPnl(id: string, ...args: (string | number | undefined)[]): void {
    const cur = this._positions.get(id);
    if (cur === undefined) return;
    // A text is a string. Anything else first is the unread number of the
    // deprecated form, including the undefined or null a script host passes
    // before it has one, and the texts follow it.
    const [pnlText, pnlPercent] = typeof args[0] === 'string' ? args : args.slice(1);
    if (typeof pnlText === 'string') cur.entity.pnlText = pnlText;
    if (typeof pnlPercent === 'string') cur.entity.pnlPercent = pnlPercent;
    cur.line.setLeftLabel(this._positionPill(cur.entity));
  }

  public getPositions(): TradingPosition[] { return [...this._positions.values()].map((t) => t.entity); }
  public getOrders(): TradingOrder[] { return [...this._orders.values()].map((t) => t.entity); }
  public getTrades(): TradingTrade[] { return [...this._trades.values()]; }

  public clear(): void {
    for (const t of this._positions.values()) this._host.removePrimitive(t.line);
    for (const t of this._orders.values()) this._host.removePrimitive(t.line);
    this._positions.clear();
    this._orders.clear();
    this._trades.clear();
    if (this._markers !== null) { this._host.removePrimitive(this._markers); this._markers = null; }
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  private _renderTrades(): void {
    if (this._markers === null) {
      this._markers = new TradeMarkersPrimitive(this._colors);
      this._host.addPrimitive(this._markers);
    }
    this._markers.setTrades(this.getTrades());
  }

  private _sync<E extends { id: string }>(map: Map<string, Tracked<E>>, list: readonly E[], kind: 'pos' | 'ord'): void {
    const seen = new Set<string>();
    for (const entity of list) {
      seen.add(entity.id);
      const opts = kind === 'pos'
        ? this._positionOpts(entity as unknown as TradingPosition)
        : this._orderOpts(entity as unknown as TradingOrder);
      const sig = this._sig(opts);
      const cur = map.get(entity.id);
      if (cur !== undefined && cur.sig === sig) {
        cur.entity = entity;
        cur.line.setPrice(opts.price);
        if (opts.leftLabel !== undefined) cur.line.setLeftLabel(opts.leftLabel);
      } else {
        if (cur !== undefined) this._host.removePrimitive(cur.line);
        const line = new PriceLine(opts);
        this._host.addPrimitive(line);
        map.set(entity.id, { entity, line, sig });
      }
    }
    for (const [id, cur] of map) {
      if (!seen.has(id)) { this._host.removePrimitive(cur.line); map.delete(id); }
    }
  }

  private _sig(o: PriceLineOptions): string {
    return `${o.color}|${o.dashed}|${o.closeButton === true}|${o.cursor ?? ''}|${o.leftLabel !== undefined}|${o.badge ?? ''}|${o.qty ?? ''}`;
  }

  /** Info segment for a position: live P&L text (side/size live in badge/qty). */
  private _positionPill(p: TradingPosition): string {
    if (p.pnlText === undefined) return '';
    return `${p.pnlText}${p.pnlPercent !== undefined ? ` (${p.pnlPercent})` : ''}`;
  }

  private _positionOpts(p: TradingPosition): PriceLineOptions {
    const lineOnly = p.variant === 'line-only';
    return {
      price: p.entryPrice,
      color: p.color ?? (p.side === 'long' ? this._colors.long : this._colors.short),
      lineWidth: 2,
      dashed: false,
      id: `pos:${p.id}`,
      badge: lineOnly ? undefined : p.side.toUpperCase(),
      qty: lineOnly ? undefined : p.size,
      leftLabel: lineOnly ? undefined : this._positionPill(p),
      closeButton: !lineOnly && p.readOnly !== true,
      extentFromRight: 0.3,
    } satisfies LooseOptional<PriceLineOptions> as PriceLineOptions; // a line-only position leaves its badge, size and pill undefined, which the line reads as absent
  }

  private _orderOpts(o: TradingOrder): PriceLineOptions {
    const lineOnly = o.variant === 'line-only';
    const draggable = !lineOnly && (o.draggable ?? o.readOnly !== true);
    const color = o.color ?? (o.bracketRole === 'tp' ? this._colors.tp
      : o.bracketRole === 'sl' ? this._colors.sl
        : this._colors.order);
    return {
      price: o.price,
      color,
      lineWidth: o.lineWidth ?? 1,
      dashed: (o.lineStyle ?? 'solid') !== 'solid',
      id: `ord:${o.id}`,
      badge: lineOnly ? undefined : (o.bracketRole ?? o.side).toUpperCase(),
      qty: lineOnly ? undefined : o.size,
      leftLabel: lineOnly || o.bracketRole !== undefined ? undefined : o.type.replace('_', ' ').toUpperCase(),
      closeButton: !lineOnly && o.readOnly !== true,
      extentFromRight: 0.3,
      cursor: draggable ? 'ns-resize' : undefined,
    } satisfies LooseOptional<PriceLineOptions> as PriceLineOptions; // undefined parts read as absent, as for a position
  }

  // ── interaction ─────────────────────────────────────────────────────────────
  private _onClick(externalId: string): void {
    if (externalId.endsWith(CLOSE_SUFFIX)) {
      const base = externalId.slice(0, -CLOSE_SUFFIX.length);
      if (base.startsWith('ord:')) {
        const id = base.slice(4);
        if (this._orders.has(id)) this._emit('trading:order_cancel', { orderId: id });
      } else if (base.startsWith('pos:')) {
        const id = base.slice(4);
        if (this._positions.has(id)) this._emit('trading:position_close', { positionId: id });
      }
      return;
    }
    // pill-body click
    if (externalId.startsWith('ord:')) {
      const cur = this._orders.get(externalId.slice(4));
      if (cur !== undefined) this._emit('trading:order_click', { order: cur.entity });
    } else if (externalId.startsWith('pos:')) {
      const cur = this._positions.get(externalId.slice(4));
      if (cur !== undefined) this._emit('trading:position_click', { position: cur.entity });
    }
  }

  private _onDrag(externalId: string, raw: number): void {
    if (!externalId.startsWith('ord:')) return;
    const price = this._ticks?.round(raw) ?? raw;
    const cur = this._orders.get(externalId.slice(4));
    if (cur === undefined) return;
    const id = externalId.slice(4);
    if (!this._dragPrev.has(id)) {
      this._dragPrev.set(id, cur.entity.price);
      cur.line.setDragGhost(cur.entity.price); // dimmed pre-drag reference line
    }
    cur.line.setPrice(price);
  }

  private _onDragEnd(externalId: string, raw: number): void {
    if (!externalId.startsWith('ord:')) return;
    const price = this._ticks?.round(raw) ?? raw;
    const id = externalId.slice(4);
    const cur = this._orders.get(id);
    if (cur === undefined) return;
    const previousPrice = this._dragPrev.get(id) ?? cur.entity.price;
    this._dragPrev.delete(id);
    cur.line.setDragGhost(null);
    cur.entity.price = price;
    cur.line.setPrice(price);
    if (cur.entity.bracketRole !== undefined) {
      this._emit('trading:bracket_modify', { parentId: cur.entity.parentId, bracketRole: cur.entity.bracketRole, newPrice: price });
    } else {
      this._emit('trading:order_modify', { orderId: id, newPrice: price, previousPrice });
    }
  }
}
