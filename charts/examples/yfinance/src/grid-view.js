// The grid view's pieces that need no page: the feed adapter, the hand-off
// from the main page and the exported document. grid.js boots the page from
// them, and they stay importable by the node tests without a document.
import { parseWorkspaceDocument, parseWorkspacePayload } from '/dist/openalgo-charts.workspace.mjs';
import { layoutIconPath } from '/dist/openalgo-charts.draw.mjs';
import { CHART_GRID_LAYOUTS, CHART_GRID_LAYOUT_NAMES } from '/dist/openalgo-charts.widget.mjs';
import { YFinanceDataFeed, AbortedError } from './feed.js';

/** Interval pills in each grid chart: widget codes this server can answer. */
export const GRID_INTERVALS = ['1m', '5m', '15m', '1h', '1d', '1w'];

/**
 * What the status line calls each layout, in the order the grid's picker lists
 * them: the library's own names, so the line and the picker's tiles say the
 * same thing.
 */
export const GRID_PRESET_LABELS = Object.fromEntries(Object.keys(CHART_GRID_LAYOUTS).map(id => [id, CHART_GRID_LAYOUT_NAMES[id]]));

/** Where the main page leaves a layout it cannot show, for this page to open. */
export const GRID_HANDOFF_KEY = 'oac-grid-handoff';

const WIRE = { '1w': '1wk' };
// The widget asks for a time window; this server answers by named period, so
// a chart whose layout saved no period asks for its interval's one here, and
// the keys are every interval this view can load at all.
const PERIODS = { '1m': '5d', '5m': '1mo', '15m': '1mo', '30m': '1mo', '1h': '6mo', '1d': '5y', '1w': '10y' };
// The periods the server knows, in days, and how far back the source serves
// each intraday interval: a longer ask comes back empty, not refused.
const PERIOD_DAYS = { '1d': 1, '5d': 5, '1mo': 31, '3mo': 92, '6mo': 186, ytd: 366, '1y': 366, '2y': 731, '5y': 1830, '10y': 3653, max: Infinity };
const MAX_DAYS = { '1m': 7, '5m': 60, '15m': 60, '30m': 60, '1h': 730 };
// A daily chart loads five years at least, as on the main page, so it holds
// 500 candles or more. A shorter period its layout saved, such as the year an
// hourly chart kept when it moved to daily, would draw about 250.
const MIN_DAYS = { '1d': PERIOD_DAYS['5y'] };
// The main page saves its weekly frame by the source's own code.
const ALIASES = { '1wk': '1w' };

/**
 * The period a chart loads: the one its layout saved when this interval can
 * serve it, else the interval's usual one. A chart whose interval changes
 * keeps its saved period for when it changes back.
 */
export function gridPeriod(interval, saved) {
  const days = PERIOD_DAYS[saved];
  return days >= (MIN_DAYS[interval] ?? 0) && days <= (MAX_DAYS[interval] ?? Infinity) ? saved : PERIODS[interval] || '1y';
}

/**
 * A widget DataFeed over the page's /api/history, keeping the caller's
 * cancellation, that loads `period` (a layout's historyPeriod) where it can.
 * Requests wait for `ready` when one is given: a request cancelled meanwhile
 * never reaches the source.
 */
export function gridFeed(source = new YFinanceDataFeed(), { ready, period } = {}) {
  return {
    getBars: async req => {
      await ready;
      if (req.signal?.aborted) throw new AbortedError();
      return source.getBars({
        symbol: req.symbol, interval: WIRE[req.interval] || req.interval, period: gridPeriod(req.interval, period), signal: req.signal,
      });
    },
    // The first answer already holds the whole period this view asks for, so
    // there is no older page. Saying so stops history paging from downloading
    // the same period again at every left edge.
    getBarsPage: async () => ({ bars: [], hasMore: false }),
  };
}

/**
 * The grid's `feed` function: each chart loads the history period its layout
 * saved. Charts with the same period get the same feed, so two of them on one
 * instrument still share one request.
 */
export function gridFeeds({ ready } = {}, source = new YFinanceDataFeed()) {
  const feeds = new Map();
  return ({ historyPeriod }) => {
    if (!feeds.has(historyPeriod)) feeds.set(historyPeriod, gridFeed(source, { ready, period: historyPeriod }));
    return feeds.get(historyPeriod);
  };
}

/**
 * Why the grid view cannot open a layout, or '' when it can. The main page
 * asks before it leaves, so a refusal is shown where the file was chosen.
 */
export function gridViewRefusal(payload) {
  const interval = pane => ALIASES[pane.interval] || pane.interval;
  for (const pane of payload.panes) {
    if (pane.comparisons?.length) return `${pane.symbol}: comparison symbols are not drawn in the grid view`;
    if (!(interval(pane) in PERIODS)) return `${pane.symbol}: the grid view has no ${pane.interval} interval`;
    if (pane.historyPeriod !== undefined && !Object.prototype.hasOwnProperty.call(PERIOD_DAYS, pane.historyPeriod)) {
      return `${pane.symbol}: the grid view cannot load a ${pane.historyPeriod} history period`;
    }
  }
  // A linked group makes its charts agree, which would overwrite the ones that do not.
  // Saved groups each link their own charts; without groups the whole desk is one.
  const groups = Array.isArray(payload.sync?.groups)
    ? payload.sync.groups.map(group => ({ ...group, panes: payload.panes.filter(pane => pane.linkGroup === group.id) }))
    : [{ ...payload.sync, panes: payload.panes }];
  for (const group of groups) {
    const differ = key => new Set(group.panes.map(key)).size > 1;
    if (group.symbol && differ(pane => `${pane.symbol}|${pane.exchange}`)) return 'the charts are linked by symbol but show different symbols';
    if (group.interval && differ(interval)) return 'the charts are linked by interval but show different intervals';
    if (group.chartType && differ(pane => pane.chartType)) return 'the charts are linked by chart type but show different chart types';
  }
  return '';
}

/**
 * A layout's glyph for the status line: the library's layout tile, drawn from
 * the layout's own slots, so a large chart spanning two cells reads as one.
 * Empty for an id the catalogue does not know (a layout saved by hand).
 */
export function presetGlyph(preset) {
  const spec = Object.prototype.hasOwnProperty.call(CHART_GRID_LAYOUTS, preset) ? CHART_GRID_LAYOUTS[preset] : null;
  if (spec === null) return '';
  return `<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"`
    + ` stroke-linecap="round" stroke-linejoin="round"><path d="${layoutIconPath(spec.rows, spec.columns, spec.slots)}"/></svg>`;
}

/** Leave a validated document for the grid view. False when storage refuses it. */
export function handOffToGrid(document, storage = globalThis.sessionStorage) {
  try { storage.setItem(GRID_HANDOFF_KEY, JSON.stringify(document)); return true; }
  catch { return false; }
}

/** Take the document the main page left, once. Null when there is none. */
export function takeGridHandoff(storage = globalThis.sessionStorage) {
  try {
    const text = storage.getItem(GRID_HANDOFF_KEY);
    storage.removeItem(GRID_HANDOFF_KEY);
    return text;
  } catch { return null; }
}

/** Validate any saved layout file, complete document or bare payload, before a chart changes. */
export function readGridFile(text) {
  const payload = parseWorkspacePayload(text);
  const refusal = gridViewRefusal(payload);
  if (refusal) throw new Error(refusal);
  for (const pane of payload.panes) pane.interval = ALIASES[pane.interval] || pane.interval;
  return payload;
}

/** The grid's payload as a named document the workspace tier accepts. */
export function gridDocument(payload, { name = 'Chart grid', now = Date.now() } = {}) {
  return parseWorkspaceDocument({ kind: 'workspace', version: 1, id: `grid-${now}`, name, createdAt: now, updatedAt: now, ...payload });
}
