import * as engine from '/dist/openalgo-charts.mjs';
import { createChart, PaneLegend } from '/dist/openalgo-charts.mjs';
import { attachAlerts, detachAlerts } from './alerts.js';
import { attachInspection, detachInspection } from './inspection.js';
import { DrawingController, DrawingLinkGroup } from '/dist/openalgo-charts.draw.mjs';
import { el, fmt, fmtVol, UP, DOWN, chartTheme, chartMotionOptions, toast, MOD } from './ui.js';
import { clipboardPort } from './clipboard.js';
import { armCursor, magnetMode, stayMode, syncMobileControls, observeMobileControls, focusChart, toolName } from './rail.js';
import { fetchBars, fetchNote, feedErrorState } from './feed.js';
import { attachComparison, comparisonState, invalidateComparisons, restoreComparisons, syncComparisons } from './compare.js';
import { autosave, stripView } from './persist.js';
import { intervalLabel, clampPeriod, INTERVALS } from './intervals.js';
import { tbtn, renderToolbar, CHART_TYPES } from './toolbar.js';
import { openContextMenu, closeMenu } from './menus.js';
import { attachVolume, refreshVolume, setVolumeLegend, applyVolumeSettings, volumeValues } from './volume.js';
import { referenceDataContext, isExpression, fetchExpressionBars } from './expression.js';
import { requestVariant, sessionOf } from './session.js';
import { chartTypeSeries, savedTransforms } from './transforms.js';
import { chartDecorationsForRebuild, normalizeLegendIconSize, restorePrimaryStyle } from './chart-settings.js';
import { bindIndicatorSource } from './indicator-source.js';
import { openSettings, renderIndicatorChips, watchStudyStatus } from './indicators.js';
import { capturePaneTarget } from './pane-target.js';
import { symbolStatus, exchangeOf, nameOf } from './status.js';
import { axisMinMove, sessionCalendarFor, tickScheduleFor } from './ticks.js';
import { attachReplay, exitReplay, syncReplayAlertPause } from './replay.js';
import { attachTimeline } from './timeline.js';
import { attachHistory, historyFor, withoutHistory } from './history.js';
import { scopeDrawings } from './drawing-scope.js';
import { attachCanvasTips } from './canvas-tips.js';

// 1.3 surfaces: chart linking, the bar cache and the interval registry.
// Same namespace read for the same reason: this page must still draw
// against an older dist/ and say which features that dist cannot serve,
// rather than failing at link time and showing a blank document.
const { createLinkGroup } = engine;

let app;
let price2 = null;
let bars2 = [];
let pane2LoadRevision = 0;
let restoreRevision = 0;
let pane2Controller = null;

// ══ split view: a second chart in the same link group ═══════════════════
//
// Linking needs two charts before any of it can be seen, so the demo grows
// a second one. It is deliberately not a clone: its own instrument and its
// own timeframe are what make the group's one real design decision visible.
// Nothing crosses the boundary as a bar index, so an hourly follower and a
// daily leader sit on the same instant rather than on the same nth bar.
//
// The group is created once and outlives every chart in it: `render()`
// destroys and rebuilds the main chart on a chart-type switch, and the
// group prunes the corpse and takes the replacement.

export function initSplit(a) {
  app = a;
  app.drawingLinkGroup = new DrawingLinkGroup();
  app.restoreSecondary = restoreSecondaryLayout;
  app.loadSecondary = loadPane2;
  app.rebuildSecondary = buildChart2;
  app.linkGroup = createLinkGroup
    ? createLinkGroup({ crosshair: true, viewport: true, symbol: false, whenMissing: 'nearest' })
    : null;

  /* Drag the divider. Percent rather than pixels, so the split survives a
     window resize as a proportion instead of pinning one side. */
  (function splitDrag() {
    const bar = el('splitbar');
    let dragging = false;
    bar.addEventListener('pointerdown', (e) => {
      dragging = true;
      bar.classList.add('is-drag');
      bar.setPointerCapture(e.pointerId);
    });
    bar.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      const box = el('split').getBoundingClientRect();
      const pct = Math.min(78, Math.max(18, ((box.right - e.clientX) / box.width) * 100));
      el('pane2').style.flexBasis = pct + '%';
    });
    const stop = (e) => {
      if (!dragging) return;
      dragging = false;
      bar.classList.remove('is-drag');
      if (e.pointerId !== undefined && bar.hasPointerCapture(e.pointerId)) bar.releasePointerCapture(e.pointerId);
    };
    bar.addEventListener('pointerup', stop);
    bar.addEventListener('pointercancel', stop);
  })();
}

export const isSplit = () => app.chart2 !== null;

/** Raw feed bars are needed to roll back a transformed chart without folding twice. */
export const secondaryRawBars = () => bars2.map(bar => ({ ...bar }));

/** Install already prepared history; no request or animation frame is awaited here. */
export function installSecondaryWorkspace(saved, bars) {
  closeSplit();
  if (!saved) return;
  app.p2 = { ...saved.request, chartType: saved.chartType || 'candlestick', transforms: savedTransforms(saved) || {},
    legendIconSize: normalizeLegendIconSize(saved.legendIconSize),
    timezone: saved.state?.timezone || app.chartTimezone };
  el('pane2').style.flexBasis = (saved.width ?? 50) + '%';
  el('pane2').hidden = false;
  el('splitbar').hidden = false;
  bars2 = bars.map(bar => ({ ...bar }));
  applyVolumeSettings(2, saved.volumeSettings || { 'volume.visible': saved.volume !== false });
  restoreComparisons(saved, 2);
  buildChart2({ state: saved.state });
  setPane2Note(`${bars2.length} bars`);
  renderPane2Bar();
}

/**
 * Join (or re-join) both charts. Adding a chart already in the group only
 * refreshes its member options, so this is safe to call on every rebuild,
 * which is exactly what a chart-type switch needs.
 */
export function joinLink() {
  if (!app.linkGroup) return;
  if (app.chart) {
    app.linkGroup.add(app.chart, {
      appearance: appearanceAdapter(app.chart, 1),
      symbol: app.req.symbol,
      interval: app.req.interval,
      onInterval: interval => {
        if (!INTERVALS.includes(interval)) return false;
        if (el('interval').value === interval) return;
        el('interval').value = interval;
        el('period').value = clampPeriod(interval, el('period').value);
        app.load();
      },
      // The group loads nothing itself: it hands the host a symbol and the
      // host fetches. This is the whole of the engine's symbol story.
      onSymbol: (sym) => {
        if (el('symbol').value === sym) return;
        el('symbol').value = sym;
        app.load();
      },
    });
  }
  if (app.chart2) {
    app.linkGroup.add(app.chart2, {
      appearance: appearanceAdapter(app.chart2, 2),
      symbol: app.p2.symbol,
      interval: app.p2.interval,
      onInterval: interval => {
        if (!INTERVALS.includes(interval)) return false;
        if (app.p2.interval === interval) return;
        app.p2.interval = interval;
        loadPane2();
      },
      onSymbol: (sym) => {
        if (app.p2.symbol === sym) return;
        app.p2.symbol = sym;
        loadPane2();
      },
    });
  }
  if (app.chart && app.draw) app.drawingLinkGroup.add(app.chart, app.draw, drawingContextReader(app.chart));
  if (app.chart2 && app.draw2) app.drawingLinkGroup.add(app.chart2, app.draw2, drawingContextReader(app.chart2));
}

// Qualified feed tickers are unique within this host's data namespace.
export const drawingLinkContext = request => ({ symbol: request.symbol, exchange: 'YFINANCE' });
const drawingContextReader = chart => () => drawingLinkContext(chart.getDataContext() || {});

// A linked change is the other chart's step, taken back on its timeline and
// sent here again; on this chart's own timeline it is never a step.
function appearanceAdapter(chart, pane) {
  return {
    read: () => engine.readChartSettings(chart),
    apply: values => withoutHistory(pane, () => engine.applyChartSettings(chart, values)),
  };
}

export async function openSplit() {
  if (!app.linkGroup) { el('status').textContent = 'this dist/ has no chart linking'; return; }
  if (isSplit()) return;
  el('pane2').hidden = false;
  el('splitbar').hidden = false;
  buildChart2();
  renderPane2Bar();
  renderToolbar();
  return loadPane2();
}

export function closeSplit() {
  exitReplay(2);
  pane2LoadRevision++;
  pane2Controller?.abort();
  pane2Controller = null;
  app.loading2 = false;
  app.loadFailed2 = false;
  if (app.chart2) {
    detachInspection(app, 2);
    detachAlerts(app, 2);
    if (app.linkGroup) app.linkGroup.remove(app.chart2);
    if (app.instrumentDrawings2) { app.instrumentDrawings2.destroy(); app.instrumentDrawings2 = null; }
    if (app.draw2) { app.draw2.destroy(); app.draw2 = null; }
    app.offCanvasTips2?.(); app.offCanvasTips2 = null;
    app.chart2.destroy();
    // A split opened again is a new second chart, with nothing to take back yet.
    historyFor(2)?.clear();
    app.chart2 = null; price2 = null; app.volume2 = null;
    app.symbolLegend2 = null; app.volLegend2 = null; app.volumeMA2 = null;
    app.volumeReadings2 = null;
    app.comparisons2 = [];
    app.cmpBaseMode2 = null;
  }
  bars2 = [];
  el('pane2').hidden = true;
  el('splitbar').hidden = true;
  el('chart2').innerHTML = '';
  focusChart(1);
  renderToolbar();
  autosave();
}

/** Restore the second chart only after its own history is available. */
export async function restoreSecondaryLayout(saved, selected = 1) {
  const revision = ++restoreRevision;
  app.restoringSecondary = true;
  try {
    closeSplit();
    if (!saved) return true;
    const req = saved.request;
    if (!req || !['symbol', 'interval', 'period'].every(key => typeof req[key] === 'string' && req[key].length > 0 && req[key].length <= 256)) {
      throw new Error('The second chart has invalid instrument settings');
    }
    const chartType = saved.chartType || 'candlestick';
    const transforms = savedTransforms(saved);
    if (!CHART_TYPES.some(type => type.v === chartType) || transforms === null) {
      throw new Error('The second chart has invalid chart type settings');
    }
    if (req.session !== undefined && !['regular', 'extended'].includes(req.session)) {
      throw new Error('The second chart has an invalid session');
    }
    app.p2 = { symbol: req.symbol, interval: req.interval, period: req.period, chartType, transforms,
      ...(req.session === 'extended' ? { session: 'extended' } : {}),
      legendIconSize: normalizeLegendIconSize(saved.legendIconSize),
      timezone: saved.state?.timezone || app.chartTimezone };
    app.inspectionState2 = saved.inspection || { panel: null, width: 300 };
    if (Number.isFinite(saved.width)) el('pane2').style.flexBasis = Math.max(18, Math.min(78, saved.width)) + '%';
    const legacyVisible = saved.state?.series?.find(series => series.type === 'histogram')?.style?.visible !== false;
    applyVolumeSettings(2, volumeValues(saved.volumeSettings || { 'volume.visible': legacyVisible }));
    restoreComparisons(saved, 2);
    const loaded = await openSplit();
    const restoredChart = app.chart2;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (revision !== restoreRevision || !loaded || !restoredChart || app.chart2 !== restoredChart
      || !['symbol', 'interval', 'period'].every(key => app.p2[key] === req[key]) || sessionOf(app.p2) !== sessionOf(req)) return false;
    let report;
    withoutViewportSync(() => { report = app.chart2.restoreState(saved.state); });
    if (!report.applied) throw new Error('The second chart layout could not be restored');
    restorePrimaryStyle(app.chart2, saved.state);
    refreshVolume(2);
    for (const spec of comparisonState(2).items) attachComparison(spec, 2);
    focusChart(selected);
    renderToolbar();
    return true;
  } catch (error) {
    if (revision === restoreRevision) toast('error', error.message || 'The second chart could not be restored');
    return false;
  } finally {
    if (revision === restoreRevision) { app.restoringSecondary = false; autosave(); }
  }
}

export function buildChart2({ keepView = true, typeChanged = false, state } = {}) {
  exitReplay(2);
  const previous = state || app.chart2?.getState();
  const saved = previous && (keepView ? previous : stripView(previous));
  const decorations = chartDecorationsForRebuild(app.chart2);
  detachInspection(app, 2);
  detachAlerts(app, 2);
  const dataContext = referenceDataContext(app.p2, app.chart2?.getDataContext());
  if (app.instrumentDrawings2) { app.instrumentDrawings2.destroy(); app.instrumentDrawings2 = null; }
  if (app.chart2) { if (app.linkGroup) app.linkGroup.remove(app.chart2); app.chart2.destroy(); }
  if (app.draw2) { app.draw2.destroy(); app.draw2 = null; }
  el('chart2').innerHTML = '';
  app.chart2 = createChart(el('chart2'), {
    theme: chartTheme(),
    // A drag moves time and leaves the price scale fitting what is in view,
    // and the wheel zooms about the latest bar (Ctrl or Cmd: about the cursor).
    navigation: { defaultBarSpacing: 8, mousePan: 'horizontal' },
    zoomAnchor: 'right',
    priceAxisWidth: 62,
    legendIconSize: normalizeLegendIconSize(app.p2.legendIconSize),
    grid: { vertLines: el('vgrid').checked, horzLines: el('hgrid').checked },
    timezone: app.p2.timezone || app.chartTimezone,
    // As on the main chart: the price pane moves from the right-click menu.
    movablePrimaryPane: true,
    ...chartMotionOptions(),
    ...decorations,
  });
  app.p2.timezone = app.chart2.timezone();
  app.chart2.setDataContext(dataContext);
  app.symbolLegend2 = new PaneLegend({ id: 'symbol', title: app.p2.symbol, row: 0, actions: [],
    status: () => symbolStatus({ symbol: app.p2.symbol, bars: app.chart2.primaryBars(), timezone: app.chart2.timezone(), session: sessionOf(app.p2) }),
  });
  app.chart2.addPrimitive(app.symbolLegend2);
  const chartType = app.p2.chartType || 'candlestick';
  const transformed = chartType.startsWith('t:');
  // The chart applies the transform to the raw bars, as on the main chart.
  const { type, transform } = chartTypeSeries(chartType, app.p2.transforms);
  const style = type === 'baseline'
    ? { baseValue: bars2.reduce((sum, bar) => sum + bar.close, 0) / (bars2.length || 1) } : {};
  price2 = app.chart2.addSeries(type, { style, ...(transform ? { transform } : {}) });
  price2.setData(bars2);
  // The second chart's own venue hours, as on the main chart.
  app.chart2.dataLayer.setSessionCalendar?.(sessionCalendarFor(app.p2.symbol));
  app.chart2.setPriceScaleOptions({ minMove: axisMinMove(app.p2.symbol, /\.(NS|BO)$/i.test(app.p2.symbol) ? 0.05 : 0.01) });
  app.chart2.setTickSchedule?.(tickScheduleFor(app.p2.symbol));
  attachVolume(2, !transformed || chartType === 't:heikin-ashi');
  app.chart2.subscribeCrosshairMove((e) => setPane2Legend(e.bar ?? app.chart2.primaryBars().at(-1)));
  attachReplay(app.chart2, 2, setPane2Legend);
  setPane2Legend(app.chart2.primaryBars().at(-1));
  // A second drawing controller, so paste has somewhere else to land: the
  // in-memory clipboard is shared by every controller on the page, which is
  // what makes chart-to-chart paste work with the OS permission refused.
  // Seeded from the rail's modes, which the rail re-asserts on any
  // controller it later observes; the seed only keeps the first drawing on
  // this side from landing before that.
  app.draw2 = new DrawingController(app.chart2, { magnet: magnetMode(), stayInDrawingMode: stayMode(), clipboard: clipboardPort });
  observeMobileControls(app.chart2, app.draw2);
  attachAlerts(app, 2);
  app.chart2.on('contextmenu', event => { event.preventDefault(); openContextMenu(event, 2); });
  app.chart2.on('destroy', closeMenu);
  app.chart2.on('indicatorSettings', ({ instanceId }) => openSettings(instanceId, capturePaneTarget(app, 2)));
  bindIndicatorSource(app.chart2, 2);
  app.chart2.on('indicatorRemoved', renderIndicatorChips);
  watchStudyStatus(app.chart2);
  if (saved) {
    const report = app.chart2.restoreState(typeChanged ? { ...saved, series: [] } : saved);
    if (state && !report.applied) throw new Error('The second chart state could not be restored');
  }
  // As on the main chart: a rebuild or a layout brings this symbol's drawings.
  app.instrumentDrawings2 = scopeDrawings(app.chart2, app.draw2, 2, saved ? 'live' : 'stored');
  restorePrimaryStyle(app.chart2, saved);
  refreshVolume(2);
  for (const spec of comparisonState(2).items) attachComparison(spec, 2);
  if (app.focusPane === 2) renderIndicatorChips();
  app.chart2.on('draw:tool', ({ tool }) => {
    armCursor(el('chart2'), tool);
    if (app.focusPane === 2) syncMobileControls(tool);
  });
  app.chart2.on('draw:add', () => { el('status').textContent = 'Chart 2: ' + app.draw2.drawings().length + ' drawings'; });
  app.offCanvasTips2 = attachCanvasTips(app.chart2, el('chart2'), 2);
  for (const event of ['draw:add', 'draw:remove', 'draw:update', 'indicatorAdded', 'indicatorRemoved', 'indicatorUpdated', 'paneCollapsed']) app.chart2.on(event, autosave);
  // No properties widget over here (it is glued to the main chart's box),
  // but the chords apply to the selected plot, so the
  // selection has to say so on this side too.
  app.chart2.on('draw:select', ({ id }) => {
    const d = id ? app.draw2.get(id) : null;
    if (d && typeof app.draw2.copy === 'function') {
      el('status').textContent = `Chart 2: ${toolName(d.tool)} selected · ${MOD}+C copy · ${MOD}+X cut · ${MOD}+V paste`;
    }
  });
  joinLink();
  attachTimeline(app, 2, bars2);
  attachInspection(app, 2);
  // Last, as on the main chart: the build is not a step, and the second
  // chart's timeline carries over its rebuilds.
  attachHistory(2);
}

export async function loadPane2() {
  if (!app.chart2) return false;
  exitReplay(2);
  const revision = ++pane2LoadRevision;
  invalidateComparisons(2);
  const chart = app.chart2;
  const state = chart.getState();
  const before = chart.getDataContext();
  pane2Controller?.abort();
  const controller = new AbortController();
  pane2Controller = controller;
  app.loading2 = true;
  app.loadFailed2 = false;
  app.alerts2?.setPaused(true);
  app.p2.period = clampPeriod(app.p2.interval, app.p2.period);
  const request = { ...app.p2 };
  const identityChanged = before?.symbol !== request.symbol || before?.interval !== request.interval
    || before?.variant?.session !== requestVariant(request)?.session;
  const keepView = chart.primaryBars().length > 0 && !identityChanged;
  // Clear while the old context still owns these bars; a refresh keeps its view.
  if (identityChanged) {
    bars2 = [];
    price2.setData([]);
    app.volume2?.setData([]);
    setPane2Legend(null);
  }
  // A session change alone is a new source, which only the helper makes the chart see.
  const context = referenceDataContext(app.p2, app.chart2.getDataContext());
  if (engine.publishDataContext) engine.publishDataContext(app.chart2, context);
  else app.chart2.setDataContext(context);
  if (app.linkGroup) app.linkGroup.setSymbol(chart, request.symbol);
  app.linkGroup?.setInterval?.(chart, request.interval);
  app.drawingLinkGroup?.setContext(chart, drawingLinkContext(request));
  // Context cleanup may remove copies received for the previous instrument.
  state.drawings = chart.drawingState();
  setPane2Note('loading ' + app.p2.symbol + ' ' + intervalLabel(app.p2.interval) + '...');
  renderToolbar();
  try {
    const variant = requestVariant(request);
    const loaded = isExpression(request.symbol)
      ? (await fetchExpressionBars(request.symbol, request.interval, request.period, { signal: controller.signal, timezone: request.timezone, variant })).bars
      : await fetchBars(request.symbol, request.interval, request.period, { signal: controller.signal, timezone: request.timezone, variant });
    if (revision !== pane2LoadRevision || app.chart2 !== chart) return false;
    bars2 = loaded;
    const note = `${bars2.length} bars${fetchNote()}`;
    buildChart2({ state, keepView });
    const loadedChart = app.chart2;
    if (!keepView || !state.viewport) placePane2View();
    setPane2Legend(app.chart2.primaryBars().at(-1));
    setPane2Note(note);
    renderPane2Bar();
    await syncComparisons(2);
    if (revision !== pane2LoadRevision || app.chart2 !== loadedChart) return false;
    return true;
  } catch (e) {
    if (revision !== pane2LoadRevision) return false;
    const fault = feedErrorState(e);
    if (fault.state === 'aborted') return false;
    app.loadFailed2 = true;
    setPane2Note((fault.state === 'unsupported' ? '' : 'error: ') + fault.message);
    return false;
  } finally {
    if (revision === pane2LoadRevision) {
      app.loading2 = false;
      if (pane2Controller === controller) pane2Controller = null;
      syncReplayAlertPause();
      renderToolbar();
      if (!app.loadFailed2) autosave();
    }
  }
}

/**
 * A freshly loaded follower restores its own default view, with sync
 * suspended, because a fit is not a pan. Two things went wrong without
 * this. Letting the fit broadcast threw the main chart off whatever window
 * the user had it on and replaced it with a month of the follower's
 * history, which reads as the split having broken the chart underneath it.
 * Adopting the leader's window instead is time-correct and looks broken for
 * the opposite reason: a year of daily bars mapped onto one month of hourly
 * ones leaves the follower's data as a sliver in the middle of an empty
 * plot. So the two windows start independent and converge on the first pan
 * or zoom, which is exactly what the group documents viewport sync to do.
 */
export function placePane2View() {
  withoutViewportSync(() => app.chart2.resetScale());
}

/** Run `fn` with viewport mirroring off, then put it back as it was. */
export function withoutViewportSync(fn) {
  if (!app.linkGroup || !app.linkGroup.options().viewport) { fn(); return; }
  app.linkGroup.setOptions({ viewport: false });
  try { fn(); } finally { app.linkGroup.setOptions({ viewport: true }); }
}

/* Kept on `p2` as well as on the node: renderPane2Bar() rebuilds the header
   from scratch, and the note would otherwise blank on every interval click. */
export function setPane2Note(text) {
  app.p2.note = text;
  const n = el('p2bar').querySelector('.p2note');
  if (n) n.textContent = text;
}

export function setPane2Legend(bar) {
  const legend = app.symbolLegend2;
  if (!legend) return;
  legend.setOptions({ title: nameOf(app.p2.symbol), params: intervalLabel(app.p2.interval) + ' ' + exchangeOf(app.p2.symbol) });
  setVolumeLegend(bar, 2);
  if (!bar) { legend.setValues([]); return; }
  const color = bar.close >= bar.open ? UP : DOWN;
  const bars = app.chart2.primaryBars();
  const index = bars.findIndex(item => item.time === bar.time);
  const previous = index > 0 ? bars[index - 1].close : bar.open;
  const change = bar.close - previous;
  const sign = change >= 0 ? '+' : '';
  const percent = previous ? 100 * change / previous : 0;
  legend.setValues([
    { label: 'O', text: fmt(bar.open), color, field: 'ohlc' },
    { label: 'H', text: fmt(bar.high), color, field: 'ohlc' },
    { label: 'L', text: fmt(bar.low), color, field: 'ohlc' },
    { label: 'C', text: fmt(bar.close), color, field: 'ohlc', priority: 10 },
    { text: `${sign}${fmt(change)} (${sign}${percent.toFixed(2)}%)`, color: change >= 0 ? UP : DOWN, field: 'change' },
    ...(app.chart2.hasOpenInterest !== false && Number.isFinite(bar.oi)
      ? [{ label: 'OI', text: fmtVol(bar.oi), color, field: 'openInterest' }] : []),
  ]);
}

/** Pane identification and status; editing controls belong to the shared toolbar. */
export function renderPane2Bar() {
  const bar = el('p2bar');
  bar.innerHTML = '';
  const select = tbtn('Chart 2', 'Select Chart 2');
  select.addEventListener('click', () => { focusChart(2); el('chart2').focus(); });
  bar.appendChild(select);

  const note = document.createElement('span');
  note.className = 'p2note';
  note.textContent = app.p2.note || '';
  bar.appendChild(note);

  const x = tbtn('&times;', 'Close the second chart');
  x.classList.add('tbtn--icon');
  x.addEventListener('click', closeSplit);
  bar.appendChild(x);
}
