/**
 * Depth-of-market ladder (ARCHITECTURE.md §9.4). Docked to the right of the
 * plot, price-aligned to the price scale. Depth-agnostic: it reads the level
 * count from the payload (5 / 20 / 30 / 50 / 200) at runtime. Viewport
 * virtualization keeps a deep book at 60 fps; price-bucket aggregation compacts
 * deep books; a size heatmap highlights resting liquidity; and it degrades
 * gracefully to nothing when no depth is available.
 *
 * Pure helpers (capability / aggregation / virtualization) are split out for
 * unit testing; the primitive draws on the top (overlay) canvas so frequent
 * depth updates only repaint the cheap overlay.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, TickSchedule, ZOrder } from 'openalgo-charts';
import type { MarketDepth } from '../feed/types';
import { contrastText, withAlpha, parseColor } from '../render/pill';

export type LadderTier = 'none' | 'compact' | 'deep';

/** Capability tier from the live payload: drives graceful degradation. */
export function ladderCapability(depth: MarketDepth): LadderTier {
  const n = Math.max(depth.bids.length, depth.asks.length);
  if (n === 0) return 'none';
  return n <= 5 ? 'compact' : 'deep';
}

export interface LadderRow {
  price: number;
  bidQty: number;
  askQty: number;
}

/**
 * Only an object is a schedule. Anything else, a numeric string from a plain-JS
 * host included, keeps the arithmetic that predates schedules. A type guard,
 * because the website compiles this file with strict null checks off, where an
 * inline null check does not narrow the union.
 */
function isSchedule(tickSize: number | TickSchedule): tickSize is TickSchedule {
  return typeof tickSize === 'object' && tickSize !== null;
}

function scheduleError(where: string): TypeError {
  return new TypeError(`${where} takes a tick size or a schedule built with new TickSchedule(bands)`);
}

/**
 * A row price on a tick schedule: the level's nearest valid price, and with
 * grouping the nearest multiple of `n` ticks of that price's band, kept inside
 * the band so the row is still a price a click can trade at.
 */
function scheduleBucket(ticks: TickSchedule, n: number): (p: number) => number {
  return (p) => {
    const price = ticks.round(p), { bands } = ticks;
    if (n === 1 || !Number.isFinite(price)) return price;
    // A schedule has at least one band (its constructor refuses none), and i
    // walks down from the last to no lower than the first.
    let i = bands.length - 1;
    while (i > 0 && price < bands[i]!.from!) i--;
    const band = bands[i]!;
    const step = band.tick * n;
    const lower = band.from ?? -Infinity, upper = bands[i + 1]?.from ?? Infinity;
    // A boundary is valid in both bands, so it is where a group stops.
    return ticks.round(Math.min(Math.max(Math.round(price / step) * step, lower), upper));
  };
}

/**
 * Merge bids + asks into price rows, optionally bucketing every `groupBy` ticks
 * (price-step aggregation for deep books). Returns rows sorted high to low price.
 * Pass a `TickSchedule` in place of the tick size for an instrument whose tick
 * changes with price: each row is then a price its band allows, and a group
 * spans `groupBy` ticks of that band, so the step changes at a boundary.
 * There `groupBy` counts whole ticks, a fraction rounding down (2.5 groups by
 * 2), because a fractional group would label rows between the prices a band
 * allows. The constant path multiplies `tickSize * groupBy` as it always has.
 */
export function buildRows(depth: MarketDepth, tickSize: number | TickSchedule, groupBy = 1): LadderRow[] {
  let bucket: (p: number) => number;
  if (!isSchedule(tickSize)) {
    const step = tickSize * Math.max(1, groupBy);
    bucket = (p: number): number => Math.round(Math.round(p / step) * step * 1e8) / 1e8;
  } else {
    if (typeof tickSize.round !== 'function') throw scheduleError('buildRows');
    bucket = scheduleBucket(tickSize, groupBy > 1 ? Math.floor(groupBy) : 1);
  }
  const map = new Map<number, LadderRow>();
  const add = (price: number, qty: number, side: 'bid' | 'ask'): void => {
    const key = bucket(price);
    let row = map.get(key);
    if (row === undefined) { row = { price: key, bidQty: 0, askQty: 0 }; map.set(key, row); }
    if (side === 'bid') row.bidQty += qty; else row.askQty += qty;
  };
  for (const b of depth.bids) add(b.price, b.qty, 'bid');
  for (const a of depth.asks) add(a.price, a.qty, 'ask');
  return Array.from(map.values()).sort((x, y) => y.price - x.price);
}

/**
 * Virtualize: keep only rows whose y is inside the plot (± one row) and cap the
 * count to `maxRows` nearest the vertical centre (around the LTP). This is what
 * keeps a 200-level book cheap and readable.
 */
export function visibleRows(
  rows: readonly LadderRow[],
  priceToY: (p: number) => number,
  plotHeight: number,
  rowHeight: number,
  maxRows: number,
): LadderRow[] {
  const onScreen = rows.filter((r) => {
    const y = priceToY(r.price);
    return y >= -rowHeight && y <= plotHeight + rowHeight;
  });
  if (onScreen.length <= maxRows) return onScreen;
  // keep the maxRows closest to the centre y
  const centre = plotHeight / 2;
  return onScreen
    .map((r) => ({ r, d: Math.abs(priceToY(r.price) - centre) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, maxRows)
    .map((x) => x.r)
    .sort((a, b) => b.price - a.price);
}

export interface DomLadderOptions {
  tickSize: number;
  /**
   * Price-dependent ticks. When set, every row is a price the instrument can
   * trade at in its own band, `groupBy` counts whole ticks of that band (a
   * fraction rounds down), and `tickSize` is unused. Absent or null, rows step
   * by `tickSize`.
   */
  tickSchedule?: TickSchedule | null;
  /** Strip width in media px. */
  width: number;
  /**
   * Group every N ticks into one row (deep-book aggregation). With a
   * `tickSchedule`, N is whole ticks of each band: 2.5 groups by 2.
   */
  groupBy: number;
  /** Max rows drawn per frame (virtualization cap). */
  maxRows: number;
  rowHeight: number;
}

export const DEFAULT_DOM_LADDER_OPTIONS: DomLadderOptions = {
  tickSize: 0.05, width: 96, groupBy: 1, maxRows: 60, rowHeight: 14,
};

export class DomLadder implements IPrimitive {
  private _opts: DomLadderOptions;
  private _depth: MarketDepth | null = null;
  private _host: PrimitiveHost | null = null;
  private _rowHits: { price: number; y: number; side: 'bid' | 'ask' }[] = [];

  public constructor(options: Partial<DomLadderOptions> = {}) {
    this._opts = { ...DEFAULT_DOM_LADDER_OPTIONS, ...options };
    // Refused here rather than from inside a frame on the first draw.
    const ticks = this._opts.tickSchedule;
    if (ticks != null && typeof ticks.round !== 'function') throw scheduleError('DomLadder tickSchedule');
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }

  public setDepth(depth: MarketDepth): void {
    this._depth = depth;
    this._host?.requestUpdate();
  }

  public tier(): LadderTier {
    return this._depth === null ? 'none' : ladderCapability(this._depth);
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._rowHits = [];
    if (this._depth === null) return; // graceful degradation: no depth, no ladder
    const rows = visibleRows(
      buildRows(this._depth, this._opts.tickSchedule ?? this._opts.tickSize, this._opts.groupBy),
      (p) => rc.priceScale.priceToY(p),
      rc.plotHeight,
      this._opts.rowHeight,
      this._opts.maxRows,
    );
    if (rows.length === 0) return;

    const dpr = rc.dpr;
    const stripW = this._opts.width * dpr;
    const x0 = (rc.plotWidth - this._opts.width) * dpr;
    const mid = x0 + stripW / 2;
    const rowH = this._opts.rowHeight * dpr;
    let maxQty = 1;
    for (const r of rows) maxQty = Math.max(maxQty, r.bidQty, r.askQty);

    // theme-derived palette: heat from buy/sell, legible qty text on any theme
    const bid = parseColor(rc.theme.buy) ?? { r: 38, g: 166, b: 154, a: 1 };
    const ask = parseColor(rc.theme.sell) ?? { r: 239, g: 83, b: 80, a: 1 };
    const qtyText = withAlpha(contrastText(rc.theme.background === 'transparent' ? '#808080' : rc.theme.background), 0.9);

    ctx.save();
    // subtle inner edge so the ladder strip reads as a docked panel
    ctx.strokeStyle = withAlpha(rc.theme.axisLine, 0.6);
    ctx.lineWidth = Math.max(1, Math.round(dpr));
    ctx.beginPath();
    ctx.moveTo(Math.round(x0) + 0.5, 0);
    ctx.lineTo(Math.round(x0) + 0.5, Math.round(rc.plotHeight * dpr));
    ctx.stroke();

    ctx.font = `${9 * dpr}px system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    for (const r of rows) {
      const yc = rc.priceScale.priceToY(r.price) * dpr;
      const bidHover = rc.hoverId === `ladder-bid:${r.price}`;
      const askHover = rc.hoverId === `ladder-ask:${r.price}`;
      // bid heatmap + bar (left of mid)
      if (r.bidQty > 0) {
        ctx.fillStyle = `rgba(${bid.r},${bid.g},${bid.b},${0.15 + 0.5 * (r.bidQty / maxQty) + (bidHover ? 0.15 : 0)})`;
        const w = (stripW / 2) * (r.bidQty / maxQty);
        ctx.fillRect(mid - w, yc - rowH / 2, w, rowH - 1);
        ctx.fillStyle = qtyText;
        ctx.textAlign = 'left';
        ctx.fillText(String(r.bidQty), x0 + 2 * dpr, yc);
        this._rowHits.push({ price: r.price, y: rc.priceScale.priceToY(r.price), side: 'bid' });
      }
      // ask heatmap + bar (right of mid)
      if (r.askQty > 0) {
        ctx.fillStyle = `rgba(${ask.r},${ask.g},${ask.b},${0.15 + 0.5 * (r.askQty / maxQty) + (askHover ? 0.15 : 0)})`;
        const w = (stripW / 2) * (r.askQty / maxQty);
        ctx.fillRect(mid, yc - rowH / 2, w, rowH - 1);
        ctx.fillStyle = qtyText;
        ctx.textAlign = 'right';
        ctx.fillText(String(r.askQty), x0 + stripW - 2 * dpr, yc);
        this._rowHits.push({ price: r.price, y: rc.priceScale.priceToY(r.price), side: 'ask' });
      }
      // hovered row: outline the clickable half (place-order affordance)
      if (bidHover || askHover) {
        ctx.strokeStyle = bidHover ? withAlpha(rc.theme.buy, 0.9) : withAlpha(rc.theme.sell, 0.9);
        ctx.lineWidth = Math.max(1, Math.round(dpr));
        ctx.strokeRect(bidHover ? x0 + 0.5 : mid + 0.5, yc - rowH / 2 + 0.5, stripW / 2 - 1, rowH - 2);
      }
    }
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    if (this._depth === null) return null;
    const x0 = rc.plotWidth - this._opts.width;
    if (x < x0 || x > rc.plotWidth) return null;
    let best: { price: number; side: 'bid' | 'ask'; d: number } | null = null;
    for (const h of this._rowHits) {
      const d = Math.abs(h.y - y);
      if (d <= this._opts.rowHeight / 2 && (best === null || d < best.d)) best = { price: h.price, side: h.side, d };
    }
    if (best === null) return null;
    return { externalId: `ladder-${best.side}:${best.price}`, zOrder: 'top', distance: best.d, cursor: 'pointer' };
  }
}
