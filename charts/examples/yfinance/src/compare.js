import * as engine from '/dist/openalgo-charts.mjs';
import { PaneLegend } from '/dist/openalgo-charts.mjs';
import { el, esc, fmt, UP, DOWN } from './ui.js';
import { fetchBars } from './feed.js';
import { requestVariant, sessionOf } from './session.js';
import { renderToolbar } from './toolbar.js';
import { autosave } from './persist.js';
import { capturePaneTarget, selectedPane } from './pane-target.js';
import { withoutHistory } from './history.js';

const { addComparison, comparisonController } = engine;
export const CMP_COLORS = ['#e6b53c', '#7e57c2', '#29b6f6', '#ec407a', '#8bc34a'];
const MODES = ['percentage', 'indexed-to-100', 'none'];
const SCALE_MODES = ['linear', 'logarithmic', 'percentage', 'indexed-to-100'];
const runtimes = new WeakMap();
let app;
let dialogTarget = null;

export function comparisonState(pane = selectedPane(app)) {
  const key = pane === 2 ? 'comparisons2' : 'comparisons';
  return { items: app[key] ||= [], mode: app[pane === 2 ? 'cmpMode2' : 'cmpMode'] || 'percentage' };
}

function captureComparisonTarget(pane) {
  const target = capturePaneTarget(app, pane);
  if (!target) return null;
  const timezone = target.chart.timezone();
  return { ...target, timezone, current: () => target.current() && target.chart.timezone() === timezone };
}
const actionTarget = () => dialogTarget || captureComparisonTarget();
// A comparison is asked for in its chart's session, so it lines up with the
// chart's bars; a session change is a new source for it too.
const sourceKey = target => JSON.stringify([target.request.interval, target.request.period, sessionOf(target.request), target.timezone]);
const available = target => target?.current() && target.chart.primaryBars().length > 0
  && !app[target.pane === 2 ? 'loading2' : 'loading'] && !app[target.pane === 2 ? 'loadFailed2' : 'loadFailed'];

/** Subscriptions and pending requests belong to a chart, never to current focus. */
function runtime(target) {
  let state = runtimes.get(target.chart);
  if (state) return state;
  state = { pending: new Map(), readoutTime: null };
  runtimes.set(target.chart, state);
  target.chart.on('destroy', () => {
    for (const request of state.pending.values()) request.abort();
    state.pending.clear();
    for (const spec of comparisonState(target.pane).items) {
      if (spec.chart === target.chart) { spec.handle = null; spec.legend = null; spec.chart = null; }
    }
    if (dialogTarget?.chart === target.chart) closeCompare();
  });
  target.chart.on('click', ({ id }) => {
    if (!id) return;
    const spec = comparisonState(target.pane).items.find(item => id.startsWith('cmp:' + item.symbol + '::'));
    if (!spec || spec.chart !== target.chart) return;
    if (id.endsWith('::close')) removeComparison(spec, target.pane);
    if (id.endsWith('::hide')) {
      spec.hidden = !spec.hidden;
      spec.handle.series.applyOptions({ visible: !spec.hidden });
      spec.legend.setOptions({ hidden: spec.hidden });
      autosave();
    }
  });
  target.chart.on('crosshair:move', event => setCompareLegends(event.bar ?? target.chart.primaryBars().at(-1), target.pane));
  target.chart.on('data:update', () => setCompareLegends(target.chart.primaryBars().at(-1), target.pane));
  return state;
}

function clearComparisonData(spec) {
  spec.bars = [];
  spec.dataKey = null;
  spec.error = null;
  indexCompare(spec);
  spec.handle?.setBars([]);
  spec.legend?.setValues([]);
}

export function invalidateComparisons(pane) {
  const chart = pane === 2 ? app.chart2 : app.chart;
  const state = chart && runtimes.get(chart);
  for (const request of state?.pending.values() || []) request.abort();
  state?.pending.clear();
  for (const spec of comparisonState(pane).items) clearComparisonData(spec);
}

export function indexCompare(spec) {
  spec.byTime = new Map();
  let prevClose = null;
  for (const bar of spec.bars || []) {
    if (!Number.isFinite(bar.close)) continue;
    spec.byTime.set(bar.time, { close: bar.close, prevClose: prevClose ?? bar.open });
    prevClose = bar.close;
  }
}

/**
 * A comparison is the demo's own overlay, saved with its layout: it borrows
 * the price scale's mode while it is up, and none of that is a chart step
 * an undo should take back underneath it.
 */
export function attachComparison(spec, pane = 1) {
  withoutHistory(pane, () => attachComparisonNow(spec, pane));
}

function attachComparisonNow(spec, pane) {
  const target = captureComparisonTarget(pane);
  if (!target?.current() || !addComparison || !spec.bars?.length) return;
  if (spec.dataKey && spec.dataKey !== sourceKey(target)) return;
  runtime(target);
  const mode = comparisonState(pane).mode;
  const controller = comparisonController?.(target.chart, { mode, baseline: 'common' });
  controller?.setBaseline?.('common');
  if (controller && !controller.list().length) {
    // Rebuilding a chart restores its comparison mode too. Carry the mode it
    // had before comparing so removing the final source can still put it back.
    const key = pane === 2 ? 'cmpBaseMode2' : 'cmpBaseMode';
    const scale = target.chart.panes()[target.chart.primaryPaneIndex?.() ?? 0].priceScale;
    app[key] ||= scale.options.mode;
    scale.setOptions({ mode: app[key] });
  }
  controller?.setMode(mode);
  if (spec.handle && spec.chart === target.chart) {
    spec.handle.setBars(spec.bars);
    setCompareLegends(target.chart.primaryBars().at(-1), pane);
    return;
  }
  try {
    spec.handle = addComparison(target.chart, {
      symbol: spec.symbol, bars: spec.bars, color: spec.color, style: { lineWidth: 1.5 },
    });
    spec.chart = target.chart;
    spec.legend = new PaneLegend({ id: 'cmp:' + spec.symbol, title: spec.symbol,
      params: '', color: spec.color, actions: ['hide', 'close'], hidden: spec.hidden === true });
    // Baselines settle during autoscale. Refresh after the controller's hook so
    // a pan or replay frame cannot leave a price for a now-suppressed source.
    spec.legend.afterAutoscale = () => {
      const time = runtimes.get(target.chart)?.readoutTime;
      setComparisonLegend(spec, time == null ? target.chart.primaryBars().at(-1) : { time });
    };
    target.chart.addPrimitive(spec.legend);
    if (spec.hidden) spec.handle.series.applyOptions({ visible: false });
    spec.error = null;
    setCompareLegends(target.chart.primaryBars().at(-1), pane);
  } catch (error) { spec.error = error.message; }
}

/** Legend values always use the displayed bar, including during replay. */
export function setCompareLegends(bar, pane = 1) {
  const state = runtimes.get(pane === 2 ? app.chart2 : app.chart);
  if (state) state.readoutTime = bar?.time ?? null;
  for (const spec of comparisonState(pane).items) setComparisonLegend(spec, bar);
}

function setComparisonLegend(spec, bar) {
  if (!spec.legend) return;
  const hit = bar && spec.byTime?.get(bar.time);
  const aligned = bar && spec.handle?.barAt?.(bar.time);
  if (!hit || aligned === null) { spec.legend.setValues([]); return; }
  const close = aligned?.close ?? hit.close;
  const change = hit.prevClose ? ((close - hit.prevClose) / hit.prevClose) * 100 : null;
  spec.legend.setValues([
    { text: fmt(close), color: spec.color, field: 'ohlc' },
    ...(change === null ? [] : [{ text: `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`,
      color: change >= 0 ? UP : DOWN, field: 'change' }]),
  ]);
}

export function removeComparison(spec, pane = comparisonState(2).items.includes(spec) ? 2 : 1) {
  const items = comparisonState(pane).items;
  if (!items.includes(spec)) return;
  const chart = pane === 2 ? app.chart2 : app.chart;
  const pending = chart && runtimes.get(chart)?.pending;
  pending?.get(spec.symbol)?.abort();
  pending?.delete(spec.symbol);
  withoutHistory(pane, () => {
    spec.handle?.remove();
    if (spec.legend && spec.chart) spec.chart.removePrimitive(spec.legend);
  });
  spec.handle = null; spec.legend = null; spec.chart = null;
  items.splice(items.indexOf(spec), 1);
  if (!items.length) app[pane === 2 ? 'cmpBaseMode2' : 'cmpBaseMode'] = null;
  renderCompareList();
  renderToolbar();
  autosave();
}

async function loadComparison(spec, target, stillWanted) {
  const state = runtime(target);
  clearComparisonData(spec);
  const controller = new AbortController();
  state.pending.set(spec.symbol, controller);
  const current = () => !controller.signal.aborted && target.current() && stillWanted();
  try {
    const bars = await fetchBars(spec.symbol, target.request.interval, target.request.period,
      { signal: controller.signal, timezone: target.timezone, variant: requestVariant(target.request) });
    if (!current()) return false;
    spec.bars = bars;
    spec.dataKey = sourceKey(target);
    spec.error = bars.length ? null : 'No data for this interval';
    indexCompare(spec);
    return true;
  } catch (error) {
    if (current()) spec.error = error.message || 'History unavailable';
    return false;
  } finally {
    if (state.pending.get(spec.symbol) === controller) state.pending.delete(spec.symbol);
  }
}

export async function syncComparisons(pane = 1) {
  const target = captureComparisonTarget(pane);
  if (!target?.current()) return;
  const items = comparisonState(pane).items;
  await Promise.all(items.map(async spec => {
    const wanted = () => comparisonState(pane).items === items && items.includes(spec);
    if (runtime(target).pending.has(spec.symbol)) return;
    if (!spec.bars?.length || spec.dataKey !== sourceKey(target)) {
      if (!await loadComparison(spec, target, wanted)) return;
    }
    if (target.current() && wanted()) attachComparison(spec, pane);
  }));
  if (target.current()) renderCompareList();
}

export async function addCompareSymbol(symbol, target = actionTarget()) {
  const sym = String(symbol || '').trim().toUpperCase();
  if (!sym || !available(target)) return;
  if (!addComparison) { el('status').textContent = 'Comparison is unavailable in this build'; return; }
  const items = comparisonState(target.pane).items;
  if (items.some(spec => spec.symbol === sym) || runtime(target).pending.has(sym)) {
    el('status').textContent = `${sym} is already added or loading on chart ${target.pane}`;
    return;
  }
  el('status').textContent = `Chart ${target.pane}: loading ${sym}...`;
  const spec = { symbol: sym, color: CMP_COLORS[items.length % CMP_COLORS.length], bars: [] };
  const loaded = await loadComparison(spec, target, () => comparisonState(target.pane).items === items);
  if (!target.current()) return;
  if (!loaded || !spec.bars.length) {
    if (spec.error) el('status').textContent = `${sym}: ${spec.error}`;
    return;
  }
  items.push(spec);
  attachComparison(spec, target.pane);
  renderCompareList();
  renderToolbar();
  autosave();
  const coverage = spec.handle?.alignment();
  el('status').textContent = coverage
    ? `Chart ${target.pane}: ${sym}, ${coverage.matched} matched, ${coverage.gaps} gaps, ${coverage.dropped} dropped`
    : `${sym}: ${spec.error || 'Could not be added'}`;
}

export function setCompareMode(mode, target = actionTarget()) {
  if (!target?.current() || !MODES.includes(mode)) return;
  app[target.pane === 2 ? 'cmpMode2' : 'cmpMode'] = mode;
  withoutHistory(target.pane, () => comparisonController?.(target.chart).setMode(mode));
  autosave();
}

export function comparisonSnapshot(pane) {
  const state = comparisonState(pane);
  return { comparisons: state.items.map(spec => ({ symbol: spec.symbol, color: spec.color, hidden: spec.hidden === true })),
    compareMode: state.mode,
    ...(state.items.length ? { compareBaseMode: app[pane === 2 ? 'cmpBaseMode2' : 'cmpBaseMode'] } : {}) };
}

export function restoreComparisons(saved, pane, replace = true) {
  const state = comparisonState(pane);
  if (replace || !state.items.length) {
    invalidateComparisons(pane);
    for (const spec of state.items.slice()) removeComparison(spec, pane);
    const seen = new Set();
    const items = [];
    for (const value of Array.isArray(saved.comparisons) ? saved.comparisons : []) {
      if (!value || typeof value.symbol !== 'string') continue;
      const symbol = value.symbol.trim().toUpperCase();
      if (!symbol || seen.has(symbol)) continue;
      seen.add(symbol);
      items.push({ symbol, hidden: value.hidden === true, bars: [],
        color: /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value.color) ? value.color : CMP_COLORS[items.length % CMP_COLORS.length] });
    }
    app[pane === 2 ? 'comparisons2' : 'comparisons'] = items;
    app[pane === 2 ? 'cmpBaseMode2' : 'cmpBaseMode'] = SCALE_MODES.includes(saved.compareBaseMode) ? saved.compareBaseMode : null;
  }
  app[pane === 2 ? 'cmpMode2' : 'cmpMode'] = MODES.includes(saved.compareMode) ? saved.compareMode : 'percentage';
}

export function renderCompareList() {
  const target = dialogTarget;
  const host = el('cmp-list');
  if (!host || !target?.current()) return;
  const state = comparisonState(target.pane);
  const controller = comparisonController?.(target.chart);
  const noCommonStart = state.mode !== 'none' && controller?.baseline === 'common' && controller.baselineTime() === null;
  host.innerHTML = '';
  if (!state.items.length) {
    const none = document.createElement('div');
    none.className = 'hint'; none.textContent = 'No comparison symbols'; host.appendChild(none);
  }
  for (const spec of state.items) {
    const coverage = spec.handle?.alignment();
    const row = document.createElement('div');
    row.className = 'cmp-row';
    row.innerHTML = '<span class="sw" style="background:' + esc(spec.color) + '"></span><b>' + esc(spec.symbol) + '</b>'
      + '<span class="cmp-cov">' + esc(spec.error || (noCommonStart ? 'No common starting bar' : coverage
        ? `${coverage.matched} matched, ${coverage.gaps} gaps, ${coverage.dropped} dropped` : 'Loading')) + '</span>';
    if (spec.error) {
      const retry = document.createElement('button');
      retry.className = 'btn btn--ghost';
      retry.textContent = 'Retry'; retry.addEventListener('click', () => { if (available(target)) syncComparisons(target.pane); });
      row.appendChild(retry);
    }
    const remove = document.createElement('button');
    remove.className = 'btn btn--ghost cmp-del'; remove.textContent = 'Remove';
    remove.setAttribute('aria-label', 'Remove ' + spec.symbol);
    remove.addEventListener('click', () => { if (target.current()) removeComparison(spec, target.pane); });
    row.appendChild(remove); host.appendChild(row);
  }
  el('cmp-mode').value = state.mode;
}

export function openCompare(target = captureComparisonTarget()) {
  if (!available(target) || !addComparison) return;
  dialogTarget = captureComparisonTarget(target.pane);
  runtime(dialogTarget);
  el('cmp-title').textContent = `Compare symbols: Chart ${target.pane}`;
  renderCompareList();
  el('cmpmodal').hidden = false;
  el('cmp-sym').value = '';
  el('cmp-sym').focus();
}
export function closeCompare() { el('cmpmodal').hidden = true; dialogTarget = null; }

export function initCompare(value) {
  app = value;
  dialogTarget = null;
  el('cmp-add').addEventListener('click', () => addCompareSymbol(el('cmp-sym').value));
  el('cmp-sym').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); addCompareSymbol(el('cmp-sym').value); }
  });
  el('cmp-mode').addEventListener('change', () => setCompareMode(el('cmp-mode').value));
  el('cmp-x').addEventListener('click', closeCompare);
  el('cmp-close').addEventListener('click', closeCompare);
  el('cmpmodal').addEventListener('click', event => { if (event.target.id === 'cmpmodal') closeCompare(); });
}
