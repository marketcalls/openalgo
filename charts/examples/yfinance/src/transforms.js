// Importing the transform tier registers the point and figure and Kagi
// renderers and the six transforms a chart can apply itself.
import '/dist/openalgo-charts.transform.mjs';
// Off the namespace, as main.js reads the newer surfaces: a dist/ from before
// in-chart transforms still draws a chart, and main.js says what it lacks.
import * as engine from '/dist/openalgo-charts.mjs';

/** Whether this dist/ can apply a transform in the chart. */
export const inChartTransforms = typeof engine.getSeriesTransform === 'function';

// ── Family-B transforms ────────────────────────────────────────────────
// A transform re-buckets bars by price movement rather than the clock, so one
// source bar can form no element, one, or several. The chart applies it: the
// series is fed the raw bars as ever, and the chart draws the bricks, boxes or
// line, forming them again as each bar and tick lands (replay shows it live).
// A size left out is taken from the loaded history, a fortieth of its range
// (twice that for range bars and Kagi), so one default suits AAPL and BTC.
//
// Point and figure and Renko carry options of their own, edited in their
// settings dialogs (box-settings.js) and kept per transform, so a Renko set
// up once is still set up after a detour through candles.

/** The option each sizing method reads its one number from. */
export const SIZE_KEY = { fixed: 'boxSize', percent: 'percent', atr: 'atrMultiplier', atrPercent: 'percent' };
const ATR_MODES = ['atr', 'atrPercent'];

/**
 * The engine options for a box transform, from the fields its dialog edits.
 * Only the size the method reads is written, so a saved layout says what was
 * chosen and nothing stale beside it.
 */
export function boxOptions(kind, { mode, size, atrPeriod = 14, reversal = 3, method }) {
  return { mode, [SIZE_KEY[mode]]: size, ...(ATR_MODES.includes(mode) ? { atrPeriod } : {}),
    ...(kind === 'point-figure' ? { reversal } : {}), method };
}

/**
 * The dialog fields back from engine options. A key left out means what the
 * engine takes it to mean, which is how an option the chart settings dialog
 * put back to its default reads here too.
 */
export function boxFields(kind, options = {}) {
  const mode = Object.hasOwn(SIZE_KEY, options.mode) ? options.mode : 'fixed';
  return { mode, size: options[SIZE_KEY[mode]] ?? (mode === 'fixed' ? 0 : 1), atrPeriod: options.atrPeriod ?? 14,
    reversal: options.reversal ?? 3, method: options.method ?? (kind === 'point-figure' ? 'hl' : 'close') };
}

/**
 * What a chart starts with before its dialog is used. Point and figure keeps
 * the ATR box this page has always opened it with; Renko keeps a fixed brick
 * sized from the history.
 */
export const BOX_DEFAULTS = {
  'point-figure': boxOptions('point-figure', { mode: 'atr', size: 1, reversal: 3, method: 'hl' }),
  renko: boxOptions('renko', { mode: 'fixed', size: 0, method: 'close' }),
};

/** The transform a chart type select value names. 't:range' predates the transform's own id. */
const kindOf = (sel) => (sel === 't:range' ? 'range-bars' : sel.slice(2));

/** The options a chart type is drawn with: its own if it was set up, else its defaults; null for a type with none. */
export function typeOptions(type) {
  const kind = type?.chartType?.startsWith('t:') ? kindOf(type.chartType) : null;
  if (!kind || !Object.hasOwn(BOX_DEFAULTS, kind)) return null;
  return type.transforms?.[kind] ?? BOX_DEFAULTS[kind];
}

// `sel` is the chart type select's value: a renderer, or `t:<transform>`, and
// `transforms` the options kept per transform.
export function chartTypeSeries(sel, transforms = {}) {
  if (!sel.startsWith('t:') || !inChartTransforms) return { type: sel.startsWith('t:') ? 'candlestick' : sel, transform: null };
  const kind = kindOf(sel);
  const options = typeOptions({ chartType: sel, transforms });
  return { type: engine.getSeriesTransform(kind).renderer, transform: options ? { type: kind, options: { ...options } } : { type: kind } };
}

const sameOptions = (a, b) => a === b || (a !== null && b !== null && Object.keys(a).length === Object.keys(b).length
  && Object.keys(a).every(key => a[key] === b[key]));

/** Whether two chart types (`{ chartType, transforms }`) draw the same thing. */
export const sameType = (a, b) => a.chartType === b.chartType && sameOptions(typeOptions(a), typeOptions(b));

/**
 * Whether a switch between two chart types keeps the view. A transform other
 * than Heikin Ashi draws elements of its own, so a view kept from bars, or
 * from other elements (a new box size forms other columns), would point at
 * nothing: a switch into or out of one starts from a fitted view.
 */
export function keepsView(shown, next) {
  const own = (type) => Boolean(type?.chartType?.startsWith('t:')) && type.chartType !== 't:heikin-ashi';
  return !(own(shown) || own(next)) || sameType(shown, next);
}

/** Whether the engine takes `options` for transform `kind`: the transform's own check, not a copy of it. */
function validBoxOptions(kind, options) {
  if (!Object.hasOwn(BOX_DEFAULTS, kind) || typeof options !== 'object' || options === null || Array.isArray(options)) return false;
  if (!inChartTransforms) return true;
  try { engine.getSeriesTransform(kind).create(options); return true; }
  catch { return false; }
}

/** How each box mode of the old P&F select drew, as the dialog's fields. */
const LEGACY_PFMODE = { atr: { mode: 'atr', size: 1 }, percent: { mode: 'percent', size: 1 }, fixed: { mode: 'fixed', size: 0 } };

/**
 * The per-transform options a saved layout (or its second chart) carries, or
 * null when they are not ones this page can apply. A layout written before
 * the settings dialogs carries `pfmode`, the old box-mode select, instead: it
 * opens on the point and figure options that select drew.
 */
export function savedTransforms(saved) {
  if (saved.transforms !== undefined) {
    const given = saved.transforms;
    if (typeof given !== 'object' || given === null || Array.isArray(given)
      || !Object.entries(given).every(([kind, options]) => validBoxOptions(kind, options))) return null;
    return Object.fromEntries(Object.entries(given).map(([kind, options]) => [kind, { ...options }]));
  }
  if (saved.pfmode === undefined) return {};
  if (typeof saved.pfmode !== 'string' || !Object.hasOwn(LEGACY_PFMODE, saved.pfmode)) return null;
  return { 'point-figure': boxOptions('point-figure', { ...LEGACY_PFMODE[saved.pfmode], reversal: 3, method: 'hl' }) };
}
