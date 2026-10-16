import { formatZonedCrosshairLabel, getIndicator } from 'openalgo-charts';
import type { Bar, Chart, CrosshairMoveEvent, PriceFormat } from 'openalgo-charts';
import type { WidgetContext } from './context';
import { el } from './form';
import { widgetText, type WidgetTranslationOptions } from './localization';

export interface DataWindowRow {
  key: string;
  label: string;
  value: string;
  /** Null means absent, never an inferred zero. */
  raw: number | null;
}
export interface DataWindowSection { id: string; title: string; rows: DataWindowRow[] }
export interface DataWindowSnapshot {
  symbol: string;
  exchange: string;
  time: number | null;
  timestamp: string;
  sections: DataWindowSection[];
}
export interface DataWindowOptions extends WidgetTranslationOptions { locale?: string | undefined }
export interface DataWindowHandle { el: HTMLElement; refresh(): void; destroy(): void }

/** Read an exact candle, or the latest when time is omitted. Does not change the crosshair. */
export function readDataWindow(chart: Chart, time?: number, options: DataWindowOptions = {}): DataWindowSnapshot {
  const bars = chart.primaryBars();
  return readSnapshot(chart, bars, time, options, bars.some(item => Number.isFinite(item.oi)));
}

function readSnapshot(chart: Chart, bars: readonly Bar[], time: number | undefined, options: DataWindowOptions, historyHasOi: boolean): DataWindowSnapshot {
  const text = (key: string, fallback: string): string => widgetText(options, `schema.ui.data.${key}`, {}, fallback);
  const unavailable = text('unavailable', 'Unavailable');
  let index = bars.length - 1;
  if (time !== undefined) {
    let lo = 0, hi = bars.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (bars[mid]!.time < time) lo = mid + 1; else hi = mid; } // mid < hi <= length
    index = bars[lo]?.time === time ? lo : -1;
  }
  const bar = bars[index];
  const at = time === undefined ? bar?.time ?? null : Number.isFinite(time) ? time : null;
  let number: Intl.NumberFormat;
  try { number = new Intl.NumberFormat(options.locale, { maximumFractionDigits: 8 }); }
  catch { number = new Intl.NumberFormat('en-US', { maximumFractionDigits: 8 }); }
  const format = (value: number, source?: PriceFormat, price = false): string => {
    try {
      if (source?.type === 'custom') return String(source.formatter(value));
      if (source?.type === 'percent') return `${value.toFixed(source.precision ?? 2)}%`;
      if (source?.type === 'price') return value.toFixed(source.precision ?? 2);
      if (price) return chart.primarySeries()?.priceScale().format(value) ?? value.toFixed(2);
    } catch { /* Host formatters cannot make the rest of the data unreadable. */ }
    return number.format(value);
  };
  const row = (key: string, label: string, raw: number | null | undefined, price = false, source?: PriceFormat): DataWindowRow => {
    const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
    return { key, label, raw: value, value: value === null ? unavailable : format(value, source, price) };
  };
  const priceRows = (['open', 'high', 'low', 'close'] as const).map(key => row(key,
    text(key, key[0]!.toUpperCase() + key.slice(1)), bar?.[key], true)); // four non-empty names
  priceRows.push(row('volume', text('volume', 'Volume'), bar?.volume));
  const hasOi = chart.hasOpenInterest !== false && (chart.hasOpenInterest === true || historyHasOi);
  if (hasOi) priceRows.push(row('oi', text('oi', 'Open interest'), bar?.oi));
  const sections: DataWindowSection[] = [{ id: 'price', title: text('price', 'Price'), rows: priceRows }];
  for (const indicator of chart.indicators()) {
    const descriptor = getIndicator(indicator.indicatorId);
    const values = indicator.values();
    const plots = descriptor?.plots ?? [];
    const rows = plots.map(plot => row(`${indicator.id}:${plot.key}`, plot.title,
      index < 0 ? null : values[plot.ohlc?.close ?? plot.key]?.[index - (plot.offset ?? 0)], false, plot.priceFormat));
    if (rows.length > 0) sections.push({ id: indicator.id, title: indicator.name, rows });
  }
  const context = chart.getDataContext();
  let timestamp = unavailable;
  if (at !== null) {
    try { timestamp = `${formatZonedCrosshairLabel(at, chart.timezone())} (${chart.timezone()})`; }
    catch { /* A timestamp outside the Date range remains unavailable. */ }
  }
  return { symbol: context?.symbol ?? '', exchange: context?.exchange ?? '', time: at, timestamp, sections };
}

/** Mount selectable readings in a host-owned panel. No polling or single-callback subscription. */
export function mountDataWindow(ctx: WidgetContext, host: HTMLElement): DataWindowHandle {
  const doc = ctx.document;
  host.classList.add('oac-data-window');
  host.setAttribute('aria-label', widgetText(ctx, 'schema.ui.data.title', {}, 'Data window'));
  const heading = el(doc, 'div', 'oac-data-window__instrument');
  const timestamp = el(doc, 'div', 'oac-data-window__time');
  const body = el(doc, 'div', 'oac-data-window__sections');
  host.append(heading, timestamp, body);
  let readTime: number | undefined;
  let pending = false, destroyed = false, awaitingData = false;
  let dataDirty = true, historyHasOi = false;
  let bars: readonly Bar[] = [];
  const sections = new Map<string, { el: HTMLElement; title: HTMLElement; rows: Map<string, { el: HTMLElement; label: HTMLElement; value: HTMLElement }> }>();
  const write = (node: HTMLElement, value: string): void => { if (node.textContent !== value) node.textContent = value; };
  const paint = (): void => {
    if (destroyed) return;
    if (dataDirty) {
      bars = ctx.chart.primaryBars();
      historyHasOi = bars.some(item => Number.isFinite(item.oi));
      dataDirty = false;
    }
    const snapshot = readSnapshot(ctx.chart, bars, awaitingData ? NaN : readTime, ctx, historyHasOi);
    write(heading, [snapshot.exchange, snapshot.symbol].filter(Boolean).join(':'));
    write(timestamp, snapshot.timestamp);
    const ids = new Set(snapshot.sections.map(section => section.id));
    for (const [id, section] of sections) if (!ids.has(id)) { section.el.remove(); sections.delete(id); }
    for (const [position, group] of snapshot.sections.entries()) {
      let section = sections.get(group.id);
      if (!section) {
        const node = el(doc, 'section', 'oac-data-window__section');
        const title = el(doc, 'h3', 'oac-data-window__title');
        node.appendChild(title); body.appendChild(node);
        section = { el: node, title, rows: new Map() }; sections.set(group.id, section);
      }
      if (body.children[position] !== section.el) body.insertBefore(section.el, body.children[position] ?? null);
      write(section.title, group.title);
      const keys = new Set(group.rows.map(item => item.key));
      for (const [key, item] of section.rows) if (!keys.has(key)) { item.el.remove(); section.rows.delete(key); }
      for (const item of group.rows) {
        let node = section.rows.get(item.key);
        if (!node) {
          const root = el(doc, 'div', 'oac-data-window__row'); root.dataset.key = item.key;
          const label = el(doc, 'span', 'oac-data-window__label'), value = el(doc, 'span', 'oac-data-window__value');
          root.append(label, value); section.el.appendChild(root);
          node = { el: root, label, value }; section.rows.set(item.key, node);
        }
        write(node.label, item.label); write(node.value, item.value);
        node.value.classList.toggle('is-unavailable', item.raw === null);
      }
    }
  };
  const refresh = (): void => {
    if (pending || destroyed) return;
    pending = true;
    // A data event can precede study recalculation within the same synchronous update.
    void Promise.resolve().then(() => { pending = false; paint(); });
  };
  const off = [
    ctx.chart.on('crosshair:readout', payload => {
      const event = payload as CrosshairMoveEvent;
      readTime = event.index === null && event.point === null ? undefined : event.time ?? NaN;
      refresh();
    }),
    ctx.chart.on('data:context', () => { readTime = undefined; awaitingData = true; dataDirty = true; refresh(); }),
    ctx.chart.on('data:range', () => { awaitingData = false; dataDirty = true; refresh(); }),
    ...(['objects:change', 'indicatorSettings', 'indicatorRemoved', 'indicator:data-status', 'paneMoved', 'resize', 'timezone:changed'] as const).map(event => ctx.chart.on(event, refresh)),
  ];
  const destroy = (): void => {
    if (destroyed) return;
    destroyed = true;
    for (const stop of off) stop();
    sections.clear(); host.textContent = ''; host.classList.remove('oac-data-window'); host.removeAttribute('aria-label');
  };
  off.push(ctx.chart.on('destroy', destroy));
  paint();
  return { el: host, refresh, destroy };
}

export const DATA_WINDOW_CSS = `
.oac-widget .oac-data-window { padding: 12px; font-size: 12px; user-select: text; -webkit-user-select: text; }
.oac-widget .oac-data-window__instrument { font-weight: 600; color: var(--oac-tx); overflow-wrap: anywhere; }
.oac-widget .oac-data-window__time { font-size: 11px; color: var(--oac-mut); margin: 4px 0 14px; line-height: 1.5; }
.oac-widget .oac-data-window__section + .oac-data-window__section { margin-top: 16px; }
.oac-widget .oac-data-window__title { margin: 0 0 6px; padding: 0; font: 600 11px/1.4 var(--oac-font); color: var(--oac-mut); text-transform: uppercase; letter-spacing: .04em; }
.oac-widget .oac-data-window__row { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; min-height: 26px; padding: 4px 0; }
.oac-widget .oac-data-window__label { min-width: 0; overflow-wrap: anywhere; }
.oac-widget .oac-data-window__value { font-variant-numeric: tabular-nums; text-align: right; overflow-wrap: anywhere; }
.oac-widget .oac-data-window__value.is-unavailable { font-size: 11px; color: var(--oac-mut); }
`;
