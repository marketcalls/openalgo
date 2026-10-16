import * as engine from '/dist/openalgo-charts.mjs';
import { el, esc } from './ui.js';
import { renderInputRows, destroyInputRows } from './indicators.js';
import { descriptionOf, exchangeOf, marketStatusReading, previousSessionClose } from './status.js';
import { syncTimezoneFromChart } from './timezone.js';
import { exitReplay } from './replay.js';
import { syncAxisChromeFromChart, syncStatusLineFromChart, syncTradeChoiceFromChart } from './axis-chrome.js';
import { foldedInterval } from './intervals.js';
import { restyleTradeChrome } from './orders.js';
import { autosave } from './persist.js';
import { asStep, historyGroup, withoutHistory } from './history.js';
import { capturePaneTarget } from './pane-target.js';
import { VOLUME_TAB, volumeSettings, applyVolumeSettings } from './volume.js';
import { BOX_DEFAULTS } from './transforms.js';

// Read off the namespace rather than named above on purpose: a missing named
// import fails the whole module at link time, and a demo served against a
// dist/ built before the settings schema shipped should still draw a chart
// and simply report the feature as unavailable.
const { chartSettingsSchema, readChartSettings, applyChartSettings } = engine;

let app;

// ── generated chart settings ───────────────────────────────────────────
// Nothing below names a control. `chartSettingsSchema(chart)` returns the
// tabs and their inputs, `readChartSettings` the current values and
// `applyChartSettings` takes a patch back, so a control the engine adds
// appears here on its own.
let chartSetTab = null;
let chartSetBefore = null;          // values as they were when the dialog opened
const chartSetDirty = new Set();    // keys this session touched, for Cancel
let chartSetTarget = null;
let disposeSettings = null;

/** Host display options that must outlive a chart-type rebuild. */
export function chartDecorationsForRebuild(chart) {
  const options = {};
  if (chart && typeof chart.brandingOptions === 'function') {
    options.branding = chart.brandingOptions();
  }
  if (chart && typeof chart.watermarkOptions === 'function') {
    options.watermark = chart.watermarkOptions();
  }
  const size = chart?.legendIconSize?.();
  if (Number.isFinite(size)) options.legendIconSize = normalizeLegendIconSize(size);
  return options;
}

export const normalizeLegendIconSize = value => Number.isFinite(value) ? Math.max(12, Math.min(28, value)) : 16;

/** Series are host-owned, so the engine's state restore only returns their styles. */
export function restorePrimaryStyle(chart, state) {
  const primary = state?.series?.[0];
  if (primary && primary.type === chart.primarySeriesInfo?.()?.type && primary.style && typeof primary.style === 'object') {
    chart.primarySeries()?.applyOptions(primary.style);
  }
}

/**
 * A glyph per tab. Keyed by the schema's tab id rather than by position, so
 * reordering the tabs in the engine cannot silently shuffle the icons; a tab
 * this table does not know simply draws none.
 */
const CSET_ICON = {
  price: '<path d="M6 4v12"/><rect x="4" y="6.5" width="4" height="6.5"/><path d="M14 3v14"/><rect x="12" y="6" width="4" height="8"/>',
  readout: '<path d="M3 5h9M3 9h14M3 13h11"/>',
  axes: '<path d="M5 3v13h12"/><path d="M5 7h2M5 11h2M9 16v-2M13 16v-2"/>',
  appearance: '<rect x="3" y="4" width="14" height="12" rx="2"/><path d="M3 9h14M8 4v12"/>',
  trading: '<path d="M3 13l4-4 3 2 6-6"/><path d="M13 5h3v3"/><path d="M4 16h12"/>',
};
const cseticon = (id) => '<svg viewBox="0 0 20 20">' + (CSET_ICON[id] || '') + '</svg>';

const settingsTabs = chart => [...chartSettingsSchema(chart).map(tab => tab.id === 'readout'
  ? { ...tab, inputs: [...tab.inputs, { key: 'legend.iconSize', label: 'Legend button size', type: 'number',
    default: 16, min: 12, max: 28, step: 1 }] } : tab), VOLUME_TAB];
const settingsValues = target => ({ ...readChartSettings(target.chart), ...volumeSettings(target.pane),
  'legend.iconSize': normalizeLegendIconSize(target.chart.legendIconSize?.()) });
function writeSettings(target, patch) {
  if (patch['time.timezone'] !== undefined && patch['time.timezone'] !== target.chart.timezone()) exitReplay(target.pane);
  const chartPatch = Object.fromEntries(Object.entries(patch).filter(([key]) => !key.startsWith('volume.') && key !== 'legend.iconSize'));
  // The chart's settings are a step on its timeline; the chart does not
  // announce them, so each write is measured as one.
  if (Object.keys(chartPatch).length) asStep(target.pane, () => applyChartSettings(target.chart, chartPatch), 'Chart settings');
  if (patch['legend.iconSize'] !== undefined) target.chart.setLegendIconSize(normalizeLegendIconSize(patch['legend.iconSize']));
  // The volume row is the demo's own, saved with its layout, and an undo
  // of the chart would not put the demo's copy of it back.
  withoutHistory(target.pane, () => applyVolumeSettings(target.pane, patch));
  afterChartSettingsWrite(target);
}
let endSettingsStep = () => {};

export function openChartSettings(tabId, target = capturePaneTarget(app)) {
  if (!target?.current()) return;
  if (target.pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed) {
    el('status').textContent = 'load chart history before changing its settings';
    return;
  }
  if (!chartSettingsSchema) { el('status').textContent = 'chart settings are not in this build of dist/'; return; }
  if (chartSetTarget) closeChartSettings(true);
  chartSetTarget = target;
  const tabs = settingsTabs(target.chart);
  chartSetBefore = settingsValues(target);
  chartSetDirty.clear();
  chartSetTab = tabId || (tabs[0] && tabs[0].id);
  app.chartSettingsEditing = true;
  // The session is one step, and a Cancel that puts everything back leaves none.
  endSettingsStep = historyGroup(target.pane, 'Chart settings');
  disposeSettings = target.chart.on('destroy', discardChartSettings);
  renderChartSettings();
  el('chartset').hidden = false;
}

export function renderChartSettings() {
  const target = settingsOwner();
  if (!target) return;
  const tabs = settingsTabs(target.chart);
  // Re-read on every paint: edits apply live, so switching tabs and coming
  // back has to show what the chart is actually drawing now.
  const values = settingsValues(target);
  const nav = el('cset-tabs');
  nav.innerHTML = '';
  for (const t of tabs) {
    const b = document.createElement('button');
    b.className = 'cset-tab' + (t.id === chartSetTab ? ' is-on' : '');
    b.innerHTML = cseticon(t.id === 'volume' ? 'price' : t.id) + '<span>' + esc(t.label) + '</span>';
    b.addEventListener('click', () => { chartSetTab = t.id; renderChartSettings(); });
    nav.appendChild(b);
  }
  const tab = tabs.find((t) => t.id === chartSetTab) || tabs[0];
  if (!tab) return;
  renderInputRows(el('cset-body'), tab.inputs, values, (key, value) => {
    if (!settingsOwner()) return;
    chartSetDirty.add(key);
    writeSettings(target, { [key]: value });
  }, (key, option) => chartSettingUnavailable(key, option, target));
}

/**
 * Why a chart-settings control cannot act on the chart as it stands, or null
 * when it can. Every colour on the Trading tab paints one piece of trade
 * chrome, and a demo with no position on it has no long line to recolour: the
 * swatch is drawn disabled with its value visible, which says "nothing here
 * yet", where an enabled swatch that changes no pixels says "this is broken".
 * Place a bracket or fill a market order and the same swatches come alive.
 */
export function chartSettingUnavailable(key, option, target = chartSetTarget || capturePaneTarget(app)) {
  if (!target) return 'No chart is available';
  if (key.startsWith('volume.') && !app[target.pane === 2 ? 'volume2' : 'volume']) {
    return 'Volume is unavailable for this transformed chart';
  }
  const symbol = target.request.symbol || '';
  if (key === 'statusLine.openInterest' && target.chart.hasOpenInterest === false) {
    return 'Open interest is unavailable for this instrument';
  }
  if (key === 'statusLine.titleMode' && option === 'description') {
    return descriptionOf(symbol) ? null
      : 'No long name for ' + (symbol || 'this symbol').toUpperCase() + ' in this demo';
  }
  if (key === 'statusLine.marketStatus' && marketStatusReading(symbol) === undefined) {
    return 'No session hours for ' + exchangeOf(symbol);
  }
  if (key === 'statusLine.lastDayChange' && previousSessionClose(target.chart.primaryBars(), target.chart.timezone()) == null) {
    return 'No previous session in the loaded range';
  }
  if (target.pane === 2 && key.startsWith('trading.')) return 'Trading is available on Chart 1';
  const longPos = app.position && app.position.netQty > 0;
  const shortPos = app.position && app.position.netQty < 0;
  switch (key) {
    case 'trading.longColor': return longPos ? null : 'No long position on the chart';
    case 'trading.shortColor': return shortPos ? null : 'No short position on the chart';
    case 'trading.orderColor':
      return app.orders.length || app.bracket ? null : 'No resting order or bracket on the chart';
    case 'trading.tpColor': case 'trading.slColor':
      return app.bracket ? null : 'No bracket on the chart';
    case 'trading.buyColor':
      return app.fills.some((f) => f.shape === 'arrowUp') ? null : 'No buy execution on the chart';
    case 'trading.sellColor':
      return app.fills.some((f) => f.shape === 'arrowDown') ? null : 'No sell execution on the chart';
    default: return null;
  }
}

/**
 * What has to follow a settings write because it lives outside the schema.
 * The zone and the axis chrome are the engine's, but a chart-type switch
 * throws the chart away and rebuilds it, so the demo has to remember what
 * the controls chose. Reading them back beats mirroring the control, because
 * `setTimezone` refuses a zone the runtime does not know.
 */
export function afterChartSettingsWrite(target = chartSetTarget || capturePaneTarget(app)) {
  if (!target?.current()) return;
  // The Price tab edits the transform in place; the demo rebuilds with its
  // own copy of the options, the one its box settings dialogs keep, so that
  // copy follows the chart or the next rebuild would put the old size back.
  const series = target.chart.primarySeries?.();
  const spec = series ? target.chart.seriesTransform?.(series) : null;
  if (spec && Object.hasOwn(BOX_DEFAULTS, spec.type)) {
    const owner = target.pane === 2 ? app.p2 : app;
    owner.transforms = { ...owner.transforms, [spec.type]: { ...spec.options } };
  }
  if (target.pane === 2) {
    app.p2.timezone = target.chart.timezone();
    app.p2.legendIconSize = normalizeLegendIconSize(target.chart.legendIconSize?.());
    return;
  }
  syncTimezoneFromChart();
  syncAxisChromeFromChart();
  syncStatusLineFromChart();
  syncTradeChoiceFromChart();
  if (app.priceLevels) app.priceLevels.setOptions({ timezone: app.chartTimezone });
  // The demo draws its own orders, bracket and position, so a Trading-tab
  // edit reaches them only because this asks it to.
  restyleTradeChrome();
}

/**
 * Restore the visible tab to the defaults the schema declares. The defaults
 * come off the same input descriptors the rows were built from, including
 * both halves and the switch of a paired colour, so this cannot drift from
 * what is on screen.
 */
export function restoreChartSettingsTab() {
  const target = settingsOwner();
  if (!target) return;
  const tab = settingsTabs(target.chart).find((t) => t.id === chartSetTab);
  if (!tab) return;
  const patch = {};
  for (const input of tab.inputs) {
    if (input.type === 'colorPair') {
      patch[input.up.key] = input.up.default;
      patch[input.down.key] = input.down.default;
      if (input.enabled) patch[input.enabled.key] = input.enabled.default;
    } else {
      patch[input.key] = input.default;
    }
  }
  // Marked dirty so Cancel still undoes it: a restore is an edit like any
  // other, not a new baseline.
  for (const key of Object.keys(patch)) chartSetDirty.add(key);
  writeSettings(target, patch);
  renderChartSettings();
  el('status').textContent = tab.label.toLowerCase() + ' settings restored to defaults';
}

/**
 * Cancel puts back only the controls this session touched, rather than
 * replaying the whole snapshot: a wholesale write would also undo an axis
 * the user dragged or a scale they switched while the dialog was open.
 */
export function closeChartSettings(revert) {
  const target = settingsOwner();
  if (!target) return;
  const zoneBefore = chartSetBefore['time.timezone'];
  if (revert && chartSetBefore) {
    const back = {};
    for (const key of chartSetDirty) back[key] = chartSetBefore[key];
    writeSettings(target, back);
  }
  // The toolbar's grid switches drive a fresh chart's `grid` option, so they
  // have to follow whatever the Appearance tab left behind.
  if (target.pane === 1 && readChartSettings) {
    const now = readChartSettings(target.chart);
    el('vgrid').checked = now['canvas.grid.vertLines'] !== false;
    el('hgrid').checked = now['canvas.grid.horzLines'] !== false;
  }
  const refold = target.chart.timezone() !== zoneBefore && foldedInterval(target.request.interval);
  discardChartSettings();
  // Calendar bars need new boundaries after an accepted zone change. Wait for
  // the dialog decision so Cancel can restore its owner without racing history.
  if (refold) {
    if (target.pane === 2) app.loadSecondary();
    else app.load();
  }
  autosave();
}

function settingsOwner() {
  if (chartSetTarget?.current()) return chartSetTarget;
  discardChartSettings();
  return null;
}

function discardChartSettings() {
  destroyInputRows(el('cset-body'));
  disposeSettings?.();
  disposeSettings = null;
  const end = endSettingsStep;
  endSettingsStep = () => {};
  end();
  el('chartset').hidden = true;
  chartSetBefore = null;
  chartSetTarget = null;
  chartSetDirty.clear();
  app.chartSettingsEditing = false;
}

export function initChartSettings(a) {
  app = a;
  el('cset-defaults').addEventListener('click', restoreChartSettingsTab);
  el('cset-ok').addEventListener('click', () => closeChartSettings(false));
  el('cset-cancel').addEventListener('click', () => closeChartSettings(true));
  el('cset-x').addEventListener('click', () => closeChartSettings(true));
  el('chartset').addEventListener('click', (e) => { if (e.target.id === 'chartset') closeChartSettings(true); });
}
