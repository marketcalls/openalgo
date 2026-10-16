/** Footprint columns, volume profiles and cluster ladders from classified trades. */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from 'openalgo-charts';
import { bucketPrice, valueArea, type FootprintBar, type FootprintCell } from './profile-model';
import { MAX_EMPTY_ROWS, diagonalImbalances, stackedImbalances } from './footprint';
import { footprintTextColor, readableTextColor, type FootprintTextColorMode } from './footprint-colors';
import { footprintSignals, type FootprintSignals, type FootprintZone, type FootprintZoneEnd } from './footprint-signals';
import { drawAuctions, drawFlip, drawVisibleProfile, drawZones, type OverlayColors } from './footprint-overlays';
import { sessionOpen, tpoLetter, type SessionWindow } from './market-profile';
import { DEFAULT_TIMEZONE } from '../feed/time';
import { parseColor, withAlpha } from '../render/pill';

export type FootprintStatRow = 'volume' | 'bidVolume' | 'askVolume' | 'delta' | 'minDelta' | 'maxDelta' | 'deltaPct' | 'cvd'
  | 'trades' | 'cumVolume' | 'cvdRatio' | 'session';
/**
 * `bidask` shades both sides by volume; `imbalance` leaves cells plain and fills
 * only diagonal imbalances, shading the candle body's rows; `delta`, `deltaPct`,
 * `volume`, `volumeDelta` and `deltaShadedVolume` print one value per row.
 * `deltaShadedVolume` (since 2.6.4) prints the row's volume on a cell coloured
 * and shaded by its delta.
 */
export type FootprintDisplayMode = 'bidask' | 'imbalance' | 'delta' | 'deltaPct' | 'volume' | 'volumeDelta' | 'deltaShadedVolume';
/** The zones `showZones` extends: stacked imbalances, multiple nodes and absorption. */
export type FootprintZoneGroup = 'stacked' | 'node' | 'absorption';
/** A zone that price came back to after it became active (since 2.6.4). */
export interface FootprintZoneAlert {
  zone: FootprintZone;
  /** Time of the bar whose range came back to the zone. */
  time: number;
}
export type FootprintCellStyle = 'heatmap' | 'profile' | 'ladder';
export type { FootprintTextColorMode } from './footprint-colors';

export interface FootprintOptions {
  /** Preferred full column width in media px, capped to the available bar slot. */
  cellWidth?: number;
  /** Fraction of the bar slot occupied by the column and candle. Default 0.9. */
  widthFactor: number;
  /** Effective price step (tickSize * rowTicks). Overrides bar.rowSize. */
  tickSize?: number;
  font: number;
  minTextHeight: number;
  textFade: number;
  displayMode: FootprintDisplayMode;
  /** Display quantities divided by this positive value; 1 shows raw units. Stats remain raw. */
  volumeDivisor: number;
  /** Abbreviate quantities to three significant figures (12.3K). False prints whole numbers. Default true. */
  compactNumbers: boolean;
  /** Intensity cells, volume-proportional bars, or square high-contrast cells. */
  cellStyle: FootprintCellStyle;
  /** Shade against each bar's busiest row, or against the busiest row on screen so clusters stand out. */
  intensityScope: 'bar' | 'visible';
  /** Text comparisons are independent of the cell background. */
  textColorMode: FootprintTextColorMode;
  textColor?: string;
  buyTextColor?: string;
  sellTextColor?: string;
  imbalanceRatio: number;
  imbalanceThreshold: number;
  /** Adjacent same-side imbalance run length. 0 disables brackets and stacked zones. */
  stackedImbalances: number;
  statsRows: readonly FootprintStatRow[];
  /** Ordered rows for a separate table below the footprints. Empty disables it (default). */
  tableRows: readonly FootprintStatRow[];
  /** Fixed table label column width in media px. Default 150. */
  tableLabelWidth: number;
  statsRowHeight: number;
  /** Fixed pane footer or labeled cards beneath each bar. */
  statsPosition: 'bottom' | 'bar';
  /** Cumulative delta preceding the supplied bars, for a rolling window. */
  cvdOffset: number;
  /** `'session'` restarts cumulative delta and cumulative volume at each session open. */
  cvdReset: 'none' | 'session';
  /** Session that letters and resets count from; omitted means local midnight. */
  sessionWindow?: SessionWindow;
  /** IANA zone for the session calendar; defaults to Asia/Kolkata. */
  timezone?: string;
  /** Length of one session-letter period in minutes. Default 30. */
  tpoMinutes: number;
  /** Draw real OHLC if supplied; legacy bars show a neutral range line. */
  showCandle: boolean;
  showPoc: boolean;
  pocStyle: 'marker' | 'outline';
  showValueArea: boolean;
  /** Fraction of volume in the contiguous value area around the POC. */
  valueAreaPercent: number;
  valueAreaColor?: string;
  /** Highlight the POC when this many consecutive bars share it. 0 (default) disables. */
  multipleNodeBars: number;
  nodeColor: string;
  /** Outline a big limit order of at least this many average cells. 0 (default) disables. */
  bigOrderMultiple: number;
  bigOrderColor: string;
  /** Band rows where bid and ask both reach this many average cells. 0 (default) disables. */
  absorptionMultiple: number;
  absorptionColor: string;
  /** Bars the average cell is taken over. Default 10. */
  signalLookback: number;
  /** Rows from the high or low a big order or absorption must be within. Default 3. */
  nearExtremeRows: number;
  /** Mark an aggressive delta flip after this many opposite bars. 0 (default) disables. */
  flipBars: number;
  flipMinDeltaPct: number;
  /** Extend stacked imbalances, multiple nodes and absorption to the right as zones. Default false. */
  showZones: boolean;
  /** Which of them `showZones` extends and alerts on (since 2.6.4). Default all three. */
  zoneKinds: readonly FootprintZoneGroup[];
  zoneEnd: FootprintZoneEnd;
  zoneActiveAfter: number;
  /** Zones start only in the newest this many bars (since 2.6.4). 0, the default, takes every bar. */
  zoneLookback: number;
  /** Dash-dot line at a high or low that traded on both bid and ask. Default false. */
  showUnfinishedAuctions: boolean;
  auctionHighColor?: string;
  auctionLowColor?: string;
  /** Bar delta printed under each column. Default false. */
  showDeltaLabels: boolean;
  /** Box the delta label when it disagrees with the bar's direction. Default false. */
  markDivergence: boolean;
  divergenceColor: string;
  /** Volume at price of the visible bars against the left edge. Default false. */
  showVisibleProfile: boolean;
  profileWidth: number;
  /**
   * Draw a 0 x 0 row at every row step a bar's trades skipped, so each column
   * spans its whole range. Display only: imbalances, the POC, value area and
   * signals still read the traded rows. Default true.
   */
  showEmptyRows: boolean;
  /** Fill the newest bar's last-price row with this colour. Omitted draws nothing. */
  lastPriceColor?: string;
  /** The newest bar is still forming, so it cannot close a zone or set an unfinished auction. Default true. */
  formingLastBar: boolean;
  buyColor?: string;
  sellColor?: string;
  // Each colour below is optional (since 2.6.4); omitted, it keeps the colour it
  // had before: the buy or sell colour, or the chart theme's background.
  /** Imbalanced cells, stacked imbalance brackets and stacked zones. */
  imbalanceBuyColor?: string;
  imbalanceSellColor?: string;
  /** Cells in the `volume` display mode, which otherwise take the colour of the side that traded more. */
  volumeColor?: string;
  /** The candle beside each column, and the body rows the `imbalance` mode shades. */
  candleUpColor?: string;
  candleDownColor?: string;
  /** Ask and bid bars of the visible-range profile. */
  profileAskColor?: string;
  profileBidColor?: string;
  /** Session letters in the table and the statistics cards. */
  sessionColor?: string;
  /** Background of the statistics table. */
  tableBackground?: string;
  pocColor: string;
  radius: number;
}

export const DEFAULT_FOOTPRINT_OPTIONS: FootprintOptions = {
  widthFactor: 0.9, font: 10, minTextHeight: 11, textFade: 4,
  displayMode: 'bidask', volumeDivisor: 1, compactNumbers: true, cellStyle: 'heatmap', intensityScope: 'bar', textColorMode: 'contrast',
  imbalanceRatio: 3, imbalanceThreshold: 0, stackedImbalances: 3,
  statsRows: [], tableRows: [], tableLabelWidth: 150, statsRowHeight: 15,
  statsPosition: 'bottom', cvdOffset: 0, cvdReset: 'none', tpoMinutes: 30, showCandle: true, showPoc: true,
  pocStyle: 'marker', pocColor: '#f0a020', showValueArea: false, valueAreaPercent: 0.7, radius: 2,
  multipleNodeBars: 0, nodeColor: '#e8c547', bigOrderMultiple: 0, bigOrderColor: '#2ea8ff',
  absorptionMultiple: 0, absorptionColor: '#a98bf0', signalLookback: 10, nearExtremeRows: 3,
  flipBars: 0, flipMinDeltaPct: 8, showZones: false, zoneKinds: ['stacked', 'node', 'absorption'], zoneEnd: 'closeInside', zoneActiveAfter: 1, zoneLookback: 0,
  showUnfinishedAuctions: false, showDeltaLabels: false, markDivergence: false, divergenceColor: '#f2a33a',
  showVisibleProfile: false, profileWidth: 100, showEmptyRows: true, formingLastBar: true,
};

export interface FootprintBarStats {
  time: number;
  volume: number;
  bidVolume: number;
  askVolume: number;
  delta: number;
  /** Intrabar running delta extremes, including initial zero; null without trade-path metadata. */
  minDelta: number | null;
  maxDelta: number | null;
  deltaPct: number;
  cvd: number;
  /** Cumulative volume over the loaded bars, restarting with `cvdReset: 'session'`. */
  cumVolume: number;
  /** Cumulative delta divided by cumulative volume; 0 before any volume. */
  cvdRatio: number;
  /** Session letter of the period the bar opens in: A for the first `tpoMinutes`, and so on. */
  session: string;
  /** Null when a legacy input does not include an actual trade count. */
  trades: number | null;
  poc: number;
  vah: number;
  val: number;
}

export interface FootprintHover {
  time: number;
  /** The exact bucket price; null over a statistics card/table. */
  price: number | null;
  cell: FootprintCell | null;
  stats: FootprintBarStats;
}

/** Three significant figures, preserving fractional quantities and suffix rollover. */
export function compactVol(v: number): string {
  if (!Number.isFinite(v)) return '-';
  const rounded = Number(v.toPrecision(3));
  const a = Math.abs(rounded);
  const [suffix, div] = a >= 1e9 ? ['B', 1e9] : a >= 1e6 ? ['M', 1e6] : a >= 1e3 ? ['K', 1e3] : ['', 1];
  return String(Number((rounded / div).toPrecision(3))) + suffix;
}

function mix(a: string, b: string, t: number): string {
  const ca = parseColor(a), cb = parseColor(b);
  if (ca === null || cb === null) return b;
  const k = Math.max(0, Math.min(1, t));
  return `rgb(${Math.round(ca.r + (cb.r - ca.r) * k)},${Math.round(ca.g + (cb.g - ca.g) * k)},${Math.round(ca.b + (cb.b - ca.b) * k)})`;
}

/** The options with their arrays copied, so a caller's array never changes them. */
function copyOptions(o: FootprintOptions): FootprintOptions {
  return { ...o, statsRows: [...o.statsRows], tableRows: [...o.tableRows], zoneKinds: [...o.zoneKinds] };
}

/** Midnight to midnight: the session when no window is given. */
const WHOLE_DAY: SessionWindow = { startMinute: 0, endMinute: 0 };
const TWO_SIDED = new Set<FootprintDisplayMode>(['bidask', 'imbalance']);
const ZONE_GROUP: Record<FootprintZone['kind'], FootprintZoneGroup> = { stackedBuy: 'stacked', stackedSell: 'stacked', node: 'node', absorption: 'absorption' };

/** A bar's cells, highest first, with a zero row at every row step the trades skipped. */
function withEmptyRows(cells: readonly FootprintCell[], step: number): readonly FootprintCell[] {
  if (!(step > 0) || cells.length < 2) return cells;
  const out: FootprintCell[] = [];
  for (let i = 0; i < cells.length; i++) {
    const cell = cells[i]!, next = cells[i + 1];
    out.push(cell);
    if (next === undefined) break;
    const missing = Math.round((cell.price - next.price) / step) - 1;
    if (missing > MAX_EMPTY_ROWS) continue;
    for (let k = 1; k <= missing; k++) out.push({ price: bucketPrice(cell.price - k * step, step), bidVol: 0, askVol: 0 });
  }
  return out;
}

interface RowHit { cell: FootprintCell; top: number; bottom: number }
interface Column {
  bar: FootprintBar;
  stats: FootprintBarStats;
  index: number;
  x: number;
  x0: number;
  width: number;
  rowSize: number;
  rows: RowHit[];
  card?: { top: number; bottom: number };
  table?: { left: number; right: number; top: number; bottom: number };
}
interface Palette { buy: string; sell: string; bg: string; imbBuy: string; imbSell: string }
const STAT_LABEL: Record<FootprintStatRow, string> = {
  volume: 'Volume', bidVolume: 'Bid Volume', askVolume: 'Ask Volume', delta: 'Delta',
  minDelta: 'Min Delta', maxDelta: 'Max Delta', deltaPct: 'Delta %', cvd: 'CVD', trades: 'Trades',
  cumVolume: 'Cum Volume', cvdRatio: 'CVD / Volume', session: 'Session',
};
const TABLE_LABEL = { ...STAT_LABEL, volume: 'Total Volume', bidVolume: 'Total Bid Volume', askVolume: 'Total Ask Volume',
  cvd: 'Cumulative Delta', cumVolume: 'Cumulative Volume', cvdRatio: 'Cum. Delta / Volume', session: 'Session Letter' };
const unsignedRow = (row: FootprintStatRow): boolean => row === 'volume' || row === 'trades' || row === 'bidVolume' || row === 'askVolume' || row === 'cumVolume';

export class Footprint implements IPrimitive {
  private _bars: FootprintBar[] = [];
  private _opts: FootprintOptions;
  private _host: PrimitiveHost | null = null;
  private _stats: FootprintBarStats[] = [];
  private _signals: FootprintSignals = { bars: [], zones: [], auctions: [] };
  /** Only visible painted rows/cards are interactive, in media pixels. */
  private _cols: Column[] = [];
  private _rc: PrimitiveRenderContext | null = null;
  private _inferredStep = 0;
  private _primed = false;
  /** Time of the newest bar at the last `setBars`: touches from it on are live. */
  private _liveFrom = -Infinity;
  private readonly _alertHandlers = new Set<(alert: FootprintZoneAlert) => void>();
  /** Zones already reported or already touched when first seen, by kind, origin and low. */
  private readonly _alerted = new Set<string>();

  public constructor(opts: Partial<FootprintOptions> = {}) {
    this._opts = copyOptions({ ...DEFAULT_FOOTPRINT_OPTIONS, ...opts });
    this._validateOptions(this._opts);
  }
  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; this._rc = null; this._cols = []; }
  public zOrder(): ZOrder { return 'normal'; }

  private _validateOptions(o: FootprintOptions): void {
    for (const v of [o.widthFactor, o.font, o.statsRowHeight, o.tableLabelWidth, o.imbalanceRatio, o.volumeDivisor, o.tpoMinutes, o.profileWidth]) {
      if (!Number.isFinite(v) || v <= 0) throw new RangeError('Footprint dimensions and ratio must be positive and finite');
    }
    for (const v of [o.radius, o.minTextHeight, o.textFade, o.imbalanceThreshold]) {
      if (!Number.isFinite(v) || v < 0) throw new RangeError('Footprint thresholds and radius must be nonnegative and finite');
    }
    for (const v of [o.cellWidth, o.tickSize]) {
      if (v !== undefined && (!Number.isFinite(v) || v <= 0)) throw new RangeError('Footprint width and row step must be positive and finite');
    }
    if (!Number.isSafeInteger(o.stackedImbalances) || o.stackedImbalances < 0) throw new RangeError('Footprint stack length must be a nonnegative integer');
    if (!Number.isFinite(o.cvdOffset)) throw new RangeError('Footprint CVD offset must be finite');
    if (!Number.isFinite(o.valueAreaPercent) || o.valueAreaPercent <= 0 || o.valueAreaPercent > 1) throw new RangeError('Footprint value area must be in (0, 1]');
    for (const rows of [o.statsRows, o.tableRows]) {
      if (rows.some(row => !Object.prototype.hasOwnProperty.call(STAT_LABEL, row)) || new Set(rows).size !== rows.length) throw new RangeError('Footprint statistics rows must be known and unique');
    }
    if (o.zoneKinds.some(kind => kind !== 'stacked' && kind !== 'node' && kind !== 'absorption') || new Set(o.zoneKinds).size !== o.zoneKinds.length) {
      throw new RangeError('Footprint zone kinds must be stacked, node or absorption, each once');
    }
    // The signal options share one validator with the pure function.
    footprintSignals([], this._signalOptions(o));
  }

  private _signalOptions(o: FootprintOptions): Parameters<typeof footprintSignals>[1] {
    return {
      imbalanceRatio: o.imbalanceRatio, imbalanceThreshold: o.imbalanceThreshold, stackedImbalances: o.stackedImbalances,
      multipleNodeBars: o.multipleNodeBars, bigOrderMultiple: o.bigOrderMultiple, absorptionMultiple: o.absorptionMultiple,
      signalLookback: o.signalLookback, nearExtremeRows: o.nearExtremeRows, flipBars: o.flipBars, flipMinDeltaPct: o.flipMinDeltaPct,
      zoneEnd: o.zoneEnd, zoneActiveAfter: o.zoneActiveAfter, zoneLookback: o.zoneLookback, formingLastBar: o.formingLastBar,
    };
  }

  public setBars(bars: readonly FootprintBar[]): void {
    this._bars = bars.map(bar => ({ ...bar, cells: bar.cells.map(cell => ({ ...cell })).sort((a, b) => b.price - a.price) }));
    let step = Infinity;
    for (const bar of this._bars) {
      if (bar.rowSize !== undefined && bar.rowSize > 0) step = Math.min(step, bar.rowSize);
      for (let i = 1; i < bar.cells.length; i++) {
        const gap = bar.cells[i - 1]!.price - bar.cells[i]!.price;
        if (gap > 0) step = Math.min(step, gap);
      }
    }
    this._inferredStep = Number.isFinite(step) ? step : 0;
    this._cols = [];
    this._recomputeStats();
    this._reportTouches(true);
    this._host?.requestUpdate();
  }

  public setOptions(patch: Partial<FootprintOptions>): void {
    const next = { ...this._opts, ...patch };
    this._validateOptions(next);
    this._opts = copyOptions(next);
    this._cols = [];
    this._recomputeStats();
    // New options can make new zones out of old bars: nothing traded into them now.
    this._reportTouches(false);
    this._host?.requestUpdate();
  }
  public options(): FootprintOptions { return copyOptions(this._opts); }

  /**
   * Called once for each zone that `showZones` extends (so nothing is reported
   * while it is off) when a bar's range comes back to it after it became active
   * (since 2.6.4), the moment to raise an alert or play a sound. The first bars
   * a footprint is given are history and report nothing; each later `setBars`
   * is read as the live tail, so a touch in the bar that was newest at the
   * previous call, or in any bar after it, is reported. `setBars([])`, or bars
   * that start again from an older bar, begin a new history. Returns the
   * unsubscribe.
   */
  public onZoneAlert(handler: (alert: FootprintZoneAlert) => void): () => void {
    this._alertHandlers.add(handler);
    return () => { this._alertHandlers.delete(handler); };
  }

  private _reportTouches(live: boolean): void {
    const o = this._opts, newest = this._bars[this._bars.length - 1]?.time;
    // No bars, or bars ending before the last ones did, are another dataset: its touches are history.
    if (newest === undefined || newest < this._liveFrom) { this._primed = false; this._alerted.clear(); this._liveFrom = -Infinity; }
    if (newest === undefined) return;
    const report = live && this._primed, from = this._liveFrom;
    if (live) { this._primed = true; this._liveFrom = newest; }
    if (!o.showZones) return;
    for (const zone of this._signals.zones) {
      if (zone.touchTime === null || !o.zoneKinds.includes(ZONE_GROUP[zone.kind])) continue;
      const key = `${zone.kind}|${zone.time}|${zone.low}`;
      if (this._alerted.has(key)) continue;
      this._alerted.add(key);
      // A touch is news when it is in the bar that was still forming at the last call, or later.
      if (!report || zone.touchTime < from) continue;
      for (const handler of [...this._alertHandlers]) {
        try { handler({ zone: { ...zone }, time: zone.touchTime }); } catch (error) { queueMicrotask(() => { throw error; }); }
      }
    }
  }
  public stats(): readonly FootprintBarStats[] { return this._stats; }
  /**
   * Multiple nodes, big orders, absorption, flips, divergence, zones and
   * unfinished auctions for the loaded bars, under the current options. Zones
   * carry `activeTime` and `endTime`, so a host can raise its own alerts.
   */
  public signals(): FootprintSignals { return this._signals; }
  private _step(bar: FootprintBar): number { return this._opts.tickSize ?? bar.rowSize ?? this._inferredStep; }

  public autoscaleInfo(): { min: number; max: number } | null {
    let min = Infinity, max = -Infinity;
    for (const bar of this._bars) {
      const half = this._step(bar) / 2;
      for (const cell of bar.cells) { min = Math.min(min, cell.price - half); max = Math.max(max, cell.price + half); }
      if (this._opts.showCandle) {
        if (bar.low !== undefined) min = Math.min(min, bar.low);
        if (bar.high !== undefined) max = Math.max(max, bar.high);
      }
    }
    return Number.isFinite(min) ? { min, max } : null;
  }

  private _recomputeStats(): void {
    const o = this._opts;
    const window = o.sessionWindow ?? WHOLE_DAY, zone = o.timezone ?? DEFAULT_TIMEZONE;
    const sessions = o.cvdReset === 'session' || o.statsRows.includes('session') || o.tableRows.includes('session');
    let cvd = o.cvdOffset, cumVolume = 0, opened = NaN;
    this._stats = this._bars.map(bar => {
      const totals = bar.cells.map(cell => cell.bidVol + cell.askVol);
      const volume = totals.reduce((sum, v) => sum + v, 0);
      const bidVolume = bar.cells.reduce((sum, cell) => sum + cell.bidVol, 0);
      const askVolume = bar.cells.reduce((sum, cell) => sum + cell.askVol, 0);
      const va = valueArea(totals, volume * o.valueAreaPercent);
      const open = sessions ? sessionOpen(bar.time, window, zone) : 0;
      if (o.cvdReset === 'session' && open !== opened && !Number.isNaN(opened)) { cvd = 0; cumVolume = 0; }
      opened = open;
      cvd += bar.delta;
      cumVolume += volume;
      return { time: bar.time, volume, bidVolume, askVolume, delta: bar.delta,
        minDelta: bar.minDelta ?? null, maxDelta: bar.maxDelta ?? null, deltaPct: volume > 0 ? bar.delta / volume * 100 : 0,
        cvd, cumVolume, cvdRatio: cumVolume > 0 ? cvd / cumVolume : 0,
        session: sessions ? tpoLetter(Math.floor((bar.time - open) / (o.tpoMinutes * 60))) : '-',
        trades: bar.tradeCount ?? null, poc: bar.cells[va.poc]?.price ?? 0,
        vah: bar.cells[va.upper]?.price ?? 0, val: bar.cells[va.lower]?.price ?? 0 };
    });
    this._signals = footprintSignals(this._bars, this._signalOptions(o));
  }

  /** Price boundaries, not a minimum pixel size: tiny rows must never overlap. */
  private _bounds(price: number, step: number, rc: PrimitiveRenderContext): { top: number; bottom: number } {
    const y = rc.priceScale.priceToY(price);
    if (!(step > 0)) return { top: y - 8, bottom: y + 8 };
    const a = rc.priceScale.priceToY(price - step / 2), b = rc.priceScale.priceToY(price + step / 2);
    return { top: Math.min(a, b), bottom: Math.max(a, b) };
  }

  /** Quantity text: compact by default, otherwise whole numbers with separators. */
  private _format(v: number): string {
    if (this._opts.compactNumbers || !Number.isFinite(v)) return compactVol(v);
    return (Math.sign(v) * Math.round(Math.abs(v))).toLocaleString('en-US');
  }

  /** The value a cell is shaded by in a single-value mode, and the peak it is measured against. */
  private _cellMeasure(cell: FootprintCell): number {
    const mode = this._opts.displayMode, vol = cell.bidVol + cell.askVol, d = cell.askVol - cell.bidVol;
    if (mode === 'volume') return vol;
    if (mode === 'deltaPct') return vol > 0 ? Math.abs(d) / vol : 0;
    if (mode === 'delta' || mode === 'volumeDelta' || mode === 'deltaShadedVolume') return Math.abs(d);
    return Math.max(cell.bidVol, cell.askVol);
  }

  private _peak(bar: FootprintBar): number {
    if (this._opts.displayMode === 'deltaPct') return 1;
    let peak = 0;
    for (const cell of bar.cells) peak = Math.max(peak, this._cellMeasure(cell));
    return peak;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._rc = rc;
    this._cols = [];
    if (this._bars.length === 0 || rc.plotHeight <= 0 || rc.plotWidth <= 0) return;
    const o = this._opts, dpr = rc.dpr;
    const buy = o.buyColor ?? rc.theme.upColor, sell = o.sellColor ?? rc.theme.downColor;
    const palette: Palette = { buy, sell, bg: rc.theme.background, imbBuy: o.imbalanceBuyColor ?? buy, imbSell: o.imbalanceSellColor ?? sell };
    const slot = rc.timeScale.barSpacing;
    const outerWidth = Math.max(0.1, Math.min(o.cellWidth ?? slot * o.widthFactor, slot * 0.96));
    const gutter = o.showCandle && outerWidth >= 20 ? Math.min(9, outerWidth * 0.15) : 0;
    const width = Math.max(0.1, outerWidth - gutter);
    const tableRows = o.tableRows.length ? o.tableRows : o.statsPosition === 'bottom' ? o.statsRows : [];
    const statsH = Math.min(rc.plotHeight, tableRows.length * o.statsRowHeight);
    const cellBottom = rc.plotHeight - statsH;
    const range = rc.timeScale.visibleRange();
    // setBars recomputes the statistics, so there is one per bar.
    for (let i = 0; i < this._bars.length; i++) {
      const bar = this._bars[i]!;
      if (!bar.cells.length) continue;
      const index = rc.dataLayer.timeToIndex(bar.time);
      if (index === undefined || index < range.from - 1 || index > range.to + 1) continue;
      const x0 = rc.timeScale.indexToX(index) - outerWidth / 2 + gutter;
      if (x0 + width < 0 || x0 > rc.plotWidth) continue;
      this._cols.push({ bar, stats: this._stats[i]!, index: i, x: x0 + width / 2, x0, width, rowSize: this._step(bar), rows: [] });
    }
    let screenPeak = 0;
    if (o.intensityScope === 'visible') for (const col of this._cols) screenPeak = Math.max(screenPeak, this._peak(col.bar));
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, rc.plotWidth * dpr, rc.plotHeight * dpr); ctx.clip();
    ctx.textBaseline = 'middle';
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, rc.plotWidth * dpr, cellBottom * dpr); ctx.clip();
    this._drawAcross(ctx, rc, palette, cellBottom);
    for (const col of this._cols) this._drawColumn(ctx, rc, col, gutter, palette, cellBottom, screenPeak);
    for (const col of this._cols) this._drawUnder(ctx, rc, col, palette, cellBottom);
    if (o.showVisibleProfile) {
      drawVisibleProfile(ctx, rc, this._cols.map(col => col.bar), this._cols[0]?.rowSize ?? 0, o.profileWidth, cellBottom,
        o.profileAskColor ?? palette.buy, o.profileBidColor ?? palette.sell, palette.bg, o.textColor ?? rc.theme.axisText, o.pocColor, v => this._format(v / o.volumeDivisor), Math.max(8, o.font - 1));
    }
    ctx.restore();
    if (o.statsRows.length && o.statsPosition === 'bar') {
      for (const col of this._cols) this._drawCard(ctx, rc, col, palette, cellBottom);
    }
    if (tableRows.length) this._drawFooter(ctx, rc, palette, statsH, tableRows);
    ctx.restore();
  }

  /** Zones and unfinished auctions sit behind the columns. */
  private _drawAcross(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, p: Palette, bottom: number): void {
    const o = this._opts;
    const colors: OverlayColors = { stackedBuy: p.imbBuy, stackedSell: p.imbSell, node: o.nodeColor, absorption: o.absorptionColor,
      auctionHigh: o.auctionHighColor ?? p.buy, auctionLow: o.auctionLowColor ?? p.sell };
    if (o.showZones) drawZones(ctx, rc, this._signals.zones.filter(zone => o.zoneKinds.includes(ZONE_GROUP[zone.kind])), colors, bottom);
    if (!o.showUnfinishedAuctions) return;
    const byTime = new Map(this._bars.map(bar => [bar.time, bar]));
    drawAuctions(ctx, rc, this._signals.auctions, colors, (auction) => {
      const bar = byTime.get(auction.time)!, step = this._step(bar);
      const cell = auction.side === 'high' ? bar.cells[0] : bar.cells[bar.cells.length - 1];
      const bounds = this._bounds(cell?.price ?? auction.price, step, rc);
      return auction.side === 'high' ? bounds.top : bounds.bottom;
    });
  }

  /** Imbalance-mode fill: stronger as the ratio passes two and three times the threshold, full against zero. */
  private _imbalanceStrength(volume: number, opposing: number): number {
    if (opposing <= 0) return 1;
    const ratio = volume / opposing, r = this._opts.imbalanceRatio;
    return ratio >= 3 * r ? 1 : ratio >= 2 * r ? 0.8 : 0.6;
  }

  private _drawColumn(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, col: Column,
    gutter: number, p: Palette, cellBottom: number, screenPeak: number): void {
    const o = this._opts, dpr = rc.dpr;
    const { bar, stats } = col;
    const { buy, sell, bg, imbBuy, imbSell } = p;
    const width = col.width * dpr, half = width / 2, x0 = col.x0 * dpr, center = col.x * dpr;
    const cells = o.showEmptyRows ? withEmptyRows(bar.cells, col.rowSize) : bar.cells;
    const flags = diagonalImbalances(bar.cells, o.imbalanceRatio, col.rowSize || undefined, o.imbalanceThreshold);
    // Without a row size every bar has one row, so nothing faces anything.
    const byPrice = new Map(col.rowSize > 0 ? bar.cells.map(cell => [bucketPrice(cell.price, col.rowSize), cell] as const) : []);
    const buys = new Set(flags.filter(flag => flag.side === 'buy').map(flag => flag.price));
    const sells = new Set(flags.filter(flag => flag.side === 'sell').map(flag => flag.price));
    const twoSided = TWO_SIDED.has(o.displayMode);
    const peak = o.intensityScope === 'visible' ? screenPeak : this._peak(bar);
    let textPeak = 0;
    for (const cell of bar.cells) textPeak = Math.max(textPeak, twoSided ? Math.max(cell.bidVol, cell.askVol) : cell.bidVol + cell.askVol);
    const signal = this._signals.bars[col.index];
    const body = this._bodyRows(bar, cells, col.rowSize);
    const candle = bar.open !== undefined && bar.close !== undefined && bar.close < bar.open ? o.candleDownColor ?? sell : o.candleUpColor ?? buy;
    const lastRow = o.lastPriceColor !== undefined && col.index === this._bars.length - 1 && bar.close !== undefined
      ? this._rowOf(bar, bar.close, col.rowSize) : null;
    if (gutter > 0) this._drawCandle(ctx, rc, col, gutter, o.candleUpColor ?? buy, o.candleDownColor ?? sell);
    // The volume each imbalance was measured against: the diagonal row's, or zero across an untraded row.
    const facing = (price: number, below: boolean): number => {
      const other = byPrice.get(bucketPrice(price + (below ? -col.rowSize : col.rowSize), col.rowSize));
      return other === undefined ? 0 : below ? other.bidVol : other.askVol;
    };
    cells.forEach((cell) => {
      const bounds = this._bounds(cell.price, col.rowSize, rc);
      if (bounds.bottom <= 0 || bounds.top >= cellBottom) return;
      col.rows.push({ cell, top: Math.max(0, bounds.top), bottom: Math.min(cellBottom, bounds.bottom) });
      const top = bounds.top * dpr, rowH = (bounds.bottom - bounds.top) * dpr;
      const h = Math.max(0, rowH - Math.min(dpr, rowH * 0.1));
      const textAlpha = Math.max(0, Math.min(1, ((bounds.bottom - bounds.top) - o.minTextHeight) / Math.max(1, o.textFade) + 1));
      ctx.font = `${o.font * dpr}px ui-monospace, SFMono-Regular, Menlo, monospace`;
      if (twoSided) {
        const gap = Math.min(dpr, half * 0.08), w = half - gap;
        let bidFill: string | undefined, askFill: string | undefined;
        if (o.displayMode === 'imbalance') {
          // Plain cells: only imbalances are coloured, and the candle body's rows are lightly shaded.
          const plain = body.has(cell.price) ? mix(bg, candle, 0.18) : bg;
          bidFill = sells.has(cell.price) ? mix(bg, imbSell, this._imbalanceStrength(cell.bidVol, facing(cell.price, false))) : plain;
          askFill = buys.has(cell.price) ? mix(bg, imbBuy, this._imbalanceStrength(cell.askVol, facing(cell.price, true))) : plain;
        }
        const bidHot = sells.has(cell.price), askHot = buys.has(cell.price);
        this._cell(ctx, rc, cell, x0, top, w, h, cell.bidVol, peak, textPeak, bidHot ? imbSell : sell, buy, sell, bg, bidHot, textAlpha, 'bid', bidFill);
        this._cell(ctx, rc, cell, center + gap, top, w, h, cell.askVol, peak, textPeak, askHot ? imbBuy : buy, buy, sell, bg, askHot, textAlpha, 'ask', askFill);
      } else {
        const direction = cell.askVol - cell.bidVol, vol = cell.bidVol + cell.askVol;
        const shade = this._cellMeasure(cell) * (o.displayMode === 'volume' ? 1 : Math.sign(direction) || 1);
        const label = o.displayMode === 'deltaPct' ? `${vol > 0 ? Math.round(direction / vol * 100) : 0}%`
          : o.displayMode === 'volumeDelta' ? `${this._format(vol / o.volumeDivisor)} x ${this._format(direction / o.volumeDivisor)}`
            : this._format((o.displayMode === 'delta' ? direction : vol) / o.volumeDivisor);
        const hot = direction > 0 ? buys.has(cell.price) : direction < 0 && sells.has(cell.price);
        const color = hot ? (direction > 0 ? imbBuy : imbSell)
          : o.displayMode === 'volume' && o.volumeColor !== undefined ? o.volumeColor
            : direction > 0 ? buy : direction < 0 ? sell : mix(buy, sell, 0.5);
        this._cell(ctx, rc, cell, x0, top, width, h, shade, peak, textPeak, color, buy, sell, bg, hot, textAlpha, 'single', undefined, label);
      }
      if (signal?.node && cell.price === stats.poc) { ctx.fillStyle = withAlpha(o.nodeColor, 0.35); ctx.fillRect(x0, top, width, h); }
      if (lastRow === cell.price) { ctx.fillStyle = withAlpha(o.lastPriceColor!, 0.45); ctx.fillRect(x0, top, width, h); }
      if (o.showPoc && cell.price === stats.poc) {
        if (o.pocStyle === 'outline') {
          ctx.strokeStyle = o.pocColor; ctx.lineWidth = Math.max(1, dpr);
          ctx.strokeRect(x0, top + dpr / 2, width, Math.max(0, h - dpr));
        } else { ctx.fillStyle = o.pocColor; ctx.fillRect(x0 - 2 * dpr, top, 2 * dpr, h); }
      }
      if (twoSided && (signal?.bigBid === cell.price || signal?.bigAsk === cell.price)) {
        ctx.strokeStyle = o.bigOrderColor; ctx.lineWidth = 2 * dpr;
        const left = signal.bigBid === cell.price ? x0 : center;
        ctx.strokeRect(left + dpr, top + dpr, half - 2 * dpr, Math.max(0, h - 2 * dpr));
      }
    });
    if (o.displayMode === 'imbalance' && body.size > 0) this._outlineBody(ctx, rc, col, body, candle);
    for (const span of signal?.absorption ?? []) {
      const a = this._bounds(span.high, col.rowSize, rc), b = this._bounds(span.low, col.rowSize, rc);
      const top = Math.min(a.top, b.top) * dpr, h = (Math.max(a.bottom, b.bottom) * dpr) - top;
      ctx.fillStyle = withAlpha(o.absorptionColor, 0.3); ctx.fillRect(x0, top, width, h);
      ctx.strokeStyle = o.absorptionColor; ctx.lineWidth = dpr; ctx.strokeRect(x0, top, width, h);
    }
    this._drawValueArea(ctx, rc, col, x0, width);
    this._drawBrackets(ctx, rc, col, imbBuy, imbSell);
  }

  /** Row prices of the drawn cells between the bar's open and close rows, inclusive. */
  private _bodyRows(bar: FootprintBar, cells: readonly FootprintCell[], step: number): Set<number> {
    const rows = new Set<number>();
    if (bar.open === undefined || bar.close === undefined || !bar.cells.length) return rows;
    const hi = this._rowOf(bar, Math.max(bar.open, bar.close), step), lo = this._rowOf(bar, Math.min(bar.open, bar.close), step);
    for (const cell of cells) if (cell.price <= hi && cell.price >= lo) rows.add(cell.price);
    return rows;
  }

  /** The row price holding `price`: the nearest row, which on the row grid is the one whose span contains it. */
  private _rowOf(bar: FootprintBar, price: number, step: number): number {
    let best = bar.cells[0]!.price;
    for (const cell of bar.cells) if (Math.abs(cell.price - price) < Math.abs(best - price)) best = cell.price;
    return step > 0 ? best : price;
  }

  private _outlineBody(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, col: Column, body: Set<number>, color: string): void {
    const dpr = rc.dpr, prices = [...body];
    const a = this._bounds(Math.max(...prices), col.rowSize, rc), b = this._bounds(Math.min(...prices), col.rowSize, rc);
    const top = Math.min(a.top, b.top), bottom = Math.max(a.bottom, b.bottom);
    ctx.strokeStyle = color; ctx.lineWidth = 1.5 * dpr;
    ctx.strokeRect(col.x0 * dpr, top * dpr, col.width * dpr, (bottom - top) * dpr);
  }

  private _drawValueArea(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, col: Column, x0: number, width: number): void {
    const o = this._opts, stats = col.stats;
    if (!o.showValueArea || stats.volume <= 0) return;
    const hi = this._bounds(stats.vah, col.rowSize, rc), lo = this._bounds(stats.val, col.rowSize, rc);
    ctx.strokeStyle = o.valueAreaColor ?? rc.theme.axisText; ctx.lineWidth = rc.dpr;
    ctx.beginPath();
    for (const y of [Math.min(hi.top, lo.top), Math.max(hi.bottom, lo.bottom)]) {
      ctx.moveTo(x0, y * rc.dpr); ctx.lineTo(x0 + width, y * rc.dpr);
    }
    ctx.stroke();
  }

  private _drawBrackets(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, col: Column, buy: string, sell: string): void {
    const o = this._opts, dpr = rc.dpr;
    if (o.stackedImbalances <= 0 || col.width < 16) return;
    const runs = stackedImbalances(col.bar.cells, o.imbalanceRatio, o.stackedImbalances, col.rowSize || undefined, o.imbalanceThreshold);
    for (const run of runs) {
      const a = this._bounds(run.startPrice, col.rowSize, rc), b = this._bounds(run.endPrice, col.rowSize, rc);
      const top = Math.min(a.top, b.top) * dpr, bottom = Math.max(a.bottom, b.bottom) * dpr;
      const bx = (run.side === 'buy' ? col.x0 + col.width - 1 : col.x0 + 1) * dpr;
      const dx = (run.side === 'buy' ? -3 : 3) * dpr;
      ctx.strokeStyle = run.side === 'buy' ? buy : sell; ctx.lineWidth = dpr;
      ctx.beginPath(); ctx.moveTo(bx + dx, top); ctx.lineTo(bx, top); ctx.lineTo(bx, bottom); ctx.lineTo(bx + dx, bottom); ctx.stroke();
    }
  }

  /** Lowest painted edge of a column: its bottom row or its candle's low. */
  private _columnBottom(rc: PrimitiveRenderContext, col: Column): number {
    let bottom = -Infinity;
    for (const cell of col.bar.cells) bottom = Math.max(bottom, this._bounds(cell.price, col.rowSize, rc).bottom);
    if (this._opts.showCandle) for (const price of [col.bar.high, col.bar.low]) if (price !== undefined) bottom = Math.max(bottom, rc.priceScale.priceToY(price));
    return bottom;
  }

  /** Delta label and flip marker under (or, for a selling flip, over) the column. */
  private _drawUnder(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, col: Column, p: Palette, cellBottom: number): void {
    const o = this._opts, dpr = rc.dpr, signal = this._signals.bars[col.index];
    let y = this._columnBottom(rc, col) + 3;
    if (o.showDeltaLabels && col.width >= 24) {
      const delta = col.bar.delta, h = o.font + 5;
      if (y + h <= cellBottom) {
        ctx.font = `bold ${o.font * dpr}px ui-monospace, SFMono-Regular, Menlo, monospace`;
        ctx.textAlign = 'center';
        ctx.fillStyle = readableTextColor(delta > 0 ? p.buy : delta < 0 ? p.sell : rc.theme.axisText, p.bg);
        ctx.fillText((delta > 0 ? '+' : '') + this._format(delta / o.volumeDivisor), col.x * dpr, (y + h / 2) * dpr);
        if (o.markDivergence && signal?.divergence) {
          ctx.strokeStyle = o.divergenceColor; ctx.lineWidth = 1.5 * dpr;
          ctx.strokeRect((col.x0 + 1) * dpr, y * dpr, (col.width - 2) * dpr, h * dpr);
        }
      }
      y += h + 2;
    }
    if (!signal?.flip) return;
    const size = Math.min(12, Math.max(6, col.width / 5));
    if (signal.flip > 0) drawFlip(ctx, rc, col.x, y + 1, size, true, p.buy);
    else {
      let top = Infinity;
      for (const cell of col.bar.cells) top = Math.min(top, this._bounds(cell.price, col.rowSize, rc).top);
      if (this._opts.showCandle && col.bar.high !== undefined) top = Math.min(top, rc.priceScale.priceToY(col.bar.high));
      drawFlip(ctx, rc, col.x, top - 3, size, false, p.sell);
    }
  }

  private _drawCandle(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, col: Column, gutter: number, buy: string, sell: string): void {
    const b = col.bar, dpr = rc.dpr;
    const x = (col.x0 - gutter / 2) * dpr;
    const bodyWidth = Math.min(4, gutter * 0.45) * dpr;
    // A column is only made for a bar with cells.
    const high = b.high ?? b.cells[0]!.price, low = b.low ?? b.cells[b.cells.length - 1]!.price;
    const y1 = rc.priceScale.priceToY(high) * dpr, y2 = rc.priceScale.priceToY(low) * dpr;
    const hasBody = b.open !== undefined && b.close !== undefined;
    const color = hasBody ? ((b.close as number) >= (b.open as number) ? buy : sell) : rc.theme.axisText;
    ctx.fillStyle = color;
    ctx.fillRect(x, Math.min(y1, y2), dpr, Math.max(dpr, Math.abs(y2 - y1)));
    if (hasBody) {
      const open = rc.priceScale.priceToY(b.open as number) * dpr, close = rc.priceScale.priceToY(b.close as number) * dpr;
      ctx.fillRect(x - bodyWidth / 2, Math.min(open, close), bodyWidth, Math.max(dpr, Math.abs(close - open)));
    }
  }

  private _cell(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, cell: FootprintCell,
    x: number, y: number, w: number, h: number, value: number, peak: number, textPeak: number, color: string,
    buy: string, sell: string, bg: string, hot: boolean, alpha: number, side: 'bid' | 'ask' | 'single', fixedFill?: string, text?: string): void {
    if (w <= 0 || h <= 0) return;
    const o = this._opts, dpr = rc.dpr, profile = o.cellStyle === 'profile' && fixedFill === undefined;
    const strength = Math.max(0, Math.min(1, peak > 0 ? Math.abs(value) / peak : 0));
    const fill = fixedFill ?? (hot ? color : mix(bg, color, o.cellStyle === 'ladder' ? 0.18 + 0.82 * Math.sqrt(strength) : 0.08 + 0.62 * Math.sqrt(strength)));
    const fillW = profile ? w * strength : w;
    const fillX = profile && side === 'bid' ? x + w - fillW : x;
    if (fillW > 0) {
      ctx.fillStyle = fill; ctx.beginPath();
      ctx.roundRect(fillX, y, fillW, h, o.cellStyle === 'ladder' || profile ? 0 : Math.min(o.radius * dpr, h / 2, fillW / 2)); ctx.fill();
    }
    if (alpha <= 0 || h < o.font * dpr * 0.6) return;
    const label = text ?? this._format(value / o.volumeDivisor), textW = ctx.measureText(label).width;
    if (textW + 4 * dpr > w) return;
    ctx.textAlign = profile && side !== 'single' ? (side === 'bid' ? 'right' : 'left') : 'center';
    const tx = profile && side !== 'single' ? (side === 'bid' ? x + w - 2 * dpr : x + 2 * dpr) : x + w / 2;
    const left = ctx.textAlign === 'right' ? tx - textW : ctx.textAlign === 'left' ? tx : tx - textW / 2;
    const right = left + textW;
    let background = fill;
    if (profile) {
      if (fillW === 0 || right <= fillX || left >= fillX + fillW) background = bg;
      else if (left < fillX || right > fillX + fillW) {
        // A number crossing a bright profile edge cannot contrast with both
        // surfaces. Give the glyphs one opaque backplate on that row.
        background = bg; ctx.fillStyle = bg;
        ctx.fillRect(left - dpr, y, textW + 2 * dpr, h);
      }
    }
    const neutral = o.textColor ?? readableTextColor(rc.theme.axisText, bg);
    const textColor = footprintTextColor({ mode: o.textColorMode, side, bidVol: cell.bidVol, askVol: cell.askVol,
      peak: textPeak, hot, neutral, buy: o.buyTextColor ?? buy, sell: o.sellTextColor ?? sell, background });
    ctx.fillStyle = withAlpha(textColor, alpha);
    ctx.fillText(label, tx, y + h / 2);
  }

  private _drawCard(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, col: Column, p: Palette, cellBottom: number): void {
    const o = this._opts, dpr = rc.dpr;
    if (col.width < 68 || col.rows.length === 0) return;
    const labels = o.showDeltaLabels && col.width >= 24 ? o.font + 7 : 0;
    const flip = this._signals.bars[col.index]?.flip === 1 ? Math.min(12, Math.max(6, col.width / 5)) + 2 : 0;
    const top = this._columnBottom(rc, col) + 8 + labels + flip, height = o.statsRows.length * o.statsRowHeight + 8;
    if (top < 0 || top + height > cellBottom) return;
    col.card = { top, bottom: top + height };
    const fill = mix(p.bg, rc.theme.axisText, 0.13);
    ctx.fillStyle = fill; ctx.beginPath(); ctx.roundRect(col.x0 * dpr, top * dpr, col.width * dpr, height * dpr, 2 * dpr); ctx.fill();
    ctx.font = `${Math.max(8, o.font - 1) * dpr}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    o.statsRows.forEach((row, i) => {
      const value = this._metric(col.stats, row), text = this._statText(col.stats, row);
      const y = (top + 4 + (i + 0.5) * o.statsRowHeight) * dpr;
      const label = STAT_LABEL[row];
      if (ctx.measureText(label).width + ctx.measureText(text).width + 12 * dpr > col.width * dpr) return;
      ctx.textAlign = 'left'; ctx.fillStyle = readableTextColor(o.textColor ?? rc.theme.axisText, fill);
      ctx.fillText(label, (col.x0 + 4) * dpr, y);
      ctx.textAlign = 'right';
      const neutral = row === 'session' ? o.sessionColor ?? o.textColor ?? rc.theme.axisText : o.textColor ?? rc.theme.axisText;
      ctx.fillStyle = readableTextColor(this._statColor(row, value, neutral, o.buyTextColor ?? p.buy, o.sellTextColor ?? p.sell), fill);
      ctx.fillText(text, (col.x0 + col.width - 4) * dpr, y);
    });
  }

  private _drawFooter(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, p: Palette, height: number, rows: readonly FootprintStatRow[]): void {
    const o = this._opts, dpr = rc.dpr, top = rc.plotHeight - height, { buy, sell } = p, bg = o.tableBackground ?? p.bg;
    const labelWidth = Math.min(o.tableLabelWidth, rc.plotWidth);
    ctx.fillStyle = bg; ctx.fillRect(0, top * dpr, rc.plotWidth * dpr, height * dpr);
    ctx.font = `${Math.max(8, o.font - 0.5) * dpr}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    ctx.textAlign = 'center';
    const slot = rc.timeScale.barSpacing;
    for (const col of this._cols) {
      const x = rc.timeScale.indexToX(rc.dataLayer.timeToIndex(col.bar.time)!);
      const left = Math.max(labelWidth, x - slot / 2), right = Math.min(rc.plotWidth, x + slot / 2);
      if (left < right) col.table = { left, right, top, bottom: rc.plotHeight };
    }
    ctx.save();
    ctx.beginPath(); ctx.rect(labelWidth * dpr, top * dpr, (rc.plotWidth - labelWidth) * dpr, height * dpr); ctx.clip();
    rows.forEach((row, i) => {
      // A ratio lives below one, so it alone is shaded against its own peak.
      let peak = row === 'cvdRatio' ? 0 : 1;
      for (const col of this._cols) if (col.table) peak = Math.max(peak, Math.abs(this._metric(col.stats, row) ?? 0));
      for (const col of this._cols) {
        if (!col.table) continue;
        const value = this._metric(col.stats, row), v = value ?? 0;
        // Session letters alternate shade per period, so a new letter stands out.
        const weight = row === 'session' ? (col.stats.session.charCodeAt(0) % 2 ? 0.3 : 0.15) : 0.1 + 0.4 * (peak > 0 ? Math.abs(v) / peak : 0);
        const fill = mix(bg, this._statColor(row, value, rc.theme.axisText, buy, sell), weight);
        const x = rc.timeScale.indexToX(rc.dataLayer.timeToIndex(col.bar.time)!);
        const y = (top + i * o.statsRowHeight) * dpr;
        ctx.fillStyle = fill;
        ctx.fillRect((x - slot / 2) * dpr, y + dpr, Math.max(0, slot * dpr - dpr), Math.max(0, o.statsRowHeight * dpr - dpr));
        const text = this._statText(col.stats, row);
        const halfText = ctx.measureText(text).width / (2 * dpr) + 2;
        if (x - halfText < col.table.left || x + halfText > col.table.right) continue;
        ctx.fillStyle = readableTextColor(row === 'session' ? o.sessionColor ?? o.textColor ?? rc.theme.axisText : o.textColor ?? rc.theme.axisText, fill);
        ctx.fillText(text, x * dpr, y + o.statsRowHeight * dpr / 2);
      }
    });
    ctx.restore();
    ctx.save();
    ctx.beginPath(); ctx.rect(0, top * dpr, labelWidth * dpr, height * dpr); ctx.clip();
    const labelFill = mix(bg, rc.theme.axisText, 0.09);
    ctx.fillStyle = labelFill; ctx.fillRect(0, top * dpr, labelWidth * dpr, height * dpr);
    ctx.fillStyle = readableTextColor(o.textColor ?? rc.theme.axisText, labelFill); ctx.textAlign = 'left';
    rows.forEach((row, i) => ctx.fillText(TABLE_LABEL[row], 6 * dpr, (top + (i + 0.5) * o.statsRowHeight) * dpr));
    ctx.restore();
    ctx.strokeStyle = mix(bg, rc.theme.axisText, 0.25); ctx.lineWidth = dpr; ctx.beginPath();
    for (let i = 0; i <= rows.length; i++) {
      const y = (top + i * o.statsRowHeight) * dpr;
      ctx.moveTo(0, y); ctx.lineTo(rc.plotWidth * dpr, y);
    }
    ctx.moveTo(labelWidth * dpr, top * dpr); ctx.lineTo(labelWidth * dpr, rc.plotHeight * dpr); ctx.stroke();
  }
  private _statColor(row: FootprintStatRow, value: number | null, neutral: string, buy: string, sell: string): string {
    if (row === 'session') return neutral;
    if (value === null || value === 0 || row === 'volume' || row === 'trades' || row === 'cumVolume') return neutral;
    if (row === 'askVolume') return buy;
    if (row === 'bidVolume') return sell;
    return value > 0 ? buy : sell;
  }
  private _metric(s: FootprintBarStats, row: FootprintStatRow): number | null { return row === 'session' ? null : s[row]; }
  private _statText(s: FootprintBarStats, row: FootprintStatRow): string {
    if (row === 'session') return s.session;
    const value = this._metric(s, row);
    if (value === null) return '-';
    if (row === 'deltaPct') return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
    if (row === 'cvdRatio') return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`;
    const displayed = row === 'trades' ? value : value / this._opts.volumeDivisor;
    const text = row === 'trades' ? compactVol(displayed) : this._format(displayed);
    return unsignedRow(row) || displayed < 0 ? text : '+' + text;
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    const hover = this.hoverAt(x, y);
    return hover ? { externalId: `footprint:${hover.time}`, zOrder: 'normal', distance: 0, cursor: 'crosshair' } : null;
  }
  public hoverAt(x: number, y: number, rc?: PrimitiveRenderContext): FootprintHover | null {
    const context = rc ?? this._rc;
    if (!context || x < 0 || x > context.plotWidth || y < 0 || y > context.plotHeight) return null;
    const table = this._cols.find(c => c.table && x >= c.table.left && x < c.table.right && y >= c.table.top && y <= c.table.bottom);
    if (table) return { time: table.bar.time, price: null, cell: null, stats: table.stats };
    const col = this._cols.find(c => x >= c.x0 && x <= c.x0 + c.width);
    if (!col) return null;
    const row = col.rows.find(r => y >= r.top && y < r.bottom);
    if (row) return { time: col.bar.time, price: row.cell.price, cell: row.cell, stats: col.stats };
    if (col.card && y >= col.card.top && y <= col.card.bottom) return { time: col.bar.time, price: null, cell: null, stats: col.stats };
    return null;
  }
}
