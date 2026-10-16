/**
 * The status line: one row under the chart with the engine's status-line
 * fields in HTML, so a host that turns the on-canvas legend off still has a
 * readout, and a screen reader has text to read.
 *
 * The fields are the legend's: the symbol and interval (the title), the O/H/L/C
 * of the bar under the pointer (chart values), the change over that bar (bar
 * change), its volume, and the bar's time in the chart's zone. Each follows
 * the same switch the settings dialog flips on the chart
 * (`chart.statusLineOptions()`), so turning off "chart values" there empties
 * the O/H/L/C here too. A transient message slot at the right takes what the
 * shell has to say (a load in progress, a magnet change, a saved layout).
 *
 * It listens to `crosshair:move`, which the engine emits on the cursor tier;
 * the handler writes text only when a value changed, so an idle pointer
 * touches nothing.
 *
 * With `marketStatus` on it also says where the market stands (open, pre-open,
 * closed until Monday), from the chart's session calendar, as a pane legend
 * shows the session state when its host supplies none. The widget turns it on
 * when it has no bottom bar to say it; a timer set for the next change of
 * phase keeps a chart nobody touches from reading "open" after the close.
 *
 * While the pointer is away the row follows the latest bar, the way the
 * legend does: it re-reads that bar on every `data:update` (a reload, a live
 * tick, a new bar), not only the first time it has none. Holding the bar it
 * last read left a grid cell nobody was hovering on the previous
 * instrument's prices after a symbol, interval or linked change.
 */
import { widgetText } from './localization';
import type { Bar, Chart, CrosshairMoveEvent } from 'openalgo-charts';
import { formatZonedCrosshairLabel } from 'openalgo-charts';
import { h, type WidgetContext } from './context';
import { dataVariantLabel } from './data-status';
import { MarketStatusHold, marketStatusReading, sessionStateShown } from './bottombar-status';

export interface StatuslineOptions {
  /** BCP 47 tag for number formatting. Default: the runtime's. */
  locale?: string | undefined;
  /**
   * Show the market status from the chart's session calendar, while the
   * chart's "Session state" switch is on. Nothing shows without a calendar
   * that lays out phases. Default false.
   */
  marketStatus?: boolean;
  /** Clock for the market status, in milliseconds. Default `Date.now`. */
  now?: (() => number) | undefined;
}

export interface StatuslineHandle {
  readonly el: HTMLElement;
  /** Put a transient message at the right. `error` tints it. */
  setMessage(text: string, kind?: 'info' | 'error'): void;
  /**
   * The title: symbol, optional exchange, and the interval code. Changing a
   * title already set clears the readings until the chart's primary data is
   * next replaced, since the bars still on the chart are the previous title's.
   */
  setSymbol(symbol: string, exchange: string, interval: string): void;
  /**
   * Show a bar's readings and hold them. Null lets the row follow the latest
   * bar again, as it does while the pointer is away.
   */
  setBar(bar: Bar | null, time: number | null): void;
  /** Re-read the chart's switches and repaint. */
  refresh(): void;
  destroy(): void;
}

/**
 * Decimals a price is printed with: the price scale's own, so the row agrees
 * with the axis, floored at two so a reading a trader compares against a level
 * survives the comparison (the same floor the engine puts under a study pane).
 */
export const MIN_PRICE_DIGITS = 2;
export function priceDigits(chart: Chart): number {
  const pane = chart.panes()[chart.primaryPaneIndex()];
  if (pane === undefined) return MIN_PRICE_DIGITS;
  const p = pane.priceScale.precision();
  return Number.isFinite(p) ? Math.max(MIN_PRICE_DIGITS, Math.min(8, Math.round(p))) : MIN_PRICE_DIGITS;
}

/** A fixed-decimal number formatter for the locale, cached per digit count. */
function numberFormatter(locale: string | undefined, digits: number, cache: Map<number, Intl.NumberFormat>): Intl.NumberFormat {
  let f = cache.get(digits);
  if (f === undefined) {
    f = new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    cache.set(digits, f);
  }
  return f;
}

export function mountStatusline(ctx: WidgetContext, host: HTMLElement, opts: StatuslineOptions = {}): StatuslineHandle {
  const doc = ctx.document;
  const chart = ctx.chart;
  const locale = opts.locale ?? ctx.locale;
  host.classList.add('oac-statusline');
  host.setAttribute('role', 'status');
  host.setAttribute('aria-live', 'polite');

  const title = h(doc, 'span', 'oac-statusline__title');
  const sym = h(doc, 'span', 'oac-statusline__sym');
  const iv = h(doc, 'span', 'oac-statusline__iv');
  // Which of the provider's series this is, when it is not the default one:
  // extended hours and raw prices look like any other candles.
  // It reads like the interval beside it, so it takes the interval's style.
  const variant = h(doc, 'span', 'oac-statusline__iv oac-statusline__variant');
  title.appendChild(sym);
  title.appendChild(iv);
  title.appendChild(variant);
  host.appendChild(title);

  const field = (label: string, cls: string): { el: HTMLElement; val: HTMLElement } => {
    const el = h(doc, 'span', 'oac-statusline__field ' + cls);
    const i = h(doc, 'i');
    i.textContent = label;
    const b = h(doc, 'b');
    el.appendChild(i);
    el.appendChild(b);
    el.hidden = true;
    host.appendChild(el);
    return { el, val: b };
  };
  const open = field(widgetText(ctx, 'O'), 'oac-statusline__o');
  const high = field(widgetText(ctx, 'H'), 'oac-statusline__h');
  const low = field(widgetText(ctx, 'L'), 'oac-statusline__l');
  const close = field(widgetText(ctx, 'C'), 'oac-statusline__c');
  const chg = field('', 'oac-statusline__chg');
  const vol = field(widgetText(ctx, 'Vol'), 'oac-statusline__vol');
  const oi = field(widgetText(ctx, 'OI'), 'oac-statusline__oi');
  const time = h(doc, 'span', 'oac-statusline__time');
  host.appendChild(time);
  const market = h(doc, 'span', 'oac-statusline__market');
  market.hidden = true;
  host.appendChild(market);
  const msg = h(doc, 'span', 'oac-statusline__msg');
  host.appendChild(msg);
  const tz = h(doc, 'span', 'oac-statusline__tz');
  host.appendChild(tz);

  const formats = new Map<number, Intl.NumberFormat>();
  const pct = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const compact = new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 2 });

  let bar: Bar | null = null;
  let barTime: number | null = null;
  // Whether the row shows the latest bar (the pointer is away, or past the
  // data) or a bar the pointer holds. Only the latest bar follows the data.
  let following = true;
  // The title changed and the bars on the chart are still the previous
  // instrument's (a feed keeps them until the new ones land). The row stays
  // empty until the next full replace rather than label old prices new.
  let awaiting = false;
  let titled = false;

  const write = (el: HTMLElement, text: string): void => { if (el.textContent !== text) el.textContent = text; };
  const show = (el: HTMLElement, on: boolean): void => { if (el.hidden === on) el.hidden = !on; };

  const paint = (): void => {
    const sw = chart.statusLineOptions();
    show(title, sw.title !== false);
    const label = dataVariantLabel(ctx, chart.getDataContext()?.variant);
    write(variant, label);
    show(variant, label !== '');
    const values = sw.chartValues !== false && bar !== null;
    for (const f of [open, high, low, close]) show(f.el, values);
    const digits = priceDigits(chart);
    if (values && bar !== null) {
      const fmt = numberFormatter(locale, digits, formats);
      write(open.val, fmt.format(bar.open));
      write(high.val, fmt.format(bar.high));
      write(low.val, fmt.format(bar.low));
      write(close.val, fmt.format(bar.close));
    }
    const change = sw.barChange !== false && bar !== null;
    show(chg.el, change);
    if (change && bar !== null) {
      const d = bar.close - bar.open;
      const p = bar.open !== 0 ? (d / bar.open) * 100 : 0;
      const sign = d > 0 ? '+' : '';
      write(chg.val, `${sign}${numberFormatter(locale, digits, formats).format(d)} (${sign}${pct.format(p)}%)`);
      chg.el.classList.toggle('is-up', d > 0);
      chg.el.classList.toggle('is-down', d < 0);
    }
    const volume = sw.volume !== false && bar !== null && typeof bar.volume === 'number';
    show(vol.el, volume);
    if (volume && bar !== null) write(vol.val, compact.format(bar.volume as number));
    const openInterest = sw.openInterest === true && chart.hasOpenInterest !== false
      && bar?.oi !== undefined && Number.isFinite(bar.oi);
    show(oi.el, openInterest);
    if (openInterest && bar?.oi !== undefined) write(oi.val, compact.format(bar.oi));
    write(time, barTime !== null && bar !== null ? formatZonedCrosshairLabel(barTime, chart.timezone()) : '');
    write(tz, chart.timezone());
    paintMarket();
  };

  // ── the market status, when the widget has no bottom bar to show it ────
  const hold = new MarketStatusHold();
  let marketTimer: ReturnType<typeof setTimeout> | 0 = 0;
  let marketWake = 0;
  let destroyed = false;
  function paintMarket(): void {
    if (opts.marketStatus !== true || destroyed) return;
    const nowSec = (opts.now ?? Date.now)() / 1000;
    const status = sessionStateShown(chart) ? hold.read(chart.dataLayer.sessionCalendar, nowSec) : null;
    const reading = status === null ? null : marketStatusReading({ translate: ctx.translate, locale }, status, nowSec, chart.timezone());
    show(market, reading !== null);
    if (reading !== null) {
      write(market, reading.detail === '' ? reading.label : `${reading.label} \u00b7 ${reading.detail}`);
      if (market.dataset.phase !== reading.phase) market.dataset.phase = reading.phase;
    }
    // Wake at the next change of phase, within the hour for a calendar
    // replaced meanwhile, and within the minute while there is none, since
    // setting one announces nothing. Set once per change, not on every
    // pointer move that repaints.
    const wake = Math.floor(status === null ? nowSec + 60 : Math.min(hold.until(), nowSec + 3600));
    if (wake === marketWake) return;
    if (marketTimer !== 0) clearTimeout(marketTimer);
    marketTimer = 0;
    marketWake = wake;
    if (wake !== 0) marketTimer = setTimeout(() => { marketTimer = 0; marketWake = 0; paintMarket(); }, Math.max(1, wake - nowSec) * 1000 + 50);
  }

  const lastBar = (): { bar: Bar | null; time: number | null } => {
    if (awaiting) return { bar: null, time: null };
    // The live array, not a copy: this runs on every tick.
    const data = chart.primaryBars();
    const last = data[data.length - 1];
    return last === undefined ? { bar: null, time: null } : { bar: last, time: last.time };
  };

  const setBar = (b: Bar | null, t: number | null): void => {
    if (b === bar && t === barTime) return;
    bar = b;
    barTime = t;
    paint();
  };

  const follow = (): void => { const l = lastBar(); setBar(l.bar, l.time); };

  const onMove = (payload: unknown): void => {
    const e = payload as CrosshairMoveEvent;
    if (e.bar !== null && e.bar !== undefined) { following = false; setBar(e.bar, e.time); return; }
    // The pointer left: the last bar is what the row shows, as the legend does.
    following = true;
    follow();
  };
  const onData = (payload: unknown): void => {
    const kind = (payload as { kind?: string } | undefined)?.kind;
    if (kind === 'reset') awaiting = false;
    if (following) { follow(); return; }
    // A tick on the bar the pointer holds changes its readings without a
    // pointer move; any other bar under the pointer is closed and stays put.
    const l = lastBar();
    if (l.bar !== null && l.time === barTime) setBar(l.bar, l.time);
  };
  const off = chart.on('crosshair:move', onMove);
  const offContext = chart.on('data:context', paint);
  const offData = chart.on('data:update', onData);
  const offResize = chart.on('resize', () => { if (following) follow(); });
  const offZone = chart.on('timezone:changed', paint);

  const handle: StatuslineHandle = {
    el: host,
    setMessage: (text, kind = 'info') => {
      write(msg, text);
      msg.classList.toggle('is-error', kind === 'error');
    },
    setSymbol: (symbol, exchange, interval) => {
      const name = exchange ? `${exchange}:${symbol}` : symbol;
      if (titled && name === sym.textContent && interval === iv.textContent) return;
      write(sym, name);
      write(iv, interval);
      // The first title names the bars already there. After that the readings
      // belong to the old title: drop them now, and take the latest bar again
      // once the new instrument's bars replace the series.
      awaiting = titled;
      titled = true;
      following = true;
      if (awaiting) setBar(null, null);
      else follow();
    },
    setBar: (b, t) => { following = b === null; setBar(b, t); },
    refresh: () => {
      if (following) { const l = lastBar(); bar = l.bar; barTime = l.time; }
      paint();
    },
    destroy: () => {
      destroyed = true;
      if (marketTimer !== 0) clearTimeout(marketTimer);
      off();
      offContext();
      offData();
      offResize();
      offZone();
      host.textContent = '';
    },
  };
  paint();
  return handle;
}
