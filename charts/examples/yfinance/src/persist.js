import * as engine from '/dist/openalgo-charts.mjs';
import * as drawTier from '/dist/openalgo-charts.draw.mjs';
import { el, toast, plural } from './ui.js';
import { volumeShown, setVolumeShown, volumeSettings, applyVolumeSettings } from './volume.js';
import { syncTimezoneFromChart } from './timezone.js';
import { comparisonSnapshot, restoreComparisons, syncComparisons } from './compare.js';
import { renderIndicatorChips } from './indicators.js';
import { CHART_TYPES, renderToolbar } from './toolbar.js';
import { savedTransforms } from './transforms.js';
import { INTERVALS, PERIODS } from './intervals.js';
import { SESSIONS, sessionOf } from './session.js';
import { withoutViewportSync } from './split.js';
import { normalizeLegendIconSize, restorePrimaryStyle } from './chart-settings.js';
import { keepHostStudy } from './host-study.js';
import { historyFor, withoutHistory } from './history.js';

// Both read off their namespaces: a dist/ built before either shipped must
// still read and write layouts, and a layout on such a build simply keeps
// its drawings as they were saved.
const { CHART_STATE_VERSION } = engine;
const { migrateDrawings } = drawTier;

let app;

// ── keys ───────────────────────────────────────────────────────────────
// Everything this page writes to storage sits under one prefix, so a host
// sharing the origin (the docs site, another example) cannot collide with
// it and a reader of the storage panel can tell at a glance what is ours.
export const STORE_PREFIX = 'oa-charts:';
export const LAYOUT_KEY = STORE_PREFIX + 'layout';
/** Where 1.x releases of this page kept the layout. Read once, then moved. */
export const LEGACY_LAYOUT_KEY = 'oa-charts-layout';
/** An entry that could not be read is renamed under here, never deleted. */
export const QUARANTINE_PREFIX = STORE_PREFIX + 'quarantine:';
/**
 * How many set-aside copies of one entry are kept. A rule that never deletes
 * anything eventually fills the quota, and a full quota is the worse failure
 * (see `writeLayout`): the newest few copies are what a bug report needs.
 */
export const QUARANTINE_KEEP = 5;

// Which symbol/interval/period the saved layout was captured on. A viewport
// is a range of bar indices and a manual price range is a range of prices,
// and neither means anything on a different dataset: restoring a day chart's
// view onto five-minute bars leaves the candles off-screen, which reads as
// the chart having loaded nothing at all.
// The session joins the key only when it is extended, so a key written
// before sessions existed still names the regular series it described.
export const datasetKey = (r) => `${r.symbol}|${r.interval}|${r.period}` + (sessionOf(r) === 'extended' ? '|extended' : '');

// ── schema and migrations ──────────────────────────────────────────────
/**
 * The layout document's own version, separate from the engine's
 * `CHART_STATE_VERSION` that rides inside it as `version`: the engine's
 * number says what shape `getState()` produced, this one says what shape the
 * demo wrapped it in. Bumped when the wrapper changes incompatibly.
 *
 *   1  the 1.x page: `getState()` spread flat, plus `dataset`, `comparisons`,
 *      `compareMode` and `volume`. No `schema` field, and `drawings` was
 *      whatever the draw tier of the day wrote (a bare array before 2.0).
 *   2  the same shape stamped `schema: 2`, with `drawings` always the 2.0
 *      drawing document and `version` always present.
 *   3  (2.6.3) the same shape, written by a page whose charts drag time alone.
 */
export const LAYOUT_SCHEMA = 3;

/** Thrown for a document that cannot be brought up to `LAYOUT_SCHEMA`. */
export class LayoutError extends Error {
  constructor(message) {
    super(message);
    this.name = 'LayoutError';
  }
}

const isRecord = (v) => typeof v === 'object' && v !== null && !Array.isArray(v);

function layoutRequest(value) {
  if (!isRecord(value) || typeof value.symbol !== 'string' || !value.symbol.trim()
    || !INTERVALS.includes(value.interval) || !PERIODS.includes(value.period)
    || (value.session !== undefined && !SESSIONS.includes(value.session))) return null;
  return { symbol: value.symbol.trim(), interval: value.interval, period: value.period,
    ...(value.session === 'extended' ? { session: 'extended' } : {}) };
}

/** The request as saved: the session only when it is not the default. */
export const savedRequest = r => ({ symbol: r.symbol, interval: r.interval, period: r.period,
  ...(sessionOf(r) === 'extended' ? { session: 'extended' } : {}) });

function validTimezone(value) {
  if (typeof value !== 'string' || !value) return false;
  if (engine.isValidTimezone) return engine.isValidTimezone(value);
  try { new Intl.DateTimeFormat('en', { timeZone: value }); return true; }
  catch { return false; }
}

/** Read only host selection fields, before any controls or history are changed. */
export function primaryLayoutSelection(doc) {
  if (!isRecord(doc)) throw new LayoutError('not a layout document');
  let request = null;
  if (Object.prototype.hasOwnProperty.call(doc, 'request')) {
    request = layoutRequest(doc.request);
    if (!request) throw new LayoutError('invalid primary chart request');
  } else if (typeof doc.dataset === 'string') {
    // A separator in an expression makes the old key ambiguous. Keep its chart
    // state usable, but do not guess which instrument the user intended.
    const fields = doc.dataset.split('|');
    if (fields.length === 3 || (fields.length === 4 && fields[3] === 'extended')) {
      request = layoutRequest({ symbol: fields[0], interval: fields[1], period: fields[2], session: fields[3] });
    }
  }
  const { chartType, timezone } = doc;
  if (chartType !== undefined && !CHART_TYPES.some(type => type.v === chartType)) {
    throw new LayoutError('unsupported primary chart type');
  }
  // A layout from before the box settings dialogs names a box mode instead.
  const transforms = savedTransforms(doc);
  if (transforms === null) throw new LayoutError('unsupported primary box settings');
  if (timezone !== undefined && !validTimezone(timezone)) throw new LayoutError('unsupported chart timezone');
  return { request, chartType, transforms, timezone };
}

/** Initialize startup selection. Switching a live chart needs a staged load. */
export function restorePrimarySelection(doc = readLayout()) {
  if (!doc || app.chart) return false;
  const { request, chartType, transforms, timezone } = primaryLayoutSelection(doc);
  if (request) {
    app.req = request;
    for (const key of ['symbol', 'interval', 'period']) el(key).value = request[key];
    el('session').value = sessionOf(request);
  }
  if (chartType !== undefined) el('ctype').value = chartType;
  app.transforms = transforms;
  if (timezone !== undefined) app.chartTimezone = timezone;
  return true;
}

/**
 * One step per schema version, keyed by the version it upgrades FROM. A
 * document at N runs `MIGRATIONS[N]`, then `MIGRATIONS[N + 1]`, until it is
 * at `LAYOUT_SCHEMA`. Each step returns a new object and leaves its input
 * alone, so a failed upgrade never half-rewrites what was read.
 */
export const MIGRATIONS = {
  // The drawings are the reason this step exists: 2.0 moved every text
  // field out of the style bag, made fib levels objects and gave each
  // drawing a z-order, and reading a 1.x save through the new types would
  // drop the text and the levels silently. The tier's own migration is the
  // one place that old shape is understood, so it is called rather than
  // restated. The chart state's version is stamped explicitly for the same
  // reason `restoreState` refuses a state without one: an implicit version
  // is a guess.
  1: (doc) => {
    const out = { ...doc, schema: 2 };
    if (typeof out.version !== 'number') out.version = 1;
    if (out.drawings !== undefined && migrateDrawings) out.drawings = migrateDrawings(out.drawings);
    return out;
  },
  // The engine writes every navigation option into a chart state, so each
  // layout saved before 2.6.3 carries the old `mousePan: 'both'` whether or
  // not anyone chose it, and restoring it would switch every drag back to
  // moving price and the pane back to manual scaling. A choice made after
  // this is saved at schema 3 and kept.
  2: (doc) => {
    const dropDefaultDrag = (state) => {
      if (!isRecord(state) || !isRecord(state.navigation) || state.navigation.mousePan !== 'both') return state;
      const { mousePan: _old, ...navigation } = state.navigation;
      return { ...state, navigation };
    };
    const out = { ...dropDefaultDrag(doc), schema: 3 };
    if (isRecord(out.secondary) && isRecord(out.secondary.state)) {
      out.secondary = { ...out.secondary, state: dropDefaultDrag(out.secondary.state) };
    }
    return out;
  },
};

/** The schema a stored document is at. Version 1 predates the field. */
export const schemaOf = (doc) => (typeof doc.schema === 'number' ? doc.schema : 1);

/**
 * Bring a parsed document up to the current schema, or throw `LayoutError`
 * with the reason a reader can act on. Two documents are refused rather
 * than guessed at: one written by a newer demo, and one carrying a chart
 * state newer than this engine (`restoreState` would refuse it anyway, but
 * later, after the drawings and comparisons had already been applied).
 */
export function upgradeLayout(input) {
  if (!isRecord(input)) throw new LayoutError('not a layout document');
  let doc = input;
  const from = doc.schema === undefined ? 1 : doc.schema;
  if (!Number.isInteger(from) || from < 1) throw new LayoutError(`schema ${String(doc.schema)} is not a version`);
  if (from > LAYOUT_SCHEMA) throw new LayoutError(`schema ${from} was written by a newer demo than this one (schema ${LAYOUT_SCHEMA})`);
  for (let v = from; v < LAYOUT_SCHEMA; v++) {
    const step = MIGRATIONS[v];
    if (!step) throw new LayoutError(`no migration from schema ${v}`);
    doc = step(doc);
  }
  if (typeof CHART_STATE_VERSION === 'number' && typeof doc.version === 'number' && doc.version > CHART_STATE_VERSION) {
    throw new LayoutError(`chart state version ${doc.version} is newer than this engine (${CHART_STATE_VERSION})`);
  }
  primaryLayoutSelection(doc);
  return doc;
}

// ── notices ────────────────────────────────────────────────────────────
// A fault the user has to act on (a layout set aside, storage that is
// full) goes to the shell's toast (ui.js), which outlives the status line:
// the readout is overwritten by the next load.

// ── storage ────────────────────────────────────────────────────────────
// Three states, in the order a session moves through them: storage works;
// storage refused a write and the layout lives in memory for the rest of
// the session; the user pressed Save, which tries storage again.
let memoryOnly = false;
let memoryLayout = null;
/** The text last persisted, so a save with nothing new in it writes nothing. */
let lastWritten = null;

const isQuotaError = (e) => Boolean(e) && (
  e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED' || e.code === 22 || e.code === 1014
);

/** Every key set aside for `name`, oldest first. */
export function quarantinedKeys(name = 'layout') {
  const prefix = QUARANTINE_PREFIX + name + ':';
  const out = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix)) out.push(k);
    }
  } catch (_) {
    // Storage that cannot be enumerated has nothing set aside in it.
  }
  return out.sort();
}

/**
 * Move an unreadable entry out of the way. Renamed, not deleted: the entry
 * is the user's own work, and the fault may be in this reader rather than
 * in the text. The status line is not enough here because it is overwritten
 * by the load that follows, and a layout that silently vanished is the
 * complaint this exists to rule out. Returns the key it now lives under.
 */
export function quarantine(key, raw, reason, name = 'layout') {
  const base = `${QUARANTINE_PREFIX}${name}:${Date.now()}`;
  let qkey = base;
  try {
    // Two faults in one millisecond must not overwrite each other.
    for (let n = 1; localStorage.getItem(qkey) !== null; n++) qkey = `${base}-${n}`;
    localStorage.setItem(qkey, raw);
    const keys = quarantinedKeys(name);
    for (const k of keys.slice(0, Math.max(0, keys.length - QUARANTINE_KEEP))) localStorage.removeItem(k);
  } catch (_) {
    // Quota. The copy could not be kept; the original still goes, or the
    // page reports the same fault on every load.
  }
  try { localStorage.removeItem(key); } catch (_) {}
  const why = reason instanceof Error ? reason.message : String(reason);
  toast('error', `The saved layout could not be read (${why}). It was set aside as "${qkey}" rather than deleted.`);
  return qkey;
}

/**
 * The stored layout, upgraded, or null when there is none. A document that
 * cannot be parsed or upgraded is quarantined and reported, and null comes
 * back, so a caller never has to guard against a throw on the load path.
 */
export function readLayout() {
  if (memoryLayout) return memoryLayout;
  let raw = null;
  try { raw = localStorage.getItem(LAYOUT_KEY); } catch (_) { return null; }
  if (raw === null) return null;
  try {
    return upgradeLayout(JSON.parse(raw));
  } catch (e) {
    quarantine(LAYOUT_KEY, raw, e);
    return null;
  }
}

/**
 * Persist a document. Returns 'unchanged' when the text is what was last
 * written, 'stored' on a write, and 'memory' when storage has refused and
 * the document is kept for the session only. A refusal degrades rather than
 * throws: every autosave would otherwise fail the same way, and the user
 * is told once, on the transition, not on every drag.
 */
export function writeLayout(doc, { retryStorage = false } = {}) {
  const text = JSON.stringify(doc);
  // An explicit Save while degraded is a request to try storage again, even
  // when nothing has changed since the memory copy was taken.
  if (text === lastWritten && !(memoryOnly && retryStorage)) return 'unchanged';
  if (!memoryOnly || retryStorage) {
    try {
      localStorage.setItem(LAYOUT_KEY, text);
      lastWritten = text;
      if (memoryOnly) toast('success', 'Browser storage is back: the layout is saved again.');
      memoryOnly = false;
      memoryLayout = null;
      return 'stored';
    } catch (e) {
      if (!memoryOnly) {
        toast('error', isQuotaError(e)
          ? 'Browser storage is full. The layout is kept in memory for this session only; clear some site data and press Save.'
          : `Browser storage is unavailable (${e && e.message ? e.message : e}). The layout is kept in memory for this session only.`);
      }
      memoryOnly = true;
    }
  }
  memoryLayout = doc;
  lastWritten = text;
  return 'memory';
}

/** Whether storage has refused a write this session. */
export const storageDegraded = () => memoryOnly;

/**
 * Move a 1.x layout to its namespaced key. The old key is read once and
 * removed; an old text that cannot be upgraded is quarantined like any
 * other. A current key wins over a legacy one, because it is the newer of
 * the two (a downgrade followed by an upgrade is the only way to hold both).
 */
export function migrateStorage() {
  let legacy = null;
  try { legacy = localStorage.getItem(LEGACY_LAYOUT_KEY); } catch (_) { return false; }
  if (legacy === null) return false;
  try {
    if (localStorage.getItem(LAYOUT_KEY) === null) {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(upgradeLayout(JSON.parse(legacy))));
    }
    localStorage.removeItem(LEGACY_LAYOUT_KEY);
    return true;
  } catch (e) {
    if (isQuotaError(e)) return false;   // leave it; the next boot tries again
    quarantine(LEGACY_LAYOUT_KEY, legacy, e);
    return false;
  }
}

// ── the document ───────────────────────────────────────────────────────
// getState() captures the viewport, grid, panes, price scales and indicator
// instances. It deliberately does NOT capture series data; that is the
// app's (it knows the symbol and feed), so restore reports the series
// descriptors back and we rebuild them from the cached bars.
/**
 * What we persist: the engine's own state plus the things it does not own.
 * Comparison series are demo-owned (the engine holds the alignment, we hold
 * the symbol and the feed), so they ride alongside `dataset`.
 */
export function layoutSnapshot() {
  const measuredWidth = app.chart2
    ? 100 * el('pane2').getBoundingClientRect().width / el('split').getBoundingClientRect().width : 0;
  return {
    schema: LAYOUT_SCHEMA,
    ...app.chart.getState(),
    dataset: datasetKey(app.req),
    request: savedRequest(app.req),
    chartType: el('ctype').value || 'candlestick',
    transforms: app.transforms || {},
    legendIconSize: normalizeLegendIconSize(app.chart.legendIconSize?.()),
    ...comparisonSnapshot(1),
    // Demo-owned like the comparisons: `render()` builds the histogram from
    // this flag, so without it a hidden volume comes back on a reload.
    volume: volumeShown(1),
    volumeSettings: volumeSettings(1),
    inspection: app.inspection1?.dock.state() || app.inspectionState1,
    focusPane: app.focusPane === 2 && app.chart2 ? 2 : 1,
    linkOptions: app.linkGroup?.options(),
    secondary: app.chart2 ? {
      request: savedRequest(app.p2),
      chartType: app.p2.chartType || 'candlestick',
      transforms: app.p2.transforms || {},
      legendIconSize: normalizeLegendIconSize(app.chart2.legendIconSize?.()),
      volumeSettings: volumeSettings(2),
      inspection: app.inspection2?.dock.state() || app.inspectionState2,
      ...comparisonSnapshot(2),
      state: app.chart2.getState(),
      width: parseFloat(el('pane2').style.flexBasis) || (Number.isFinite(measuredWidth) && measuredWidth > 0 ? measuredWidth : 50),
    } : undefined,
  };
}

/**
 * The document without what describes the old view. Keeps what describes
 * the workspace (indicators, drawings, pane sizes, styles) and drops the
 * viewport and every pinned price range, for a layout that is about to
 * land on a different dataset. Returns a copy.
 */
export function stripView(doc) {
  const out = { ...doc };
  delete out.viewport;
  delete out.barSpacing;
  if (Array.isArray(out.panes)) {
    out.panes = out.panes.map((pane) => {
      if (!pane || !pane.priceScale) return pane;
      const priceScale = { ...pane.priceScale, autoScale: true };
      delete priceScale.range;
      return { ...pane, priceScale };
    });
  }
  return out;
}

/** The symbol a layout was captured on, or null when it cannot say. */
function layoutSymbol(doc) {
  try { return primaryLayoutSelection(doc).request?.symbol ?? null; }
  catch (_) { return null; }
}

/**
 * Put a document onto the live chart. `keepView` restores the viewport and
 * the pinned ranges too, which is right only on the dataset they were
 * captured on. `replaceComparisons` swaps the live comparison set for the
 * saved one and fetches it; off, the saved set is adopted only when nothing
 * is on the chart yet and the caller fetches (the way `load()` does, after
 * it has finished its own work). Returns the engine's restore report.
 */
export function applyLayout(doc, options = {}) {
  // A layout is a new document, not a step: nothing it sets is recorded, and
  // the timeline it replaces no longer leads anywhere.
  const report = withoutHistory(1, () => applyLayoutNow(doc, options));
  if (report.applied) historyFor(1)?.clear();
  return report;
}

function applyLayoutNow(doc, { keepView = true, replaceComparisons = true } = {}) {
  if (!app.chart) return { applied: false, series: [], indicators: 0, reason: 'no chart' };
  const primary = app.chart;
  const primaryRequest = datasetKey(app.req);
  let state = keepView ? doc : stripView(doc);
  // Drawings belong to the symbol they were drawn on. A layout captured on
  // another symbol keeps its drawings for that symbol, shown when it loads,
  // and this chart keeps the ones it has.
  const own = layoutSymbol(doc);
  if (own !== null && own !== app.req.symbol && app.instrumentDrawings && state.drawings !== undefined) {
    app.instrumentDrawings.setDocument({ symbol: own }, state.drawings);
    state = { ...state, drawings: app.draw.toJSON() };
  }
  // Mirror the restored indicators into our own spec list so a later chart
  // rebuild (type switch / reload) keeps them.
  app.activeIndicators = (state.indicators || []).map(study => ({ ...study, settings: { ...study.settings } }));
  const report = app.chart.restoreState(state);
  if (!report.applied) {
    toast('error', 'The layout could not be restored: ' + report.reason);
    return report;
  }
  app.inspectionState1 = state.inspection || { panel: null, width: 300 };
  app.inspection1?.dock.restore(app.inspectionState1);
  syncTimezoneFromChart();   // the saved zone is the engine's to apply, ours to remember
  restorePrimaryStyle(app.chart, state);
  app.chart.setLegendIconSize?.(normalizeLegendIconSize(state.legendIconSize));
  // The engine restores drawings before alerts. A second drawing restore
  // would remove the anchors underneath the alerts that just returned.
  restoreComparisons(state, 1, replaceComparisons);
  if (state.volume !== undefined) setVolumeShown(state.volume !== false, 1);
  if (state.volumeSettings) applyVolumeSettings(1, state.volumeSettings);
  if (replaceComparisons) syncComparisons();
  renderIndicatorChips();
  renderToolbar();
  if (app.restoreSecondary) {
    const links = state.linkOptions || app.linkGroup?.options() || {};
    const options = {};
    for (const key of ['crosshair', 'viewport', 'symbol', 'interval']) {
      if (typeof links[key] === 'boolean') options[key] = links[key];
    }
    if (links.whenMissing === 'nearest' || links.whenMissing === 'hide') options.whenMissing = links.whenMissing;
    app.linkGroup?.setOptions({ symbol: false, interval: false });
    report.secondaryReady = Promise.resolve(app.restoreSecondary(state.secondary, state.focusPane)).then(restored => {
      if (!restored || app.chart !== primary || datasetKey(app.req) !== primaryRequest) return false;
      // Opening the split resizes the primary chart after its state was applied.
      // Restore its logical window once both chart boxes have settled.
      if (state.viewport) {
        withoutViewportSync(() => primary.setVisibleLogicalRange(state.viewport));
      }
      if (!app.linkGroup) return restored;
      const secondary = state.focusPane === 2 && app.chart2;
      const chart = secondary || app.chart;
      const request = secondary ? app.p2 : app.req;
      app.linkGroup.setSymbol(chart, request.symbol);
      app.linkGroup.setInterval?.(chart, request.interval);
      app.linkGroup.setOptions(options);
      renderToolbar();
      return restored;
    });
  }
  return report;
}

// ── saving ─────────────────────────────────────────────────────────────
// Persist the whole chart state (viewport, panes, indicators, drawings) on
// every change, so a refresh comes back exactly where it left off. Debounced
// because drags fire per frame.
export const SAVE_DEBOUNCE_MS = 250;
let saveTimer = 0;

/** Write the current layout now. Returns what `writeLayout` did. */
export function persistLayoutNow(opts) {
  if (!app.chart || app.workspaceLoading || app.applyingTemplate) return 'unchanged';
  const result = writeLayout(layoutSnapshot(), opts);
  app.onLayoutPersisted?.();
  return result;
}

export function autosave() {
  // Not while replaying: the chart is showing a prefix of the session and a
  // viewport captured over it would restore the user into a truncated chart.
  if (!app.chart || app.workspaceLoading || app.applyingTemplate || app.replay || app.replayPicking || app.replayLoading || app.loading || app.loadFailed || app.loading2 || app.loadFailed2 || app.restoringSecondary || app.chartSettingsEditing) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushAutosave, SAVE_DEBOUNCE_MS);
}

/** Run a pending autosave now, for the moment the page is going away. */
export function flushAutosave() {
  if (!saveTimer) return;
  clearTimeout(saveTimer);
  saveTimer = 0;
  if (app.chart && !app.workspaceLoading && !app.applyingTemplate && !app.replay && !app.replayPicking && !app.replayLoading && !app.loading && !app.loadFailed && !app.loading2 && !app.loadFailed2 && !app.restoringSecondary && !app.chartSettingsEditing) persistLayoutNow();
}

// ── files ──────────────────────────────────────────────────────────────
/**
 * The layout as a file body. The document is wrapped, not bare, so a file
 * found later says what wrote it, and `parseLayoutFile` accepts both.
 */
export function exportLayout() {
  const doc = layoutSnapshot();
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  const name = datasetKey(app.req).replace(/[^A-Za-z0-9.^-]+/g, '_');
  return {
    filename: `openalgo-charts-layout-${name}-${stamp}.json`,
    text: JSON.stringify({ app: 'openalgo-charts yfinance demo', exportedAt: new Date().toISOString(), layout: doc }, null, 2),
  };
}

const withoutPolicy = (d) => {
  if (!isRecord(d) || !('policy' in d)) return d;
  const out = { ...d };
  delete out.policy;
  return out;
};

/**
 * A chart state with every drawing's `policy` taken off, and nothing else
 * changed. A policy is a host's restriction on drawings it placed itself, and
 * a file from elsewhere is not this host: honouring one would let a shared
 * layout plant a drawing that no control here can move or delete, and that
 * every autosave then writes back.
 */
export function untrustedDrawings(state) {
  if (!isRecord(state) || state.drawings === undefined) return state;
  const { drawings } = state;
  return { ...state, drawings: Array.isArray(drawings) ? drawings.map(withoutPolicy)
    : isRecord(drawings) && Array.isArray(drawings.drawings) ? { ...drawings, drawings: drawings.drawings.map(withoutPolicy) } : drawings };
}

/**
 * A chart state without the studies that carry a policy. A policy is a
 * host's restriction on a study it placed itself, so such a study is that
 * host's, not the file's: brought in unrestricted it would be a copy of
 * someone else's study, and restricted it would be one no control here
 * removes. This host keeps its own study through an import instead
 * (`keepHostStudy`).
 */
export function untrustedStudies(state) {
  if (!isRecord(state) || !Array.isArray(state.indicators)) return state;
  return { ...state, indicators: state.indicators.filter((study) => !isRecord(study) || !('policy' in study)) };
}

/** Parse and upgrade a file body. Throws `LayoutError` (or a JSON error) for anything that is not a layout. */
export function parseLayoutFile(text) {
  let parsed;
  try { parsed = JSON.parse(text); } catch (e) { throw new LayoutError('not JSON: ' + e.message); }
  const doc = untrustedStudies(untrustedDrawings(upgradeLayout(isRecord(parsed) && isRecord(parsed.layout) ? parsed.layout : parsed)));
  return isRecord(doc.secondary?.state)
    ? { ...doc, secondary: { ...doc.secondary, state: untrustedStudies(untrustedDrawings(doc.secondary.state)) } } : doc;
}

/**
 * Hand the layout to the browser as a download. The engine ships no DOM and
 * no downloads; this is the host's, and it is one anchor click.
 */
export function downloadLayout() {
  if (!app.chart) return null;
  const { filename, text } = exportLayout();
  const blob = new Blob([text], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

/**
 * Apply a layout file (a `File`, a `Blob`, or the text itself), then save
 * it so a reload keeps it. The view is kept only when the file was captured
 * on the dataset that is loaded. Reports through the toast and returns
 * whether it applied.
 */
export async function importLayoutFile(file) {
  const text = typeof file === 'string' ? file : await file.text();
  let doc;
  try {
    doc = parseLayoutFile(text);
  } catch (e) {
    toast('error', 'That file is not a layout: ' + e.message);
    return false;
  }
  const report = applyLayout(keepHostStudy(app.chart, doc), { keepView: doc.dataset === datasetKey(app.req), replaceComparisons: true });
  if (!report.applied) return false;
  if (report.secondaryReady && !await report.secondaryReady) return false;
  persistLayoutNow();
  toast('success', `Layout imported: ${plural(report.indicators, 'indicator')}, ${plural((doc.drawings && doc.drawings.drawings || []).length, 'drawing')}.`);
  return true;
}

// ── wiring ─────────────────────────────────────────────────────────────
export function initPersist(a) {
  app = a;
  migrateStorage();
  // Read once now, not only when a button asks: an entry that cannot be
  // read is set aside before the first load reaches for it, and start-up
  // is the one moment the notice lands where the user will act on it.
  readLayout();
  // What is stored now is the baseline for "has anything changed": without
  // this the first autosave after a reload rewrites an identical document.
  try { lastWritten = localStorage.getItem(LAYOUT_KEY); } catch (_) {}
  el('lsave').addEventListener('click', () => {
    if (!app.chart) return;
    if (app.workspaceCatalog?.currentId && app.saveNamedLayout) { app.saveNamedLayout(); return; }
    const did = persistLayoutNow({ retryStorage: true });
    el('status').textContent = did === 'memory'
      ? 'layout kept in memory only (storage refused the write)'
      : `layout saved · ${plural(app.chart.indicators().length, 'indicator')}`;
    // The readout is overwritten by the next thing that happens; a save is
    // worth a notice that stays long enough to be read.
    if (did !== 'memory') toast('success', 'Layout saved');
  });
  el('lload').addEventListener('click', () => {
    const doc = app.chart ? readLayout() : null;
    if (!doc) { el('status').textContent = 'no saved layout'; toast('error', 'No saved layout'); return; }
    const report = applyLayout(keepHostStudy(app.chart, doc), { keepView: true, replaceComparisons: true });
    // applyLayout has already raised the toast for a refused document.
    if (!report.applied) { el('status').textContent = 'restore failed: ' + report.reason; return; }
    el('status').textContent = `layout restored · ${plural(report.indicators, 'indicator')} · ${plural(report.series.length, 'series descriptor')}`;
  });
  // The file buttons are optional markup: a page without them still saves.
  const exp = el('lexport');
  if (exp) exp.addEventListener('click', () => { const f = downloadLayout(); if (f) el('status').textContent = 'layout exported as ' + f; });
  const imp = el('limport');
  const picker = el('limport-file');
  if (imp && picker) {
    imp.addEventListener('click', () => { picker.value = ''; picker.click(); });
    picker.addEventListener('change', () => {
      const f = picker.files && picker.files[0];
      if (f) importLayoutFile(f);
    });
  }
  // A debounced save still pending when the tab closes is the last quarter
  // second of the user's work; `pagehide` is the last moment a synchronous
  // write is allowed.
  if (typeof window !== 'undefined') window.addEventListener('pagehide', flushAutosave);
}
