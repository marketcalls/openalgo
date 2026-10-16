// Composition root of the yfinance demo. Creates the shared `app` state, wires
// every module to it in the order the page needs, and owns the two operations
// everything else reaches back to: render() builds the chart from the cached
// bars and load() fetches them.
import * as engine from '/dist/openalgo-charts.mjs';
import { createChart, PaneLegend } from '/dist/openalgo-charts.mjs';
// Lazy tiers. Each registers into the base bundle's registries as a side
// effect of being imported, so `setSeriesTransform({ type: 'renko' })` and
// `addIndicator('macd')` resolve afterwards. The transform and draw tiers are
// imported by the modules that call into them; the indicators tier is only
// ever registered, so it is imported here.
import '/dist/openalgo-charts.indicators.mjs';
// The bottom bar and its ranges, read off the namespace like the engine's newer surfaces below.
import * as widgetTier from '/dist/openalgo-charts.widget.mjs';
import { el, initShell, chartTheme, chartMotionOptions, setChartState, toast, currentTheme } from './ui.js';
import { initHover } from './hover.js';
import { fillIntervalSelect, clampPeriod, rangeLoad } from './intervals.js';
import { initFeed, fetchBars, fetchNote, feedErrorState } from './feed.js';
import { chartTypeSeries, inChartTransforms, keepsView } from './transforms.js';
import { isExpression, fetchExpressionBars, mountOperatorKeypad, referenceDataContext } from './expression.js';
import { initStatus, nameOf, symbolStatus } from './status.js';
import { requestVariant, sessionOf, sessionLabel } from './session.js';
import { DEFAULT_TZ, initTimezone, syncTimezoneFromChart } from './timezone.js';
import { initAxisChrome, applyAxisChrome, applyStatusLineChoice, applyTradeChoice, followBottombar } from './axis-chrome.js';
import { initVolume, attachVolume, refreshVolume, setVolumeShown, setLegend, applyVolumeSettings } from './volume.js';
import {
  initOrders, saveState, restoreState, cancelOrder, attachOrderLines, removeAllOrders,
  updatePositionLine, restyleTradeChrome, clearPosition, executionAllowed, repriceOrder,
} from './orders.js';
import { tickScheduleFor, axisMinMove, sessionCalendarFor } from './ticks.js';
import { initBracket, attachBracketLines, setBracketPrice, updateBracket, removeBracket } from './bracket.js';
import { initAccount } from './account.js';
import { initIndicators, fillIndicatorPicker, renderIndicatorChips, openSettings, rememberIndicators, watchStudyStatus } from './indicators.js';
import { afterChartSettingsWrite, chartDecorationsForRebuild, initChartSettings, normalizeLegendIconSize, restorePrimaryStyle } from './chart-settings.js';
import { initBoxSettings } from './box-settings.js';
import { initHistory, attachHistory, historyFor, recordChartType } from './history.js';
import { bindIndicatorSource, initIndicatorSource } from './indicator-source.js';
import { initRoutedStudy } from './routed-study.js';
import { initAnchoredStudy } from './anchored-study.js';
import { initCompare, attachComparison, invalidateComparisons, syncComparisons, restoreComparisons } from './compare.js';
import { initSnapshot } from './snapshot.js';
import { initReplay, exitReplay, attachReplay, syncReplayAlertPause } from './replay.js';
import { initSplit, joinLink, installSecondaryWorkspace, drawingLinkContext } from './split.js';
import { initLink } from './link.js';
import { initClipboard } from './clipboard.js';
import { initMenus, openContextMenu } from './menus.js';
import { initPersist, datasetKey, applyLayout, stripView, autosave, restorePrimarySelection, primaryLayoutSelection } from './persist.js';
import { attachAlerts, detachAlerts } from './alerts.js';
import { initInspection, attachInspection, detachInspection } from './inspection.js';
import { initToolbar, renderToolbar } from './toolbar.js';
import { initRail, buildRail, initMobile, focusChart, setMagnetMode, setStayMode } from './rail.js';
import { initWorkspaceHost } from './workspace-host.js';
import { initWorkspaces } from './workspaces.js';
import { initTemplates } from './templates.js';
import { mountPropertiesBar } from './properties.js';
import { initDrawing, attachDrawing } from './drawing.js';
import { scopeDrawings } from './drawing-scope.js';
import { capturePaneTarget, selectedPane } from './pane-target.js';
import { attachTimeline } from './timeline.js';
import { initGoTo, openGoTo } from './goto.js';
import { attachCanvasTips } from './canvas-tips.js';

// Price-level family (previous close, session extremes, extended hours,
// bid/ask). Read off the namespace rather than named above on purpose: a
// missing named import fails the whole module at link time, and an older
// dist/ should still draw a chart, with the level submenus simply reporting
// themselves unavailable.
const { PriceLevels } = engine;
// 1.3 surfaces: chart linking, the bar cache and the interval registry.
// Same namespace read for the same reason: this page must still draw
// against an older dist/ and say which features that dist cannot serve,
// rather than failing at link time and showing a blank document.
const { createLinkGroup, withBarCache, barCloseSec, registerInterval, bucketStartOf } = engine;
// A session change alone is a change of source, which only this helper makes
// the chart see; a dist/ from before sessions sets the context directly.
const publishContext = (chart, context) => (engine.publishDataContext
  ? engine.publishDataContext(chart, context) : chart.setDataContext(context));

/**
 * A tick size for the demo, by market. yfinance does not report one, and a
 * guess stated openly is better than a silent 0, which the price scale
 * reads as "work the precision out from the range".
 */
const tickFor = (sym) => (/\.(NS|BO)$/i.test(String(sym || '')) ? 0.05 : 0.01);
/**
 * What this dist/ cannot do. Collected rather than thrown so one missing
 * feature does not take the other three down with it, and reported once in
 * the status line: a demo that silently drops a control is exactly the
 * failure mode the controls are here to rule out.
 */
const MISSING = [];
if (!createLinkGroup) MISSING.push('chart linking');
if (!withBarCache || !barCloseSec) MISSING.push('bar cache');
if (!registerInterval || !bucketStartOf) MISSING.push('interval registry');
if (!inChartTransforms) MISSING.push('in-chart transforms');

/**
 * The demo's shared state, created here and handed to every module's init.
 * A chart-type switch destroys and rebuilds the chart, so anything that has
 * to outlive a rebuild (the indicator specs, the zone, the trade chrome, the
 * comparisons) lives here rather than on the chart.
 */
const app = {
  // The chart and its two series. `volume` is null on a chart whose transform
  // forms elements at times of its own (all but Heikin Ashi).
  chart: null,
  price: null,
  volume: null,
  // The price-level primitive on the price pane, plus the level styles as the
  // menu left them. The primitive belongs to the chart and dies with it; the
  // styles are the demo's, the way activeIndicators are, so a chart-type
  // switch does not quietly put every level back to its default.
  priceLevels: null,
  priceLevelState: {},
  // Active indicators, as {indicatorId, settings} specs. They are re-applied on
  // every chart rebuild (a chart-type switch destroys and recreates the chart),
  // which is also exactly what chart.getState()/restoreState() persists.
  activeIndicators: [{ indicatorId: 'halftrend', settings: {} }, { indicatorId: 'rsi', settings: {} }],
  // Resting orders placed by right-click: each is one draggable price line.
  orders: [],            // { id, side, type, price, qty, product, line }
  nextOrderId: 1,
  // Market fills build a net position (avg price) shown as a solid line + arrow markers.
  position: null,        // { netQty, avgPrice }
  posLine: null,         // PriceLine for the position
  fills: [],             // marker list for executed market orders
  markersApi: null,      // SeriesMarkers handle on the price series
  currentBars: [],       // cached so a chart-type switch needs no refetch
  // Options per transform, as the point and figure and Renko dialogs left
  // them ({ 'point-figure': {...}, renko: {...} }); one left out draws with
  // its defaults (transforms.js). The second chart keeps its own on app.p2.
  transforms: {},
  idxByTime: new Map(),  // bar time -> array index (for previous-close lookup)
  req: {},               // last-loaded request (symbol/interval/period)
  // The chart's zone, mirrored: the engine persists it in getState(), but a
  // rebuilt chart starts on the default again unless it is handed back.
  chartTimezone: DEFAULT_TZ,
  // Row 0 of the price pane and the volume row. PaneLegends like every
  // indicator row, not a floating DOM box: an opaque overlay sat on top of the
  // indicator legends and hid them, whereas rows share one stack.
  symbolLegend: null,
  volLegend: null,
  bracket: null,         // { side, entry, target, stop, qty }
  bLines: null,          // { entry, tp, sl } price-line primitives on the current chart
  // The loaded symbol's tick schedule, when the host holds one (see ticks.js).
  // Null means two-decimal order prices, which is every symbol but one.
  ticks: null,
  // { symbol, color, bars, handle, legend, byTime, hidden }. The spec survives
  // a chart rebuild and a saved layout; the handle and legend do not.
  comparisons: [],
  cmpMode: 'percentage',
  comparisons2: [],
  cmpMode2: 'percentage',
  // Market replay: the controller, and the pick state while the user is
  // choosing the bar to start from. One shade per pane, because the future
  // has to be hidden on all of them.
  replay: null,
  replayTarget: null,
  replayTargets: [],
  replayScope: 'focused',
  replayLoading: false,
  replayPicking: false,
  replayPickIndex: null,
  // The link group and the second chart of the split view. A different
  // instrument AND a different timeframe from the main chart on purpose: an
  // hourly follower beside a daily leader is the only way to see that the
  // group crosses the boundary as an instant, not as a bar index.
  linkGroup: null,
  chart2: null,
  volume2: null,
  draw2: null,
  p2: { symbol: 'MSFT', interval: '1h', period: '1mo', note: '' },
  focusPane: 1,          // selected chart for shared controls and clipboard shortcuts
  // The main chart's drawing controller, and the tool id -> chord table the
  // rail labels its rows from once the draw tier has answered.
  draw: null,
  // What keeps each chart's drawings per symbol (drawing-scope.js). Rebuilt
  // with the chart it follows.
  instrumentDrawings: null,
  instrumentDrawings2: null,
  shortcuts: {},
  cache: null,           // the bar cache wrapping the feed; null on a dist/ without one
  offBranding: null,     // refreshes the host link when setBranding changes at runtime
  load: null,            // set below: the modules reach the loader through the app
  bottombar: null,       // the widget tier's bottom bar under the stage (initBottombar)
};
app.load = load;
app.render = render;

// The e2e suite drives the page through this handle, and only when asked to:
// a demo should not put its internals on window by default.
if (new URLSearchParams(location.search).get('test') === '1') {
  window.__oac = { get chart() { return app.chart; }, get draw() { return app.draw; }, app };
}

// (Re)build the chart for the currently selected type using cached bars.
function render({ keepView = true, state } = {}) {
  // Leave replay first: stop() hands the driven series their real data back,
  // and it has to reach the chart that is about to be thrown away.
  exitReplay(1);
  const previousState = state || app.chart?.getState();
  const rebuildState = previousState && (keepView ? previousState : stripView(previousState));
  const decorations = chartDecorationsForRebuild(app.chart);
  if (state) decorations.legendIconSize = normalizeLegendIconSize(state.legendIconSize);
  const dataContext = referenceDataContext(app.req, app.chart?.getDataContext());
  if (app.offBranding) { app.offBranding(); app.offBranding = null; }
  detachInspection(app);
  detachAlerts(app);
  if (app.instrumentDrawings) { app.instrumentDrawings.destroy(); app.instrumentDrawings = null; }
  if (app.draw) { app.draw.destroy(); app.draw = null; }
  if (app.chart) app.chart.destroy();
  el('chart').innerHTML = '';
  app.chart = createChart(el('chart'), {
    // DEFAULT_THEME is the light palette; the shell's switch decides which.
    theme: chartTheme(),
    // A drag moves time and leaves the price scale fitting what is in view,
    // and the wheel zooms about the latest bar (Ctrl or Cmd: about the cursor).
    navigation: { defaultBarSpacing: 8, mousePan: 'horizontal' },
    zoomAnchor: 'right',
    priceAxisWidth: 72, // free crosshair (follows pointer)
    legendIconSize: 16,
    grid: { vertLines: el('vgrid').checked, horzLines: el('hgrid').checked },
    // A chart-type switch builds a new chart; the zone the user picked is
    // the demo's to carry across, like activeIndicators.
    timezone: app.chartTimezone,
    // The price pane can go below the studies from the right-click menu. Every
    // part of this host that means the price pane asks primaryPaneIndex() or
    // names no pane, which is what the option asks of a host before it is on.
    movablePrimaryPane: true,
    ...chartMotionOptions(),
    ...decorations,
  });
  app.chart.setDataContext(dataContext);
  app.offBranding = app.chart.on('branding:changed', renderToolbar);
  applyAxisChrome();
  applyStatusLineChoice();   // before the legends: a row added later obeys the switches
  applyTradeChoice();

  // Row 0 of the price pane: symbol + interval + the O/H/L/C/V readout.
  // Added BEFORE any indicator so their legends stack beneath it
  // (`legendRowsOn` counts what is already there).
  // `status` is the host half of the status line: the mark, the two alternate
  // titles, the session state and the change since the previous close. The
  // legend draws nothing for a field with no data, so these switches are live
  // only because this hands them something.
  app.symbolLegend = new PaneLegend({ id: 'symbol', title: '', params: '', row: 0, actions: [],
    status: () => symbolStatus({ symbol: app.req.symbol, bars: app.chart.primaryBars(), timezone: app.chart.timezone(), session: sessionOf(app.req) }),
  });
  app.chart.addPrimitive(app.symbolLegend);

  // Previous close, session high/low and the rest. Off the namespace, so a
  // dist/ built before the family shipped leaves this null and the price-axis
  // menu says so instead of throwing.
  app.priceLevels = null;
  if (PriceLevels) {
    app.priceLevels = new PriceLevels({ timezone: app.chartTimezone, levels: app.priceLevelState });
    app.chart.addPrimitive(app.priceLevels);
  }

  const sel = el('ctype').value;
  const isTransform = sel.startsWith('t:');
  // What the chart was last built as, so a switch from the select can be
  // recorded with the type it replaced.
  app.renderedType = { chartType: sel, transforms: app.transforms };

  // Family-B transforms: the chart applies one to the bars it is fed and
  // draws the elements, forming them again on every bar and tick. The series
  // still takes the raw bars, and trading uses real prices. Volume needs a
  // bar per element at the element's time, which Heikin Ashi keeps and the
  // price-bucket transforms do not.
  const { type, transform } = chartTypeSeries(sel, app.transforms);

  const style = {};
  if (type === 'baseline') {
    const avg = app.currentBars.reduce((s, b) => s + b.close, 0) / (app.currentBars.length || 1);
    style.baseValue = avg;
  }
  app.price = app.chart.addSeries(type, { style, ...(transform ? { transform } : {}) }); // first series -> drives the OHLC legend
  app.price.setData(app.currentBars);
  // The venue's hours for the empty space right of the last candle, so a
  // trend line or a box drawn there after Friday's close ends on Monday's
  // bars. Optional-called: an older dist/ has no calendar to take.
  app.chart.dataLayer.setSessionCalendar?.(sessionCalendarFor(app.req.symbol));
  // The pre-open and post-close hours in that calendar, washed behind their
  // bars: on an extended-hours chart a move made on thin pre-open volume then
  // reads as what it is. A regular-hours chart has no bars there to wash.
  engine.attachSessionShading?.(app.chart);

  // Tell the engine the instrument's tick. Left unset, `minMove` is 0, which
  // means "infer precision from the visible range": the axis then renders a
  // decimal short on many instruments, drawings snap to an invented grid,
  // and an indicator reading `ctx.tickSize` is told nobody knows.
  //
  // yfinance carries no tick size, so this demo picks one by market and says
  // so plainly. A real host reads it from its own instrument master, the way
  // OpenAlgo reads tick_size out of its symbol table, rather than guessing.
  //
  // A symbol the host holds metadata for gives the axis its price tick, which
  // with a tick schedule is the grid every band lies on: every price it can
  // trade at is on it, whichever band that price is in.
  app.ticks = tickScheduleFor(app.req.symbol);
  app.chart.setPriceScaleOptions({ minMove: axisMinMove(app.req.symbol, tickFor(app.req.symbol)) });
  // The chart rounds a dragged price alert by the same bands, since the axis
  // grid alone accepts prices a coarse band does not trade at.
  app.chart.setTickSchedule?.(app.ticks);
  attachVolume(1, !isTransform || sel === 't:heikin-ashi');
  if (!isTransform) {
    app.markersApi = app.price.createMarkers();
    app.markersApi.setMarkers(app.fills);
  } else {
    app.markersApi = null;
  }

  // Indicators come from the lazy 'openalgo-charts/indicators' tier. The chart
  // owns the whole lifecycle: it creates one series per plot, picks the pane,
  // draws declared reference levels (RSI 70/30), pins a declared fixed range
  // (RSI 0..100), and recomputes on every data change. On a transformed chart
  // a study reads the elements drawn, or the raw bars when set to (its
  // settings' "Compute on" row), and draws on the elements either way.
  for (const spec of rebuildState ? [] : app.activeIndicators) {
    try {
      // A study the host protects comes back protected: the policy rides with the spec, as its bars do.
      const instance = app.chart.addIndicator(spec.indicatorId, spec.settings, { paneIndex: spec.paneIndex,
        ...(spec.policy ? { policy: spec.policy } : {}), ...(spec.barSource ? { barSource: spec.barSource } : {}) });
      if (spec.visible === false) instance.setVisible(false);
    }
    catch (e) { console.warn('indicator', spec.indicatorId, e.message); }
  }
  renderIndicatorChips();
  attachDrawing();
  attachAlerts(app);
  if (rebuildState) {
    // The new series type is the user's selection; carry studies and anchors
    // through the engine's ordered restore without applying the old series style.
    const report = app.chart.restoreState({ ...rebuildState, series: [] });
    if (state && !report.applied) throw new Error('The primary chart state could not be restored');
    restorePrimaryStyle(app.chart, rebuildState);
    refreshVolume(1);
    renderIndicatorChips();
  }
  // After the restore: a rebuild carries this symbol's drawings from the chart
  // it replaces (a symbol change swapped them there, on the old chart, the
  // moment its context moved), and a layout brings its own. A chart built
  // fresh takes what the store holds for the symbol.
  app.instrumentDrawings = scopeDrawings(app.chart, app.draw, 1, rebuildState ? 'live' : 'stored');

  // Restore the price pane before attaching comparisons, which own a temporary scale mode.
  for (const c of app.comparisons) attachComparison(c, 1);

  // Chart trading: one drag handler routes both - drag a bracket leg -> move
  // that leg; drag a resting order line -> re-price that order. Both are redrawn
  // on the freshly-rebuilt chart.
  app.chart.subscribeDrag((externalId, p) => {
    if (!executionAllowed()) return;
    if (externalId.startsWith('bk-')) { setBracketPrice(externalId.slice(3), p); return; }
    if (externalId.startsWith('order:')) repriceOrder(externalId, p);
  });
  // Click the cancel box on a line: cancel that order, or close the position.
  app.chart.subscribeClick((id) => {
    if (id === 'position::close') { clearPosition(); saveState(); el('status').textContent = 'position closed'; return; }
    // The volume row's eye. Ahead of the `::close` fallthrough below, which
    // reads any other `::close` as an order line's cancel box.
    if (id === 'volume::hide') return;
    // Comparison legend actions are handled by their chart-owned event listener.
    if (id.startsWith('cmp:')) return;
    if (id.endsWith('::close')) cancelOrder(id.slice(0, -'::close'.length));
  });
  attachOrderLines();
  // The canvas's own controls say what they do under the pointer.
  app.offCanvasTips?.();
  app.offCanvasTips = attachCanvasTips(app.chart, el('chart'), 1);
  updatePositionLine(); // redraw the position line on the rebuilt chart
  if (app.bracket) {
    el('bracket').hidden = false;
    el('bk-entry').querySelector('[data-act="place"]').className = app.bracket.side === 'BUY' ? 'bk-buy' : 'bk-sell';
    attachBracketLines(); updateBracket();
  }
  // Fills come back from localStorage carrying the colour they were drawn in,
  // which may predate a Trading-tab edit or a whole release: put the restored
  // chrome on the palette the chart is actually using now.
  restyleTradeChrome();

  // The gear on a pane legend has no built-in dialog (the engine ships no
  // DOM), so it emits and we render the generated form.
  app.chart.on('indicatorSettings', ({ instanceId }) => openSettings(instanceId, capturePaneTarget(app, 1)));
  bindIndicatorSource(app.chart, 1);
  // The close and trash buttons on a legend removes the indicator inside the chart, so
  // mirror that into our own spec list and refresh the chips.
  app.chart.on('indicatorRemoved', () => {
    if (app.applyingTemplate) return;
    rememberIndicators();
    renderIndicatorChips();
  });
  // A study that stops drawing (a failed calculation, a timeframe the chart
  // refuses) says why; the listener goes with the chart.
  watchStudyStatus(app.chart);
  // Any change to the pane stack moves which pane is the bottom one.

  // Replay is headless: the controller emits, the transport bar and the
  // legend follow. `replay:stop` is here too, so the bar is correct for the
  // instant between stop() and exitReplay() tearing it down.
  attachReplay(app.chart, 1, setLegend);

  // Right-click. The chart classifies what is under the pointer and hands
  // over the price, so one menu covers order entry, drawings and settings,
  // and taking this event over replaces the engine's save-image fallback,
  // which is exactly the trade a host raising its own menu wants.
  app.chart.on('contextmenu', (e) => { e.preventDefault(); openContextMenu(e); });

  // OHLC legend tracks the crosshair. The position P&L does NOT - it marks to
  // the LTP (the latest close here; with a live feed, update it on each tick).
  app.chart.subscribeCrosshairMove((e) => {
    setLegend(e.bar ?? app.chart.primaryBars().at(-1));
  });
  setLegend(app.chart.primaryBars().at(-1));
  // Last, because the chart that just replaced the destroyed one has to be
  // the one in the group: the old entry is a corpse the group prunes on its
  // next broadcast, and a linked grid that stops following after a
  // chart-type switch is the failure this call exists to prevent.
  joinLink();
  attachTimeline(app, 1, app.currentBars);
  attachInspection(app);
  // Last: everything above built this chart, and none of it is a step. The
  // timeline itself carries over from the chart this one replaced.
  attachHistory(1);
  // The bar acts on the chart this call just built.
  app.bottombar?.refresh();
  window.__chart = () => app.chart;
  window.__draw = () => app.draw;
  window.__chart2 = () => app.chart2;
  window.__link = () => app.linkGroup;
  window.__drawingLink = () => app.drawingLinkGroup;
  window.__cache = () => app.cache;
}

let loadRevision = 0;

function installWorkspace({ layout, bars }) {
  const selection = primaryLayoutSelection(layout);
  if (!selection.request || !bars[0]?.length || (layout.secondary && !bars[1]?.length)) {
    throw new Error('Every workspace chart needs prepared history');
  }
  loadRevision++;
  app.linkGroup?.setOptions({ crosshair: false, viewport: false, symbol: false, interval: false });
  invalidateComparisons(1);
  removeBracket(); removeAllOrders(); clearPosition();
  app.req = { ...selection.request };
  for (const key of ['symbol', 'interval', 'period']) el(key).value = app.req[key];
  el('session').value = sessionOf(app.req);
  el('ctype').value = selection.chartType || 'candlestick';
  app.transforms = selection.transforms || {};
  app.chartTimezone = selection.timezone || DEFAULT_TZ;
  app.currentBars = bars[0].map(bar => ({ ...bar }));
  app.idxByTime.clear();
  app.currentBars.forEach((bar, index) => app.idxByTime.set(bar.time, index));
  app.activeIndicators = (layout.indicators || []).map(study => ({ ...study, settings: { ...study.settings } }));
  app.inspectionState1 = layout.inspection || { panel: null, width: 300 };
  app.inspectionState2 = layout.secondary?.inspection || { panel: null, width: 300 };
  applyVolumeSettings(1, layout.volumeSettings || { 'volume.visible': layout.volume !== false });
  restoreComparisons(layout, 1);
  restoreState(app.req.symbol);
  setMagnetMode(layout.magnet || 'off');
  setStayMode(layout.stay === true);
  // Set split geometry before creating the primary chart so its saved viewport
  // is applied against the final plot width, without a later resize correction.
  installSecondaryWorkspace(layout.secondary, bars[1]);
  render({ state: layout });
  // A workspace is a new document: no step taken on the one it replaced applies to it.
  historyFor(1)?.clear();
  historyFor(2)?.clear();
  focusChart(layout.focusPane);
  const focused = app.focusPane === 2 ? app.chart2 : app.chart;
  const request = app.focusPane === 2 ? app.p2 : app.req;
  app.linkGroup?.setSymbol(focused, request.symbol);
  app.linkGroup?.setInterval?.(focused, request.interval);
  app.linkGroup?.setOptions(layout.linkOptions || {});
  setChartState('ready', app.req);
  el('status').textContent = `Layout loaded: ${app.req.symbol}${app.chart2 ? ' / ' + app.p2.symbol : ''}`;
  renderToolbar();
}

async function load(opts) {
  const revision = ++loadRevision;
  exitReplay(1);
  invalidateComparisons(1);
  app.loading = true;
  app.loadFailed = false;
  app.alerts?.setPaused(true);
  const status = el('status');
  const hadChart = Boolean(app.chart);
  // Clamp here too, not just at the interval buttons: a saved layout or a
  // hand-set select can otherwise ask for a range the interval cannot serve.
  const interval = el('interval').value;
  const wanted = el('period').value;
  const period = clampPeriod(interval, wanted);
  if (period !== wanted) el('period').value = period;
  const prev = app.req || {};
  app.req = { symbol: el('symbol').value.trim(), interval, period,
    ...(el('session').value === 'extended' ? { session: 'extended' } : {}) };
  // A different instrument or timeframe means the bars on screen are about to
  // be replaced rather than refreshed, so the stage blanks under the loading
  // dots. A reload of the same request keeps them: they are still correct,
  // and blanking a chart to redraw the same chart is just a flicker.
  // Extended hours are another series, so a session change blanks the stage too.
  const identityChanged =
    prev.symbol !== app.req.symbol || prev.interval !== app.req.interval || sessionOf(prev) !== sessionOf(app.req);
  if (app.chart) {
    // Context subscribers must never read the previous source's bars as the new one.
    if (identityChanged) {
      app.price?.setData([]);
      app.volume?.setData([]);
    }
    publishContext(app.chart, referenceDataContext(app.req, app.chart.getDataContext()));
  }
  // Announced before the fetch, not after it: the follower starts loading
  // the same instrument in parallel instead of a second behind. Recorded
  // even with symbol sync off, so switching it on later converges on this
  // instrument rather than on a stale one.
  if (app.linkGroup && app.chart) app.linkGroup.setSymbol(app.chart, app.req.symbol);
  if (app.chart) app.linkGroup?.setInterval?.(app.chart, app.req.interval);
  if (app.chart) app.drawingLinkGroup?.setContext(app.chart, drawingLinkContext(app.req));
  status.textContent = `loading ${app.req.symbol} ${app.req.interval}...`;
  setChartState('loading', { ...app.req, blank: identityChanged || !app.chart });
  try {
    // The main slot: a newer main load cancels the one in flight, so a
    // quick symbol switch cannot land the older answer on the newer name.
    // A symbol box holding arithmetic (`AAPL/MSFT`) fetches every leg and folds
    // them into one series. Anything else takes the ordinary single-symbol path.
    const variant = requestVariant(app.req);
    const bars = isExpression(app.req.symbol)
      ? (await fetchExpressionBars(app.req.symbol, app.req.interval, app.req.period, { ...(opts || {}), variant })).bars
      : await fetchBars(app.req.symbol, app.req.interval, app.req.period, { ...(opts || {}), slot: 'main', variant });
    // Read the cache verdict now: `syncComparisons()` below fetches too, and
    // `lastFetch` describes whichever load ran most recently, so composing
    // the line at the end would report the comparison's verdict as this
    // symbol's.
    const note = fetchNote();
    if (revision !== loadRevision) return;
    app.currentBars = bars;
    app.idxByTime.clear();
    bars.forEach((b, i) => app.idxByTime.set(b.time, i));
    removeBracket(); removeAllOrders(); clearPosition(); // detach old chart's lines + reset vars
    restoreState(app.req.symbol);                            // repopulate this symbol's saved orders/bracket/position
    render({ keepView: !identityChanged });
    setChartState(bars.length ? 'ready' : 'empty', app.req);
    // Re-apply the saved layout now the series exists: a logical viewport
    // means nothing on an empty chart, and the drawing controller reads its
    // model back out of the restored state. Startup already selected the
    // saved named document or the validated session recovery snapshot.
    const saved = hadChart ? null : app.startupLayout;
    if (saved) {
      const report = applyLayout(saved, { keepView: saved.dataset === datasetKey(app.req), replaceComparisons: false });
      await report.secondaryReady;
    }
    app.startupLayout = null;
    // After the restore, so a comparison saved in the layout is fetched too.
    await syncComparisons(1);
    if (revision !== loadRevision) return;
    renderToolbar();
    status.textContent = `${app.req.symbol} · ${bars.length} bars · ${app.req.interval}/${app.req.period}`
      + (sessionOf(app.req) === 'extended' ? ' · ' + sessionLabel('extended').toLowerCase() : '')
      + (period !== wanted ? `  (${wanted} unavailable at ${interval})` : '')
      + note
      + (MISSING.length ? `  ·  dist/ predates: ${MISSING.join(', ')}` : '');
  } catch (e) {
    const fault = feedErrorState(e);
    // A superseded load has nothing to report: the newer one owns the readout.
    if (fault.state === 'aborted') return;
    if (revision !== loadRevision) return;
    app.loadFailed = true;
    if (fault.state === 'unsupported') {
      // Not a failure to retry: the source has no such series. The card says
      // so and offers the one choice that will load, and nothing is relabelled.
      status.textContent = fault.message;
      setChartState('unsupported', { ...app.req, message: fault.message, retry: () => { el('session').value = 'regular'; load(opts); } });
      return;
    }
    status.textContent = 'error: ' + fault.message;
    setChartState('error', { ...app.req, message: fault.message, retry: () => load(opts) });
    toast('error', `Could not load ${app.req.symbol}: ${fault.message}`);
  } finally {
    if (revision === loadRevision) {
      app.loading = false;
      syncReplayAlertPause();
      renderToolbar();
      if (!app.loadFailed) autosave();
    }
  }
}

// ── bottom bar ─────────────────────────────────────────────────────────
// The widget tier's strip under the stage: preset ranges and Go to on the
// left, the market status, the clock and the price scale toggles on the
// right, all acting on whichever chart has the focus. Its root is a layer
// over the whole stage, so its menus and tips open above the chart and
// outlive every chart render() throws away; only the strip takes the pointer.
//
// A range here is the page's own: the source serves history by named period,
// so a range picks the interval nearest its own among those this page offers
// that reach back to its first session, and the shortest period that does,
// loads them through the ordinary load path unless the pane holds them
// already, and then places the sessions on the bars that arrived.
/** The range each pane last took, with the chart it was placed on: a rebuilt chart has left it. */
const paneRanges = new Map();
let rangeRequest = 0;

async function applyRange(id) {
  const { DEFAULT_RANGES, DateNavigator, rangeInterval, rangeWindow } = widgetTier;
  const range = DEFAULT_RANGES.find(r => r.id === id);
  const target = capturePaneTarget(app);
  if (!range || !target?.current()) return { status: 'cancelled' };
  const mine = ++rangeRequest;
  const now = Date.now() / 1000;
  const calendar = sessionCalendarFor(target.request.symbol);
  const reach = now - rangeWindow(range, { end: now, zone: target.chart.timezone(), calendar }).from;
  const { interval, period } = rangeLoad(range, reach, rangeInterval);
  paneRanges.delete(target.pane);
  const request = { ...target.request, interval, period };
  // History already on screen only needs the view moved: loading it again
  // would rebuild the chart, and while a bar is forming it would come from
  // the wire, all of it, for a change of view. A load under way is about to
  // replace the chart the view would move on, so the range loads in its place.
  const onScreen = target.request.interval === interval && target.request.period === period
    && !(target.pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed)
    && !app.replay && !app.replayPicking && !app.replayLoading;
  if (!onScreen && target.pane === 2) {
    Object.assign(app.p2, request);
    await app.loadSecondary();
  } else if (!onScreen) {
    for (const key of ['symbol', 'interval', 'period']) el(key).value = request[key];
    await load();
  }
  renderToolbar();
  if (mine !== rangeRequest) return { status: 'cancelled' };
  const chart = target.pane === 2 ? app.chart2 : app.chart;
  // The split was closed while its history loaded, and the range went with it.
  if (!chart) return { status: 'cancelled' };
  if (target.pane === 2 ? app.loadFailed2 : app.loadFailed) return { status: 'error', error: new Error(`${request.symbol} history could not load`) };
  const bars = chart.primaryBars();
  if (bars.length === 0) return { status: 'no-data' };
  paneRanges.set(target.pane, { id, chart });
  const span = rangeWindow(range, { end: bars[bars.length - 1].time, zone: chart.timezone(), calendar: chart.dataLayer.sessionCalendar, bars });
  const result = await new DateNavigator({ chart }).goTo(span);
  if (result.status !== 'partial' || !result.clipped || chart.isDestroyed) return result;
  // A range ends at the latest bar, so one wider than the plot gives up its
  // oldest bars rather than its newest: the last price stays on screen.
  const lastBar = bars[bars.length - 1];
  const last = chart.dataLayer.timeToIndex(lastBar.time) ?? bars.length - 1;
  const view = chart.getVisibleLogicalRange();
  const from = last + 0.5 - (view.to - view.from);
  chart.setVisibleLogicalRange({ from, to: last + 0.5 });
  return { ...result, from: chart.dataLayer.indexToTime(Math.ceil(from + 0.5)) ?? result.from, to: lastBar.time };
}

function initBottombar() {
  const { mountBottombar, createOverlayStack, createTipController, applyTokens, widgetTokens, injectWidgetStyles, WIDGET_COMPONENT_CSS } = widgetTier;
  const stage = document.querySelector('main.stage');
  if (!mountBottombar || !stage) return;
  // The bar's rules ride the widget sheet. The alert layer injects it as well;
  // whichever comes first fills it and the other call leaves it alone.
  injectWidgetStyles(document, WIDGET_COMPONENT_CSS);
  const layer = document.createElement('div');
  layer.className = 'oac-widget oac-alert-host host-bottombar';
  const strip = document.createElement('div');
  layer.appendChild(strip);
  stage.appendChild(layer);
  stage.classList.add('has-bottombar');
  const theme = () => {
    layer.dataset.theme = currentTheme();
    applyTokens(layer, widgetTokens(chartTheme(), currentTheme()));
  };
  theme();
  document.addEventListener('oac:theme', theme);
  const overlays = createOverlayStack(layer, document);
  const tips = createTipController(layer, overlays.layer, document);
  const context = {
    document, tips,
    openOverlay: (node, options) => overlays.open(node, options),
    status: (text) => { el('status').textContent = text; },
  };
  app.bottombar = mountBottombar(context, strip, {
    target: () => {
      const target = capturePaneTarget(app);
      if (!target) return null;
      return {
        // Read when used: a range loads through the page, which builds the
        // pane a new chart, and what the range did is read off that one. A
        // split closed meanwhile leaves none, and applyRange cancels then.
        get chart() { return target.pane === 2 ? app.chart2 : app.chart; },
        interval: () => target.request.interval,
        range: () => { const held = paneRanges.get(target.pane); return held && held.chart === target.chart ? held.id : null; },
        setRange: applyRange,
      };
    },
    onGoTo: (anchor) => openGoTo(anchor),
    // A zone picked on the main chart survives the next rebuild, the way one picked in the settings does.
    onTimezone: () => { if (selectedPane(app) === 1) syncTimezoneFromChart(); autosave(); },
  });
  // The phone shell hides the bar and a wider window brings it back, and the
  // corner clock takes whichever side the bar leaves.
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => followBottombar()).observe(strip);
}

// Module wiring, in the order the original page registered its listeners.
initHover();
// Before the first render(): the shell sets the theme the chart is built in.
initShell(app);
initHistory(app);
initStatus(app);
initTimezone(app);
initAxisChrome(app);
initFeed(app);
initVolume(app);
initOrders(app);
initBracket(app);
initAccount(app);
initIndicators(app);
initIndicatorSource();
initRoutedStudy();
initAnchoredStudy();

// The operator keypad lives beside the symbol field. Mounted once: it writes
// into the field and the ordinary Enter handler does the loading, so nothing
// here needs to know how a chart is built.
mountOperatorKeypad(el('symbol'), el('symkeys'));
initChartSettings(app);
initBoxSettings(app);
initCompare(app);
initSnapshot(app);
initReplay(app);
initSplit(app);
initGoTo(app);
initBottombar();
initLink(app);
initClipboard(app);
initMenus(app);

// Wrapped, not passed: `load` now takes options, and handing it straight to
// addEventListener would pass a MouseEvent as the options bag.
el('load').addEventListener('click', () => load());
el('fit').addEventListener('click', () => { if (app.chart && app.chart.navigationOptions?.().zoomEnabled !== false) app.chart.resetScale(); });
el('symbol').addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
// Export the full chart (all layers composited) - native right-click "Save image"
// only grabs the canvas under the pointer (the transparent crosshair overlay).
el('save').addEventListener('click', () => {
  if (!app.chart) return;
  const a = document.createElement('a');
  a.download = `${nameOf(app.req.symbol || 'chart')}_${(app.req.interval || '').toLowerCase()}.png`;
  a.href = app.chart.takeScreenshot().toDataURL('image/png');
  a.click();
});
// switching chart type re-renders cached bars (no network round-trip)
el('ctype').addEventListener('change', () => {
  if (!app.currentBars.length) return;
  const from = app.renderedType;
  render({ keepView: !from || keepsView(from, { chartType: el('ctype').value, transforms: app.transforms }) });
  if (from) recordChartType(1, from, app.renderedType, showPrimaryType);
});

/** Build the main chart as `type`: what undoing or redoing a type switch does. */
function showPrimaryType(type) {
  const keepView = !app.renderedType || keepsView(app.renderedType, type);
  el('ctype').value = type.chartType;
  app.transforms = type.transforms;
  render({ keepView });
  renderToolbar();
  autosave();
}
app.showPrimaryType = showPrimaryType;

// An undo or redo can bring back a study, a zone or a scale the demo keeps
// its own copy of; read them back from the chart, the way a rebuild does.
app.afterHistory = (pane) => {
  afterChartSettingsWrite(capturePaneTarget(app, pane));
  if (pane === 1) rememberIndicators();
  renderIndicatorChips();
  renderToolbar();
  autosave();
};
// toggle grid lines live (no rebuild needed)
// These legacy fields belong to the primary chart; the shared toolbar captures its owner.
const applyGrid = () => {
  const o = { vertLines: el('vgrid').checked, horzLines: el('hgrid').checked };
  if (app.chart) app.chart.setGridOptions(o);
};
el('vgrid').addEventListener('change', applyGrid);
el('hgrid').addEventListener('change', applyGrid);
// Volume is hidden, not removed: the series keeps its data and its overlay
// price scale, so switching it back on is instant.
el('volshow').addEventListener('change', () => setVolumeShown(el('volshow').checked, 1));
initPersist(app);
initInspection(app);

// Escape is the overlay stack's (ui.js): one layer per press, each closed
// through its own close control, so chart settings still revert.
initToolbar(app);
app.onFocusPane = () => { renderToolbar(); renderIndicatorChips(); autosave(); app.bottombar?.refresh(); };
// The rail mounts the properties bar for the selected drawing on the stage,
// so a bar docked to it comes along into chart-only full screen.
initRail(app, { mountPropertiesBar });
initDrawing(app);
initMobile(app);
fillIntervalSelect();
initWorkspaceHost(app, installWorkspace);
app.startupLayout = await initWorkspaces(app);
initTemplates(app);
restorePrimarySelection(app.startupLayout);
if (app.startupLayout?.magnet) setMagnetMode(app.startupLayout.magnet);
if (typeof app.startupLayout?.stay === 'boolean') setStayMode(app.startupLayout.stay);

buildRail();
fillIndicatorPicker();
renderToolbar();
// Keep legacy field events available to embedded examples and test harnesses.
el('symbol').addEventListener('blur', () => { el('symbol').classList.remove('is-live'); renderToolbar(); });
el('symbol').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === 'Escape') { el('symbol').classList.remove('is-live'); renderToolbar(); }
});
load();
