import { el, esc, currentTheme, toggleTheme, plural } from './ui.js';
import { attachTip, hideTip } from './hover.js';
import { cycleMagnet, magnetMode, focusChart, syncNavigationControls, applyRailCollapsed } from './rail.js';
import { INTERVALS, intervalLabel, intervalName, periodsFor, clampPeriod, foldedInterval } from './intervals.js';
import { popupMenu } from './menus.js';
import { openCompare, comparisonState } from './compare.js';
import { enterReplay, askExitReplay } from './replay.js';
import { openSnapMenu, downloadSnapshot } from './snapshot.js';
import { isSplit, openSplit, closeSplit } from './split.js';
import { describeLink, openLinkMenu } from './link.js';
import { openTimelineMenu } from './timeline.js';
import { openCacheMenu } from './feed.js';
import { openChartSettings } from './chart-settings.js';
import { openAlerts } from './alerts.js';
import { capturePaneTarget, selectedPane } from './pane-target.js';
import { autosave } from './persist.js';
import { rememberIndicators, renderIndicatorChips } from './indicators.js';
import { recordChartType, withoutHistory } from './history.js';
import { mountSymbolPicker, mountIndicatorPicker } from '/dist/openalgo-charts.widget.mjs';
import { referenceSymbolSearch } from './symbol-search.js';
import { toggleInspection } from './inspection.js';
import { openGoTo } from './goto.js';
import { extendedSessionAvailable, sessionLabel, sessionOf } from './session.js';
import { keepsView, typeOptions } from './transforms.js';
import { openBoxSettings } from './box-settings.js';

let app;
let symbolPicker = null;
let symbolSearchClose = null;
let indicatorPicker = null;

function closeIndicatorPicker() {
  const picker = indicatorPicker;
  indicatorPicker = null;
  picker?.close();
}

function closeSymbolSearch() {
  const picker = symbolPicker;
  symbolPicker = null;
  picker?.destroy();
  const close = symbolSearchClose;
  symbolSearchClose = null;
  close?.();
}

// ══ toolbar shell ══════════════════════════════════════════════════════
// Buttons and popup menus rather than native <select>s: a select cannot show
// an icon per row, cannot group, and looks like a form control on a chart.
// Primary legacy fields remain available; shared actions capture their pane
// instead of treating those fields as the selected chart's state.
export const TOOLBAR_ICON = {
  search: '<circle cx="9" cy="9" r="5.5"/><path d="M13 13l4 4"/>',
  download: '<path d="M10 3v9m0 0 3.2-3.2M10 12 6.8 8.8"/><path d="M3.5 14v2.5h13V14"/>',
  copy: '<rect x="6.5" y="6.5" width="9" height="9" rx="1.5"/><path d="M13 4.5H5A1.5 1.5 0 0 0 3.5 6v8"/>',
  candles: '<path d="M6 4v12M6 6h0"/><rect x="4" y="6" width="4" height="7"/><path d="M14 3v14"/><rect x="12" y="6" width="4" height="8"/>',
  bars: '<path d="M6 4v12M6 7h3M3 10h3"/><path d="M14 4v12M14 7h3M11 10h3"/>',
  line: '<path d="M3 14l4-5 4 3 6-8"/>',
  area: '<path d="M3 15l4-5 4 3 6-8v10z"/>',
  baseline: '<path d="M3 10h14"/><path d="M3 13l4-5 4 3 6-6"/>',
  renko: '<rect x="3" y="10" width="4" height="5"/><rect x="8" y="6" width="4" height="5"/><rect x="13" y="3" width="4" height="5"/>',
  pnf: '<path d="M3 4l4 4M7 4l-4 4"/><circle cx="10" cy="12" r="2"/><path d="M14 4l4 4M18 4l-4 4"/>',
  indicators: '<path d="M3 15l3-6 3 3 3-7 3 5 2-2"/>',
  save: '<path d="M4 4h9l3 3v9H4z"/><path d="M7 4v4h6V4M7 16v-5h6v5"/>',
  restore: '<path d="M4 10a6 6 0 1 1 2 4.5"/><path d="M3 6v4h4"/>',
  camera: '<rect x="3" y="6" width="14" height="10" rx="2"/><circle cx="10" cy="11" r="3"/><path d="M7 6l1.5-2h3L13 6"/>',
  fit: '<path d="M4 8V4h4M16 8V4h-4M4 12v4h4M16 12v4h-4"/>',
  grid: '<path d="M3 8h14M3 12h14M8 3v14M12 3v14"/>',
  magnet: '<path d="M6 4v6a4 4 0 008 0V4"/><path d="M6 4h3v6M11 4h3v6"/>',
  chevron: '<path d="M6 8l4 4 4-4"/>',
  // Diagonal expand/collapse arrows, deliberately unlike `fit` (four corner
  // brackets), which is a different action and sits two buttons away.
  fullscreen: '<path d="M11 4h5v5"/><path d="M9 16H4v-5"/><path d="M16 4l-5.5 5.5"/><path d="M4 16l5.5-5.5"/>',
  fullscreenExit: '<path d="M16 9h-5V4"/><path d="M4 11h5v5"/><path d="M11 9l5-5"/><path d="M9 11l-5 5"/>',
  // Replay transport. A clock inside a rewinding arrow, then the four
  // buttons the bar itself uses.
  replay: '<path d="M3.2 10a6.8 6.8 0 1 1 2.2 5"/><path d="M3.2 6v4h4"/><path d="M10 7.5V10l1.8 1.2"/>',
  play: '<path d="M7.5 4.6l7.4 5.4-7.4 5.4z"/>',
  pause: '<path d="M7.6 4.6v10.8M12.4 4.6v10.8"/>',
  stepfwd: '<path d="M5.8 4.6l6.6 5.4-6.6 5.4z"/><path d="M14.6 4.6v10.8"/>',
  stepback: '<path d="M14.2 4.6l-6.6 5.4 6.6 5.4z"/><path d="M5.4 4.6v10.8"/>',
  exit: '<path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/>',
  // Two series diverging from one another: the point of a comparison.
  compare: '<path d="M3 15.5l4-4.5 3.5 2.5L17 5"/><path d="M3 9.5l4 3 3.5-5.5L17 12"/>',
  // Two sliders: the settings of the chart type beside it, kept apart from
  // the chart settings gear further along the bar.
  tune: '<path d="M3 6.5h8M15 6.5h2M3 13.5h2M9 13.5h8"/><circle cx="13" cy="6.5" r="2"/><circle cx="7" cy="13.5" r="2"/>',
  gear: '<circle cx="10" cy="10" r="2.6"/><path d="M10 2.6v2M10 15.4v2M17.4 10h-2M4.6 10h-2M15.2 4.8l-1.4 1.4M6.2 13.8l-1.4 1.4M15.2 15.2l-1.4-1.4M6.2 6.2L4.8 4.8"/>',
  // Two chain links: the group, not the layout.
  link: '<path d="M8.4 11.6a3 3 0 0 1 0-4.2l1.8-1.8a3 3 0 1 1 4.2 4.2l-.9.9"/><path d="M11.6 8.4a3 3 0 0 1 0 4.2l-1.8 1.8a3 3 0 1 1-4.2-4.2l.9-.9"/>',
  // One frame divided: the layout, not the group.
  split: '<rect x="2.5" y="4" width="15" height="12" rx="1.6"/><path d="M10 4v12"/>',
  // The frame divided both ways: the grid view with rows as well as columns.
  // Its own key: a second `grid` took the grid lines' icon from the Grid button.
  gridView: '<rect x="2.5" y="4" width="15" height="12" rx="1.6"/><path d="M10 4v12M2.5 10h15"/>',
  // A stack of stored rows with a tick: something held, and held valid.
  cache: '<ellipse cx="10" cy="5.4" rx="6.2" ry="2.4"/><path d="M3.8 5.4v4.6c0 1.3 2.8 2.4 6.2 2.4s6.2-1.1 6.2-2.4V5.4"/><path d="M3.8 10v4.6c0 1.3 2.8 2.4 6.2 2.4"/><path d="M13 15l1.8 1.8L18 13"/>',
  // The mirror of `download`: a layout file going the other way.
  upload: '<path d="M10 12V3m0 0 3.2 3.2M10 3 6.8 6.2"/><path d="M3.5 14v2.5h13V14"/>',
  // Sun and moon for the theme switch: the glyph shown is the theme you would switch to.
  sun: '<circle cx="10" cy="10" r="3.6"/><path d="M10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1L4.7 4.7"/>',
  moon: '<path d="M16.5 12.2A6.6 6.6 0 0 1 7.8 3.5a6.6 6.6 0 1 0 8.7 8.7z"/>',
};
export const ticon = (k) => '<svg viewBox="0 0 20 20">' + (TOOLBAR_ICON[k] || '') + '</svg>';

export const CHART_TYPES = [
  { group: 'Time-indexed' },
  { v: 'candlestick', label: 'Candles', icon: 'candles' },
  { v: 'hollow-candle', label: 'Hollow candles', icon: 'candles' },
  { v: 'bar', label: 'Bars', icon: 'bars' },
  { v: 'high-low', label: 'High-low', icon: 'bars' },
  { v: 'volume-candle', label: 'Volume candles', icon: 'candles' },
  { v: 'line', label: 'Line', icon: 'line' },
  { v: 'line-markers', label: 'Line with markers', icon: 'line' },
  { v: 'step', label: 'Step line', icon: 'line' },
  { v: 'area', label: 'Area', icon: 'area' },
  { v: 'hlc-area', label: 'HLC area', icon: 'area' },
  { v: 'baseline', label: 'Baseline', icon: 'baseline' },
  { group: 'Transforms' },
  { v: 't:heikin-ashi', label: 'Heikin Ashi', icon: 'candles' },
  { v: 't:renko', label: 'Renko', icon: 'renko' },
  { v: 't:range', label: 'Range bars', icon: 'renko' },
  { v: 't:line-break', label: 'Line break', icon: 'renko' },
  { v: 't:point-figure', label: 'Point and figure', icon: 'pnf' },
  { v: 't:kagi', label: 'Kagi', icon: 'line' },
];

export const chartTypeLabel = (v) => (CHART_TYPES.find((t) => t.v === v) || { label: 'Candles' }).label;
export const chartTypeIcon = (v) => (CHART_TYPES.find((t) => t.v === v) || { icon: 'candles' }).icon;

/** Link metadata for the chart's active branding, or null when it has no link. */
export function brandingLink(chart) {
  if (!chart || typeof chart.brandingOptions !== 'function') return null;
  const options = chart.brandingOptions();
  if (!options || typeof options.href !== 'string' || !/^https?:\/\//i.test(options.href)) return null;
  const label = typeof options.label === 'string' && options.label.trim()
    ? options.label.trim()
    : 'Chart branding';
  return { href: options.href, label };
}

/* ── chart-only full screen ────────────────────────────────────────────
   Keep the toolbar and dialogs in the fullscreen subtree while only the
   selected plot is shown. Its ResizeObserver measures the new chart box. */
export const stageEl = () => document.querySelector('main.stage');
export const isChartFull = () => document.fullscreenElement === document.body;
let fullscreenControlHomes = [];

export function toggleChartFullscreen() {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(error => { el('status').textContent = error.message; });
  } else if (document.body.requestFullscreen) {
    const target = capturePaneTarget(app);
    if (!target?.current()) return;
    app.fullscreenPane = target.pane;
    // Fullscreen is user-gesture gated and blocked outright in some embeds.
    document.body.requestFullscreen().catch((e) => {
      app.fullscreenPane = null;
      syncFullscreenChrome();
      el('status').textContent = 'full screen unavailable: ' + (e && e.message ? e.message : e);
    });
  } else {
    el('status').textContent = 'full screen not supported by this browser';
  }
}

// Moving existing drawing controls preserves their state and listeners.
export function syncFullscreenChrome() {
  if (!fullscreenControlHomes.length) {
    fullscreenControlHomes = ['rail', 'mobilebar'].map(id => { const node = el(id); return [node, node?.parentNode]; });
  }
  if (isChartFull() && app.fullscreenPane === 2 && !app.chart2) {
    app.fullscreenPane = null;
    document.exitFullscreen().catch(() => {});
  }
  const pane = isChartFull() ? app.fullscreenPane : null;
  if (pane) document.body.dataset.fullscreenPane = String(pane);
  else {
    delete document.body.dataset.fullscreenPane;
  }
  const secondary = pane === 2 ? el('chart2')?.parentElement : null;
  for (const [node, home] of fullscreenControlHomes) {
    const parent = secondary || home;
    if (node && parent && node.parentNode !== parent) parent.appendChild(node);
  }
  // The rail's fold tab and its chart offset live beside the rail, so they follow it.
  applyRailCollapsed();
}


function currentTarget(target) {
  if (target?.current()) return true;
  el('status').textContent = 'chart changed; open the control again';
  return false;
}

export function changeRequest(target, patch) {
  if (!currentTarget(target)) return;
  const request = { ...target.request, ...patch };
  request.period = clampPeriod(request.interval, request.period);
  if (target.pane === 2) {
    Object.assign(app.p2, request);
    app.loadSecondary();
  } else {
    for (const key of ['symbol', 'interval', 'period']) el(key).value = request[key];
    el('session').value = sessionOf(request);
    app.load();
  }
  renderToolbar();
}

/** What chart `pane` is drawn as: the type, and the options kept for each transform. */
export function shownType(pane) {
  return pane === 2 ? { chartType: app.p2.chartType || 'candlestick', transforms: app.p2.transforms || {} }
    : { chartType: el('ctype').value, transforms: app.transforms || {} };
}

/**
 * Rebuild the target's chart as `next` (`{ chartType, transforms }`). A
 * settings dialog that also recolours passes `colors` on both sides, so the
 * colours ride in the same step as the options: the style a rebuild carries
 * over is the old chart's, and an undo has to put the old colours back too.
 */
export function changeType(target, next, { label, fromColors, colors } = {}) {
  if (!currentTarget(target)) return;
  const busy = target.pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed;
  if (busy) { el('status').textContent = 'wait for chart history before changing its type'; return; }
  const pane = target.pane;
  const from = { ...shownType(pane), colors: fromColors };
  const to = { chartType: next.chartType, transforms: next.transforms ?? from.transforms, colors };
  // The type is a rebuild here, so the switch is recorded as a command that
  // rebuilds again: one step on that chart's timeline.
  const show = (type) => {
    const keepView = keepsView(shownType(pane), type);
    if (pane === 2) {
      app.p2.chartType = type.chartType;
      app.p2.transforms = type.transforms;
      app.rebuildSecondary({ typeChanged: true, keepView });
    } else {
      el('ctype').value = type.chartType;
      app.transforms = type.transforms;
      app.render({ keepView });
    }
    if (type.colors) withoutHistory(pane, () => (pane === 2 ? app.chart2 : app.chart)?.primarySeries()?.applyOptions(type.colors));
    renderToolbar();
    autosave();
  };
  show(to);
  recordChartType(pane, from, to, show, label);
}

/** Rebuild shared controls from their explicitly selected chart. */
export function renderToolbar() {
  closeSymbolSearch();
  closeIndicatorPicker();
  syncFullscreenChrome();
  const bar = el('shellbar');
  const pane = selectedPane(app);
  const target = capturePaneTarget(app, pane);
  const request = target?.request || app.req || {};
  const ctype = pane === 2 ? app.p2.chartType || 'candlestick' : el('ctype').value;
  // #status starts in the hidden legacy bar and gets moved in here on the
  // first render -- so from the second call on it is a child of `bar`, and
  // wiping the bar would destroy it. Every el('status') after that returns
  // null, and load()'s first line is a write to it, so changing symbol /
  // timeframe / range silently did nothing. Detach it first, and recreate
  // it if an earlier render already ate it.
  const statusText = el('status') || Object.assign(document.createElement('span'), { id: 'status' });
  if (statusText.parentElement) statusText.parentElement.removeChild(statusText);
  bar.innerHTML = '';

  const link = brandingLink(target?.chart);
  const brand = document.createElement(link ? 'a' : 'div');
  brand.className = 'brand';
  brand.title = link ? link.label : 'OpenAlgo Charts yfinance demo';
  if (link) {
    brand.setAttribute('href', link.href);
    brand.setAttribute('target', '_blank');
    brand.setAttribute('rel', 'noopener noreferrer');
    brand.setAttribute('aria-label', link.label);
  }
  brand.innerHTML =
    '<span class="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true">'
    + '<path d="M3 17.5 9 7l4 6.5L21 3v4.2l-8 10.3-4-6.5-3.6 6.5z"/></svg></span>'
    + '<span class="brand-name">OpenAlgo <em>yfinance</em></span>';
  bar.appendChild(brand);
  bar.appendChild(divider());

  if (isSplit()) {
    const selection = tbtn('Chart ' + pane, 'Selected chart');
    selection.classList.add('tbtn--chart');
    selection.addEventListener('click', () => popupMenu(selection, [1, 2].map(index => ({
      label: 'Chart ' + index, on: pane === index,
      onSelect: () => {
        if (isChartFull()) { app.fullscreenPane = index; syncFullscreenChrome(); }
        focusChart(index);
        el(index === 2 ? 'chart2' : 'chart').focus();
      },
    }))));
    bar.appendChild(selection);
  }

  // symbol
  const sym = tbtn(ticon('search') + '<b>' + esc((request.symbol || '').toUpperCase()) + '</b>', 'Change symbol');
  sym.addEventListener('click', () => {
    const symbolContext = app['inspection' + pane]?.context;
    if (!target?.current() || !symbolContext) return;
    closeSymbolSearch();
    const box = document.createElement('div');
    box.className = 'oac-menu host-symbol-search';
    const input = document.createElement('input');
    input.type = 'search';
    input.placeholder = 'Symbol or expression';
    input.setAttribute('aria-label', 'Symbol or expression');
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('spellcheck', 'false');
    box.appendChild(input);
    symbolSearchClose = symbolContext.openOverlay(box, {
      anchor: sym, placement: 'below', initialFocus: input,
      onClose: () => { symbolSearchClose = null; symbolPicker?.destroy(); symbolPicker = null; },
    });
    symbolPicker = mountSymbolPicker(symbolContext, input, {
      search: referenceSymbolSearch,
      context: () => target.current() ? `${pane}:${target.request.symbol}:${target.request.interval}` : 'changed',
      onSelect: symbol => { closeSymbolSearch(); changeRequest(target, { symbol }); },
    });
    input.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || event.defaultPrevented || !symbolPicker?.canCommitRaw()) return;
      const query = input.value.trim();
      if (!query) return;
      event.preventDefault();
      closeSymbolSearch();
      changeRequest(target, { symbol: query.toUpperCase() });
    });
  });
  bar.appendChild(sym);
  bar.appendChild(divider());

  // interval pills
  const ig = document.createElement('div');
  ig.className = 'pills';
  for (const iv of INTERVALS) {
    const b = document.createElement('button');
    b.textContent = intervalLabel(iv);
    b.title = intervalName(iv);
    b.className = request.interval === iv ? 'is-on' : '';
    b.setAttribute('aria-pressed', String(request.interval === iv));
    b.addEventListener('click', () => changeRequest(target, { interval: iv }));
    ig.appendChild(b);
  }
  bar.appendChild(ig);

  // range menu
  const range = tbtn('<span>' + esc(request.period || '') + '</span>' + ticon('chevron'), 'History range');
  // Only offer ranges this interval can actually serve: an unavailable one
  // comes back empty from Yahoo, which reads as a broken chart.
  range.addEventListener('click', () => popupMenu(range, periodsFor(request.interval).map((p) => ({
    label: p, on: p === request.period,
    onSelect: () => changeRequest(target, { period: p }),
  }))));
  bar.appendChild(range);
  // Trading session. Extended hours are the source's own pre and post market
  // bars, served only for intraday bars of a US listed stock, so the row is
  // greyed with the reason everywhere else. A chart already on extended hours
  // keeps that choice through an interval change and says it is unavailable,
  // rather than quietly showing regular hours under the old label.
  const session = sessionOf(request);
  const wire = foldedInterval(request.interval)?.foldFrom || request.interval;
  const extendedServed = extendedSessionAvailable(request.symbol, wire);
  const sessionButton = tbtn('<span>' + esc(sessionLabel(session)) + '</span>' + ticon('chevron'), 'Trading session',
    extendedServed ? 'Regular or extended hours' : 'Extended hours are served only for intraday bars of US listed stocks');
  sessionButton.id = 'session-menu';
  sessionButton.setAttribute('aria-haspopup', 'menu');
  if (session === 'extended') sessionButton.classList.add('is-on');
  sessionButton.addEventListener('click', () => popupMenu(sessionButton, [
    { label: sessionLabel('regular'), on: session === 'regular', onSelect: () => changeRequest(target, { session: 'regular' }) },
    { label: sessionLabel('extended'), on: session === 'extended', disabled: !extendedServed,
      reason: extendedServed ? '' : `Not available for ${request.symbol || 'this symbol'} at ${request.interval}`,
      onSelect: () => changeRequest(target, { session: 'extended' }) },
  ], { role: 'menu' }));
  bar.appendChild(sessionButton);
  // Go to a date or range, loading a longer period when the date is older
  // than the one on screen.
  const goTo = tbtn('<span>Go to</span>', 'Go to a date or range', 'Loads older history when it is needed');
  goTo.id = 'goto';
  goTo.setAttribute('aria-haspopup', 'dialog');
  goTo.disabled = !target?.current() || Boolean(pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed);
  goTo.addEventListener('click', () => openGoTo(goTo));
  bar.appendChild(goTo);
  bar.appendChild(divider());

  // chart type menu
  const ct = tbtn(ticon(chartTypeIcon(ctype)) + '<span>' + esc(chartTypeLabel(ctype)) + '</span>' + ticon('chevron'), 'Chart type');
  ct.disabled = Boolean(pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed);
  ct.addEventListener('click', () => popupMenu(ct, CHART_TYPES.map((t) => (t.group ? { group: t.group } : {
    label: t.label, icon: t.icon, on: t.v === ctype,
    onSelect: () => changeType(target, { chartType: t.v }),
  }))));
  bar.appendChild(ct);

  // The settings of a transform that has a dialog, beside the type, and only
  // while that type is the one drawn.
  if (typeOptions({ chartType: ctype })) {
    const set = iconBtn('tune', chartTypeLabel(ctype) + ' settings', () => openBoxSettings(target));
    set.id = 'box-settings';
    set.setAttribute('aria-haspopup', 'dialog');
    set.disabled = ct.disabled;
    bar.appendChild(set);
  }

  // indicators
  const ind = tbtn(ticon('indicators') + '<span>Indicators</span>', 'Add an indicator');
  ind.addEventListener('click', () => {
    if (!target?.current()) return;
    const context = app['inspection' + pane]?.context;
    if (!context) return;
    closeIndicatorPicker();
    indicatorPicker = mountIndicatorPicker(context, ind, { onAdd: () => {
      if (pane === 1) rememberIndicators();
      renderIndicatorChips();
      autosave();
    } });
  });
  bar.appendChild(ind);
  const PANELS = { data: ['Data', 'Data window'], objects: ['Objects', 'Chart objects'], watchlist: ['Watchlist', 'Watchlists and quotes'], news: ['News', 'News for this symbol'] };
  for (const [panel, [label, title]] of Object.entries(PANELS)) {
    const control = tbtn(label, title);
    control.setAttribute('aria-pressed', String(app['inspection' + pane]?.dock.state().panel === panel));
    control.addEventListener('click', () => toggleInspection(pane, panel));
    bar.appendChild(control);
  }
  const templates = tbtn('Templates', 'Indicator templates');
  templates.setAttribute('aria-label', 'Templates'); templates.setAttribute('aria-haspopup', 'dialog');
  templates.setAttribute('aria-controls', 'templatemodal');
  templates.addEventListener('click', () => { templates.focus(); app.openTemplates?.(); });
  bar.appendChild(templates);

  // compare: a second instrument on the price pane
  const comparisons = comparisonState(target?.pane).items;
  const cmp = tbtn(ticon('compare') + '<span>Compare</span>',
    comparisons.length ? `Comparing ${comparisons.map((c) => c.symbol).join(', ')}` : 'Compare a second symbol');
  if (comparisons.length) cmp.classList.add('is-on');
  cmp.disabled = !target?.current() || Boolean(app[pane === 2 ? 'loading2' : 'loading'] || app[pane === 2 ? 'loadFailed2' : 'loadFailed']);
  cmp.addEventListener('click', () => openCompare(target));
  bar.appendChild(cmp);

  const alerts = tbtn('<span>Alerts</span>', 'Alerts');
  alerts.addEventListener('click', () => openAlerts(app));
  bar.appendChild(alerts);

  // replay: enter the session bar by bar, or leave and get the chart back
  const rp = tbtn(ticon('replay') + '<span>Replay</span>',
    app.replay ? 'Exit replay' : app.replayLoading ? 'Cancel replay loading' : app.replayPicking ? 'Cancel bar selection' : 'Replay this session bar by bar');
  if (app.replay || app.replayPicking || app.replayLoading) rp.classList.add('is-on');
  rp.disabled = !app.replay && !app.replayPicking && !app.replayLoading
    && (!target?.current() || Boolean(app[pane === 2 ? 'loading2' : 'loading'] || app[pane === 2 ? 'loadFailed2' : 'loadFailed']));
  rp.addEventListener('click', () => ((app.replay || app.replayPicking || app.replayLoading) ? askExitReplay() : enterReplay()));
  bar.appendChild(rp);

  // Snapshot. The chart is a picture people share, and the two things they
  // do with it are save it and paste it, so both are one click from here.
  const snap = tbtn(ticon('camera'), 'Chart snapshot');
  snap.addEventListener('click', (e) => { e.stopPropagation(); openSnapMenu(snap); });
  bar.appendChild(snap);

  // Split view and the link switches. Two controls over one group: the
  // toggle opens the second chart, the menu decides what crosses between
  // them. Both report "unavailable" against a dist/ without linking rather
  // than sitting there dead.
  const sp = iconBtn('split', app.linkGroup
    ? (isSplit() ? 'Close the second chart' : 'Open a second, linked chart')
    : 'Split view needs a dist/ with chart linking',
    () => (isSplit() ? closeSplit() : openSplit()));
  if (isSplit()) sp.classList.add('is-on');
  bar.appendChild(sp);

  const lk = iconBtn('link', app.linkGroup
    ? 'Chart linking (' + describeLink() + ')'
    : 'Chart linking needs a newer dist/',
    () => openLinkMenu(lk));
  if (app.linkGroup && isSplit() && describeLink() !== 'nothing synced') lk.classList.add('is-on');
  bar.appendChild(lk);
  const events = tbtn('Events', 'Timeline events (sample data)');
  events.addEventListener('click', event => { event.stopPropagation(); openTimelineMenu(app, events); });
  bar.appendChild(events);

  // Bar cache. The counter is the point: a feature you can only feel as
  // "that seemed quicker" is a feature nobody can check.
  if (app.cache) {
    const s = app.cache.stats();
    const cc = tbtn(ticon('cache') + '<span>' + s.hits + '/' + (s.hits + s.misses) + '</span>',
      `Bar cache: ${s.hits} warm of ${plural(s.hits + s.misses, 'load')}, ${s.entries} series held`);
    if (s.hits > 0) cc.classList.add('is-on');
    cc.addEventListener('click', () => openCacheMenu(cc));
    bar.appendChild(cc);
  }
  bar.appendChild(divider());

  // view + layout icons
  const fit = iconBtn('fit', 'Reset view', () => {
    if (currentTarget(target) && target.chart.navigationOptions?.().zoomEnabled !== false) target.chart.resetScale();
  });
  fit.id = 'toolbar-fit';
  bar.appendChild(fit);
  // Anchor on the button that was clicked: by the time the handler runs,
  // bar.lastChild is whatever the toolbar appended last, not this button.
  bar.appendChild(iconBtn('grid', 'Grid', (ev) => {
    if (!currentTarget(target)) return;
    const grid = target.chart.gridOptions();
    popupMenu(ev.currentTarget, [
      ['Both', true, true], ['Horizontal', false, true], ['Vertical', true, false], ['None', false, false],
    ].map(([label, vertLines, horzLines]) => ({
      label, on: grid.vertLines === vertLines && grid.horzLines === horzLines,
      onSelect: () => {
        if (!currentTarget(target)) return;
        target.chart.setGridOptions({ vertLines, horzLines });
        if (target.pane === 1) { el('vgrid').checked = vertLines; el('hgrid').checked = horzLines; }
        autosave();
      },
    })));
  }));
  // The magnet is the rail's three-way mode (off, weak, strong); this button
  // cycles it, so the shell and the rail can never disagree.
  const mg = iconBtn('magnet', 'Magnet: ' + magnetMode(), () => { cycleMagnet(); renderToolbar(); },
    'Snaps anchors to a bar or study value: off, weak, strong');
  if (magnetMode() !== 'off') mg.classList.add('is-on');
  bar.appendChild(mg);
  bar.appendChild(iconBtn('camera', 'Save PNG', () => downloadSnapshot(target)));
  const fs = iconBtn(isChartFull() ? 'fullscreenExit' : 'fullscreen',
    isChartFull() ? 'Exit full screen (Esc)' : 'Full screen chart', toggleChartFullscreen);
  if (isChartFull()) fs.classList.add('is-on');
  bar.appendChild(fs);
  const light = currentTheme() === 'light';
  bar.appendChild(iconBtn(light ? 'moon' : 'sun', light ? 'Dark theme' : 'Light theme', () => { toggleTheme(); renderToolbar(); }));

  // Bracket entry. The buttons that own this live in the legacy sub-bar,
  // which is display:none, and a hidden ancestor takes its whole subtree out
  // of the box tree: they still fire when clicked programmatically, but a
  // user had no way to reach them, which also stranded the Trading tab's
  // entry and exit colours with nothing on the chart to recolour.
  bar.appendChild(divider());
  const buy = tbtn('<b>Buy</b>', 'Place a Buy OCO bracket: entry, target and stop', pane === 2 ? 'Trading is available on Chart 1' : undefined);
  buy.disabled = pane === 2;
  buy.classList.add('tbtn--buy');
  buy.addEventListener('click', () => { if (pane === 1 && currentTarget(target)) el('buy').click(); });
  bar.appendChild(buy);
  const sell = tbtn('<b>Sell</b>', 'Place a Sell OCO bracket: entry, target and stop', pane === 2 ? 'Trading is available on Chart 1' : undefined);
  sell.disabled = pane === 2;
  sell.classList.add('tbtn--sell');
  sell.addEventListener('click', () => { if (pane === 1 && currentTarget(target)) el('sell').click(); });
  bar.appendChild(sell);
  // The sandbox broker: the trade tier's account, preview and native close
  // contract against a simulated provider, beside the page's own simulation.
  const account = tbtn('<span>Account</span>', 'Sandbox broker account',
    pane === 2 ? 'The sandbox broker trades Chart 1' : 'Figures, preview, durations, native close and reverse');
  account.id = 'account';
  account.disabled = pane === 2;
  account.setAttribute('aria-haspopup', 'dialog');
  account.addEventListener('click', () => { if (pane === 1 && currentTarget(target)) app.openAccount?.(account); });
  bar.appendChild(account);

  bar.appendChild(divider());
  bar.appendChild(iconBtn('gear', 'Chart settings (or right-click the chart)', () => openChartSettings(undefined, target)));
  bar.appendChild(iconBtn('save', 'Save layout', () => el('lsave').click()));
  const layouts = tbtn('Layouts', 'Named layouts');
  layouts.setAttribute('aria-label', 'Layouts');
  layouts.setAttribute('aria-haspopup', 'dialog');
  layouts.setAttribute('aria-controls', 'workspacemodal');
  layouts.addEventListener('click', () => { layouts.focus(); app.openLayouts?.(); });
  bar.appendChild(layouts);

  const status = document.createElement('div');
  status.className = 'status';
  status.innerHTML = '<span class="status-dot"></span>';
  status.appendChild(statusText);
  // The readout truncates on a narrow window, so the full line has to be
  // reachable. Copied on hover rather than on write: a dozen call sites
  // assign to #status directly and every one of them would have to remember.
  status.addEventListener('pointerenter', () => { status.title = statusText.textContent; });
  bar.appendChild(status);
  syncNavigationControls();
  app.refreshWorkspaceControls?.();
}

export function tbtn(html, title, sub) {
  const b = document.createElement('button');
  b.className = 'tbtn';
  b.innerHTML = html;
  // Styled label rather than `title`: half of these buttons are a bare
  // glyph, and the native box arrives a second late in the wrong theme.
  attachTip(b, { title, sub, side: 'bottom' });
  // A button that shows words (a symbol, a range, a chart type) is named by
  // them too: the tip's title alone would hide the value on it.
  const shown = b.textContent.trim();
  if (shown !== '' && !title.toLowerCase().includes(shown.toLowerCase())) b.setAttribute('aria-label', `${title}, ${shown}`);
  return b;
}
export function iconBtn(icon, title, onClick, sub) {
  const b = tbtn(ticon(icon), title, sub);
  b.classList.add('tbtn--icon');
  b.addEventListener('click', onClick);
  return b;
}
export function divider() {
  const d = document.createElement('span');
  d.className = 'divider';
  return d;
}

export function initToolbar(a) {
  app = a;
  app.changeRequest = changeRequest;
  app.changeType = changeType;
  app.renderToolbar = renderToolbar;
  document.addEventListener('fullscreenchange', () => {
    if (!isChartFull()) app.fullscreenPane = null;
    hideTip(); syncFullscreenChrome(); renderToolbar();
  });
}
