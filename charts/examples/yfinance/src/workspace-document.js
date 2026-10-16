import { parseWorkspacePayload, WorkspaceDocumentError } from '/dist/openalgo-charts.workspace.mjs';
import { stripView } from '/dist/openalgo-charts.widget.mjs';
import { primaryLayoutSelection, datasetKey, LAYOUT_SCHEMA } from './persist.js';
import { clampPeriod, foldedInterval, PERIODS, PERIOD_DAYS } from './intervals.js';
import { EXTENDED, extendedSessionAvailable } from './session.js';
import { VOLUME_DEFAULTS, volumeValues } from './volume.js';
import { normalizeLegendIconSize } from './chart-settings.js';

const CHART_FIELDS = ['version', 'timezone', 'navigation', 'canvas', 'statusLine', 'watermark',
  'trading', 'events', 'axisChrome', 'viewport', 'barSpacing', 'grid', 'crosshairMode',
  'crosshairSnapToBar', 'priceOnlyAutoScale', 'indicatorLegendCollapsed', 'indicators', 'alerts', 'drawings', 'panes', 'primaryPane', 'series'];
const COMPARISON_MODES = ['percentage', 'indexed-to-100', 'none'];
const SCALE_MODES = ['linear', 'logarithmic', 'percentage', 'indexed-to-100'];
const HOST_SETTINGS = ['reference.pfmode', 'reference.compareMode', 'reference.compareBaseMode', 'reference.whenMissing', 'reference.legendIconSize',
  'reference.inspectionPanel', 'reference.inspectionWidth'];
const fail = message => { throw new WorkspaceDocumentError(message); };
// Pane settings are scalars, so each transform option is a key of its own:
// `reference.transform.renko.mode`. A workspace saved before the box settings
// dialogs has `reference.pfmode` instead, which the layout reads as before.
const TRANSFORM_KEY = 'reference.transform.';

/** The transform options a pane's settings hold, as a layout carries them. */
function transformFields(settings) {
  const entries = Object.entries(settings).filter(([key]) => key.startsWith(TRANSFORM_KEY)).map(([key, value]) => {
    const rest = key.slice(TRANSFORM_KEY.length), dot = rest.indexOf('.');
    return [rest.slice(0, dot), rest.slice(dot + 1), value];
  });
  if (!entries.length) return settings['reference.pfmode'] === undefined ? {} : { pfmode: settings['reference.pfmode'] };
  const kinds = [...new Set(entries.map(([kind]) => kind))];
  // fromEntries defines every key as the object's own, so a hostile key is
  // one more option for the check to refuse, never a prototype.
  return { transforms: Object.fromEntries(kinds.map(kind => [kind,
    Object.fromEntries(entries.filter(entry => entry[0] === kind).map(([, option, value]) => [option, value]))])) };
}

function chartFields(state) {
  return Object.fromEntries(CHART_FIELDS.filter(key => state[key] !== undefined).map(key => [key, state[key]]));
}

function paneFromLayout(saved, state, id, rail, whenMissing) {
  const selection = primaryLayoutSelection({ ...saved, timezone: state.timezone });
  if (!selection.request) fail('A named workspace needs an explicit chart source request');
  const settings = { ...volumeValues({ 'volume.visible': saved.volume !== false, ...saved.volumeSettings }),
    ...Object.fromEntries(Object.entries(selection.transforms).flatMap(([kind, options]) =>
      Object.entries(options).map(([option, value]) => [`${TRANSFORM_KEY}${kind}.${option}`, value]))),
    'reference.compareMode': saved.compareMode || 'percentage',
    'reference.whenMissing': whenMissing, 'reference.legendIconSize': normalizeLegendIconSize(saved.legendIconSize) };
  if (saved.compareBaseMode != null) settings['reference.compareBaseMode'] = saved.compareBaseMode;
  if (saved.inspection) {
    settings['reference.inspectionPanel'] = saved.inspection.panel || 'closed';
    settings['reference.inspectionWidth'] = saved.inspection.width;
  }
  const comparisons = (saved.comparisons || []).map((item, index) => ({
    id: `${id}:comparison:${index}`, symbol: item.symbol, exchange: '', visible: item.hidden !== true,
    ...(item.color === undefined ? {} : { color: item.color }),
  }));
  return { id, symbol: selection.request.symbol, interval: selection.request.interval,
    historyPeriod: selection.request.period, exchange: '',
    ...(selection.request.session === 'extended' ? { variant: { ...EXTENDED } } : {}),
    chartType: selection.chartType || 'candlestick', chart: chartFields(state), settings,
    volume: settings['volume.visible'], magnet: rail.magnet, stay: rail.stay, comparisons,
    comparisonMode: settings['reference.compareMode'] === 'none' ? 'price' : 'percent' };
}

/** Convert a trusted host snapshot, never the application's runtime or trading state. */
export function workspaceFromLayout(layout, { magnet = layout.magnet || 'off', stay = layout.stay === true } = {}) {
  const links = layout.linkOptions || {};
  const whenMissing = links.whenMissing || 'nearest';
  const panes = [paneFromLayout(layout, layout, 'primary', { magnet, stay }, whenMissing)];
  if (layout.secondary) panes.push(paneFromLayout(layout.secondary, layout.secondary.state, 'secondary', { magnet, stay }, whenMissing));
  const width = layout.secondary?.width ?? 50;
  const payload = { panes, activePaneId: panes.length === 2 && layout.focusPane === 2 ? 'secondary' : 'primary',
    layout: { rows: 1, columns: panes.length,
      slots: panes.map((pane, column) => ({ paneId: pane.id, row: 0, column, rowSpan: 1, columnSpan: 1 })),
      ...(panes.length === 2 ? { columnWeights: [100 - width, width] } : {}) },
    sync: { crosshair: links.crosshair !== false, viewport: links.viewport !== false,
      symbol: links.symbol === true, interval: links.interval === true,
      ...(links.appearance === undefined ? {} : { appearance: links.appearance === true }) } };
  // getState() can contain absent optional fields. Normalize that trusted state
  // before the portable boundary, which deliberately accepts only JSON values.
  return validateReferenceWorkspace(JSON.parse(JSON.stringify(payload)));
}

function orderedPanes(payload) {
  return [...payload.layout.slots].sort((a, b) => a.column - b.column)
    .map(slot => payload.panes.find(pane => pane.id === slot.paneId));
}

function secondaryWidth(payload) {
  const weights = payload.layout.columnWeights || [1, 1];
  return 100 * weights[1] / (weights[0] + weights[1]);
}

/** One chart, or two side by side: the geometry this page draws itself. */
const singleOrSplit = payload => {
  const grid = payload.layout;
  return grid.rows === 1 && grid.columns === payload.panes.length && grid.columns <= 2
    && grid.slots.every(slot => slot.row === 0 && slot.rowSpan === 1 && slot.columnSpan === 1);
};

/** A valid layout whose geometry only the grid view (grid.html) can show. */
export function needsGridView(input) {
  try { return !singleOrSplit(parseWorkspacePayload(input)); }
  catch { return false; }
}

// The grid view (grid.html) writes each chart's widget theme under this key.
const GRID_THEME = 'widget.theme';
// The periods the grid view's server knows and this page has no range for, as
// the range nearest in length, by ratio: twice and half as long are equally
// near, and the year to date counts as the year it can reach.
const NEAREST_PERIOD = new Map([['1d', '1mo'], ['5d', '1mo'], ['3mo', '6mo'], ['ytd', '1y'], ['2y', '1y'], ['10y', '5y']]);

/**
 * A layout the grid view exported, in this page's terms. This page sets one
 * theme for the whole page, so the per-chart widget theme is dropped; the
 * widget's weekly code becomes the source's; and a saved period becomes this
 * page's nearest range, clamped to what the chart's interval can serve the
 * way this page clamps its own. The grid view loads its own periods, so a
 * saved window, which counts bars, would land on other bars here: each chart
 * opens fitted to its data instead, with its studies and drawings. Any
 * document without the grid view's theme comes back unchanged, so this page's
 * own files keep every strict check.
 */
export function fromGridView(input) {
  const panes = Array.isArray(input?.panes) ? input.panes : [];
  if (!panes.some(pane => Object.prototype.hasOwnProperty.call(pane?.settings ?? {}, GRID_THEME))) return input;
  return { ...input, panes: panes.map(pane => {
    const settings = { ...pane?.settings }, interval = pane?.interval === '1w' ? '1wk' : pane?.interval;
    const period = PERIODS.includes(pane?.historyPeriod) ? pane.historyPeriod : NEAREST_PERIOD.get(pane?.historyPeriod);
    delete settings[GRID_THEME];
    return { ...pane, settings, interval, chart: pane?.chart && typeof pane.chart === 'object' ? stripView(pane.chart) : pane?.chart,
      ...(period === undefined ? {} : { historyPeriod: clampPeriod(interval, period) }) };
  }) };
}

/** Library validity does not imply the current host can honor every saved option. */
export function validateReferenceWorkspace(input) {
  const payload = parseWorkspacePayload(input);
  if (!singleOrSplit(payload)) {
    fail('This page shows one chart or two horizontal charts; open other workspace geometry in the grid view');
  }
  if (payload.panes.length === 2 && (secondaryWidth(payload) < 18 || secondaryWidth(payload) > 78)) {
    fail('The second chart width must be between 18 and 78 percent');
  }
  const [first] = orderedPanes(payload);
  for (const pane of payload.panes) {
    if (pane.exchange) fail('This reference feed uses ticker symbols, not separate exchange identifiers');
    const period = pane.historyPeriod ?? clampPeriod(pane.interval, '1y');
    // This source serves a session and nothing else: regular hours, which are
    // its default series, and extended hours where it has them. A saved
    // adjustment, currency or unit, or extended hours it does not have, would
    // reopen as some other series.
    if (pane.variant !== undefined) {
      if (Object.keys(pane.variant).some(key => key !== 'session')) fail('This reference feed serves only regular or extended trading hours');
      if (pane.variant.session === 'extended'
        && !extendedSessionAvailable(pane.symbol, foldedInterval(pane.interval)?.foldFrom || pane.interval)) {
        fail(`Extended hours are not available for ${pane.symbol} ${pane.interval}`);
      }
    }
    primaryLayoutSelection({ request: { symbol: pane.symbol, interval: pane.interval, period },
      chartType: pane.chartType, ...transformFields(pane.settings), timezone: pane.chart.timezone });
    // A period longer than the interval can serve would reopen with less
    // history than was saved, so it is refused. One shorter than the
    // interval's floor (a daily chart saved over a year, before daily charts
    // loaded five) reopens with more history and the same view, so it is
    // raised to the floor.
    const served = clampPeriod(pane.interval, period);
    if (served !== period && PERIOD_DAYS[period] > PERIOD_DAYS[served]) fail('The saved history period is unavailable at this interval');
    pane.historyPeriod = served;
    for (const key of Object.keys(pane.settings)) {
      if (!HOST_SETTINGS.includes(key) && !key.startsWith(TRANSFORM_KEY) && !Object.prototype.hasOwnProperty.call(VOLUME_DEFAULTS, key)) {
        fail(`Unsupported workspace setting: ${key}`);
      }
    }
    const normalizedVolume = volumeValues(pane.settings);
    const legendSize = pane.settings['reference.legendIconSize'];
    if (legendSize !== undefined && legendSize !== normalizeLegendIconSize(legendSize)) {
      fail('Invalid workspace setting: reference.legendIconSize');
    }
    const dockPanel = pane.settings['reference.inspectionPanel'];
    const dockWidth = pane.settings['reference.inspectionWidth'];
    if (dockPanel !== undefined && !['closed', 'data', 'objects'].includes(dockPanel)) fail('Invalid information panel');
    if (dockWidth !== undefined && (!Number.isInteger(dockWidth) || dockWidth < 240 || dockWidth > 480)) fail('Invalid information panel width');
    for (const key of Object.keys(VOLUME_DEFAULTS)) {
      if (pane.settings[key] !== undefined && pane.settings[key] !== normalizedVolume[key]) fail(`Invalid workspace setting: ${key}`);
    }
    if (pane.settings['volume.visible'] !== undefined && pane.volume !== pane.settings['volume.visible']) {
      fail('Workspace volume visibility conflicts with its settings');
    }
    const mode = pane.settings['reference.compareMode'];
    if (mode !== undefined && (!COMPARISON_MODES.includes(mode) || (mode === 'none') !== (pane.comparisonMode === 'price'))) {
      fail('Unsupported or conflicting comparison mode');
    }
    const base = pane.settings['reference.compareBaseMode'];
    if (base !== undefined && !SCALE_MODES.includes(base)) fail('Unsupported comparison base scale mode');
    const missing = pane.settings['reference.whenMissing'] ?? 'nearest';
    if (!['nearest', 'hide'].includes(missing) || missing !== (first.settings['reference.whenMissing'] ?? 'nearest')) {
      fail('Unsupported or conflicting missing-crosshair behavior');
    }
    if (pane.magnet !== first.magnet || pane.stay !== first.stay) fail('This host uses a shared drawing rail');
    const symbols = new Set();
    for (const comparison of pane.comparisons) {
      if (comparison.exchange) fail('This reference feed cannot resolve a separate comparison exchange');
      const symbol = comparison.symbol.trim().toUpperCase();
      if (symbols.has(symbol)) fail('Duplicate comparison symbol');
      symbols.add(symbol);
      if (comparison.color !== undefined && !/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(comparison.color)) {
        fail('Unsupported comparison color');
      }
    }
  }
  return payload;
}

function paneToLayout(pane) {
  const request = { symbol: pane.symbol, interval: pane.interval, period: pane.historyPeriod,
    ...(pane.variant?.session === 'extended' ? { session: 'extended' } : {}) };
  return { request, chartType: pane.chartType, ...transformFields(pane.settings),
    legendIconSize: normalizeLegendIconSize(pane.settings['reference.legendIconSize']),
    volume: pane.volume, volumeSettings: volumeValues({ 'volume.visible': pane.volume, ...pane.settings }),
    comparisons: pane.comparisons.map(item => ({ symbol: item.symbol, hidden: !item.visible,
      ...(item.color === undefined ? {} : { color: item.color }) })),
    compareMode: pane.settings['reference.compareMode'] || (pane.comparisonMode === 'price' ? 'none' : 'percentage'),
    ...(pane.settings['reference.compareBaseMode'] === undefined ? {} : { compareBaseMode: pane.settings['reference.compareBaseMode'] }),
    ...(pane.settings['reference.inspectionPanel'] === undefined ? {} : { inspection: {
      panel: pane.settings['reference.inspectionPanel'] === 'closed' ? null : pane.settings['reference.inspectionPanel'],
      width: pane.settings['reference.inspectionWidth'] ?? 300,
    } }) };
}

/** Validate the entire document before returning anything a live host can apply. */
export function layoutFromWorkspace(input) {
  const payload = validateReferenceWorkspace(input);
  const [first, second] = orderedPanes(payload);
  const primary = paneToLayout(first);
  return { schema: LAYOUT_SCHEMA, ...first.chart, ...primary, dataset: datasetKey(primary.request),
    magnet: first.magnet, stay: first.stay,
    linkOptions: { ...payload.sync, whenMissing: first.settings['reference.whenMissing'] || 'nearest' },
    focusPane: second && payload.activePaneId === second.id ? 2 : 1,
    ...(second ? { secondary: { ...paneToLayout(second), state: second.chart, width: secondaryWidth(payload) } } : {}) };
}
