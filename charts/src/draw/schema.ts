/**
 * The per-tool settings schema: what a host may show in a drawing's settings
 * dialog, expressed as dot paths into the drawing (`style.color`,
 * `text.fontSize`, `props.foo`, `intervals.from`, `zIndex`, `space`) with a
 * control kind and a label.
 *
 * The rule the whole module exists for: a tool declares only fields its `draw`
 * actually reads. A schema is not a wish list. A host renders exactly what is
 * declared, so an entry with nothing behind it becomes a control that does
 * nothing, which is worse than no control at all.
 *
 * Pure: no DOM, no registry. The registry lookup (`drawingSettingsSchema`)
 * lives in registry.ts so this file has no import that could loop back here.
 */
import type {
  Drawing, DrawingSpace, DrawingText, FibLevel, SettingsField, SettingsSchema,
} from './types';

// The field types live in types.ts, beside the `DrawingTool.settings` that
// names them, so the two modules do not import each other; the public names
// are still exported from here.
export type { FieldKind, FieldGroup, SettingsField, SettingsSchema } from './types';

// ── option lists ──────────────────────────────────────────────────────────

export const LINE_STYLE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'solid', label: 'Solid' },
  { value: 'dashed', label: 'Dashed' },
  { value: 'dotted', label: 'Dotted' },
];

export const ALIGN_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'left', label: 'Left' },
  { value: 'center', label: 'Center' },
  { value: 'right', label: 'Right' },
];

export const VALIGN_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'top', label: 'Top' },
  { value: 'middle', label: 'Middle' },
  { value: 'bottom', label: 'Bottom' },
];

export const TEXT_POSITION_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'inside', label: 'Inside' },
  { value: 'outside', label: 'Outside' },
];

/** The two coordinate spaces, as a host offers them: follow the bars, or stay on screen. */
export const SPACE_OPTIONS: ReadonlyArray<{ value: DrawingSpace; label: string }> = [
  { value: 'data', label: 'Time and price' },
  { value: 'viewport', label: 'Screen' },
];

/**
 * Font stacks a host can offer. Values are real CSS stacks, so a drawing's
 * `text.fontFamily` needs no translation before it reaches `ctx.font`; a host
 * may still accept any stack the user types.
 */
export const FONT_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif', label: 'Sans' },
  { value: 'ui-serif, Georgia, Times New Roman, serif', label: 'Serif' },
  { value: 'ui-monospace, Menlo, Consolas, monospace', label: 'Mono' },
];

// ── field vocabulary ──────────────────────────────────────────────────────

export const COLOR_FIELD: SettingsField = { path: 'style.color', label: 'Color', kind: 'color', group: 'line' };
export const LINE_WIDTH_FIELD: SettingsField = {
  path: 'style.lineWidth', label: 'Width', kind: 'number', min: 1, max: 12, step: 0.5, group: 'line',
};
export const LINE_STYLE_FIELD: SettingsField = {
  path: 'style.lineStyle', label: 'Line style', kind: 'lineStyle', options: LINE_STYLE_OPTIONS, group: 'line',
};

/** Colour, width and dash: what every stroked tool reads through `applyStroke`. */
export const LINE_FIELDS: readonly SettingsField[] = [COLOR_FIELD, LINE_WIDTH_FIELD, LINE_STYLE_FIELD];

export const FILL_FIELDS: readonly SettingsField[] = [
  { path: 'style.fill', label: 'Fill', kind: 'boolean', group: 'fill' },
  { path: 'style.fillColor', label: 'Fill color', kind: 'color', group: 'fill' },
  { path: 'style.fillOpacity', label: 'Fill opacity', kind: 'opacity', min: 0, max: 1, step: 0.01, group: 'fill' },
];

export const EXTEND_FIELDS: readonly SettingsField[] = [
  { path: 'style.extendLeft', label: 'Extend left', kind: 'boolean', group: 'behavior' },
  { path: 'style.extendRight', label: 'Extend right', kind: 'boolean', group: 'behavior' },
];

/**
 * Where the drawing is anchored: to time and price, or to the screen. Declared
 * only by tools that set `viewport`, since the controller converts nothing
 * else. Writing it converts the anchors at the view on screen, so the drawing
 * keeps its place and only stops (or starts) following the bars.
 */
export const SPACE_FIELD: SettingsField = {
  path: 'space', label: 'Anchor', kind: 'select', options: SPACE_OPTIONS, group: 'behavior', defaultValue: 'data',
};

/**
 * The intervals a drawing is shown on (`Drawing.intervals`), as two interval
 * codes, each end included and either one left empty for no limit. No tool
 * declares them, since the engine cannot list a host's intervals: a host that
 * offers visibility per interval adds them to a tool's schema with
 * `composeSettings`, and `applyDrawingSettings` writes the pair as the patch's
 * `intervals`, with both ends cleared meaning every interval.
 */
export const INTERVAL_FIELDS: readonly SettingsField[] = [
  { path: 'intervals.from', label: 'Show from', kind: 'interval', group: 'visibility' },
  { path: 'intervals.to', label: 'Show up to', kind: 'interval', group: 'visibility' },
];

export const SHOW_LABELS_FIELD: SettingsField = {
  path: 'style.showLabels', label: 'Show labels', kind: 'boolean', group: 'behavior',
};

export const LEVEL_FIELDS: readonly SettingsField[] = [
  { path: 'style.levels', label: 'Levels', kind: 'levels', group: 'levels' },
  { ...SHOW_LABELS_FIELD, group: 'levels' },
];

/**
 * The face of any text a tool prints, including readouts it composes itself
 * (a fib level's ratio, a measure's chip, a horizontal line's price tag).
 * Tools that print nothing do not declare these.
 */
export const FONT_FIELDS: readonly SettingsField[] = [
  { path: 'text.color', label: 'Text color', kind: 'color', group: 'text' },
  { path: 'text.fontSize', label: 'Font size', kind: 'number', min: 6, max: 96, step: 1, group: 'text' },
  { path: 'text.fontFamily', label: 'Font', kind: 'select', options: FONT_OPTIONS, group: 'text' },
  { path: 'text.bold', label: 'Bold', kind: 'boolean', group: 'text' },
  { path: 'text.italic', label: 'Italic', kind: 'boolean', group: 'text' },
];

export const TEXT_VALUE_FIELD: SettingsField = { path: 'text.value', label: 'Text', kind: 'text', group: 'text' };

/** The full surface of the text tool: content, face, layout, plate. */
export const TEXT_FIELDS: readonly SettingsField[] = [
  TEXT_VALUE_FIELD,
  ...FONT_FIELDS,
  { path: 'text.align', label: 'Align', kind: 'select', options: ALIGN_OPTIONS, group: 'text' },
  { path: 'text.valign', label: 'Vertical align', kind: 'select', options: VALIGN_OPTIONS, group: 'text' },
  { path: 'text.wrap', label: 'Wrap', kind: 'boolean', group: 'text' },
  { path: 'text.wrapWidth', label: 'Wrap width', kind: 'number', min: 40, max: 2000, step: 10, group: 'text' },
  { path: 'text.background', label: 'Background', kind: 'boolean', group: 'text' },
  { path: 'text.backgroundColor', label: 'Background color', kind: 'color', group: 'text' },
  { path: 'text.backgroundOpacity', label: 'Background opacity', kind: 'opacity', min: 0, max: 1, step: 0.01, group: 'text' },
  { path: 'text.border', label: 'Border', kind: 'boolean', group: 'text' },
  { path: 'text.borderColor', label: 'Border color', kind: 'color', group: 'text' },
];

/**
 * A label attached to a shape: it sits inside or just above the outline, so
 * it has an alignment and a position but no plate of its own (the shape is
 * the plate) and wraps to the shape's width rather than a width of its own.
 */
export const SHAPE_TEXT_FIELDS: readonly SettingsField[] = [
  TEXT_VALUE_FIELD,
  ...FONT_FIELDS,
  { path: 'text.align', label: 'Align', kind: 'select', options: ALIGN_OPTIONS, group: 'text' },
  { path: 'text.valign', label: 'Vertical align', kind: 'select', options: VALIGN_OPTIONS, group: 'text' },
  { path: 'text.wrap', label: 'Wrap', kind: 'boolean', group: 'text' },
  { path: 'text.position', label: 'Label position', kind: 'select', options: TEXT_POSITION_OPTIONS, group: 'text' },
];

/**
 * An annotation's plate (note, balloon, comment, signpost, price note): always
 * drawn, so there is no `background` toggle, only its colour and opacity, plus
 * an optional border.
 */
export const PLATE_TEXT_FIELDS: readonly SettingsField[] = [
  TEXT_VALUE_FIELD,
  ...FONT_FIELDS,
  { path: 'text.backgroundColor', label: 'Plate color', kind: 'color', group: 'text' },
  { path: 'text.backgroundOpacity', label: 'Plate opacity', kind: 'opacity', min: 0, max: 1, step: 0.01, group: 'text' },
  { path: 'text.border', label: 'Border', kind: 'boolean', group: 'text' },
  { path: 'text.borderColor', label: 'Border color', kind: 'color', group: 'text' },
];

/**
 * Build a schema from field lists and single fields. Later duplicates of a
 * path are dropped so a tool can layer a group over a shared list without
 * showing one control twice.
 */
export function composeSettings(
  parts: ReadonlyArray<readonly SettingsField[] | SettingsField>,
  opts: { textIsContent?: boolean } = {},
): SettingsSchema {
  const seen = new Set<string>();
  const fields: SettingsField[] = [];
  for (const part of parts) {
    for (const f of Array.isArray(part) ? part : [part as SettingsField]) {
      if (seen.has(f.path)) continue;
      seen.add(f.path);
      fields.push(f);
    }
  }
  return opts.textIsContent === true ? { fields, textIsContent: true } : { fields };
}

// ── dot-path access ───────────────────────────────────────────────────────

type BagRoot = 'style' | 'text' | 'props' | 'intervals';
type FlagRoot = 'locked' | 'visible' | 'zIndex' | 'space';

const BAG_ROOTS: ReadonlySet<string> = new Set<BagRoot>(['style', 'text', 'props', 'intervals']);
const FLAG_ROOTS: ReadonlySet<string> = new Set<FlagRoot>(['locked', 'visible', 'zIndex', 'space']);

/** A path split and checked. `null` for anything the model has no home for. */
function parsePath(path: string): { root: BagRoot; key: string } | { root: FlagRoot; key: null } | null {
  const parts = path.split('.');
  // Each part read below is there by the length it is compared with.
  if (parts.length === 1 && FLAG_ROOTS.has(parts[0]!)) return { root: parts[0] as FlagRoot, key: null };
  if (parts.length === 2 && BAG_ROOTS.has(parts[0]!) && parts[1] !== '') {
    return { root: parts[0] as BagRoot, key: parts[1]! };
  }
  return null;
}

/** The value at a dot path, or `undefined` when unset or the path is not one the model has. */
export function readDrawingSetting(d: Drawing, path: string): unknown {
  const p = parsePath(path);
  if (p === null) return undefined;
  if (p.key === null) return d[p.root];
  const bag = d[p.root] as Record<string, unknown> | undefined;
  const v = bag?.[p.key];
  // Levels are handed back as a copy: a host editing the list in place would
  // otherwise change the drawing behind the controller's back, with no undo.
  return Array.isArray(v) ? (v as FibLevel[]).map((l) => ({ ...l })) : v;
}

/**
 * Every field of a schema read off a drawing, keyed by path. Unset fields use
 * their declared default value, or remain `undefined` when no default exists.
 */
export function readDrawingSettings(d: Drawing, schema: SettingsSchema): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of schema.fields) out[f.path] = readDrawingSetting(d, f.path) ?? f.defaultValue;
  return out;
}

// ── coercion ──────────────────────────────────────────────────────────────

const LINE_STYLES: ReadonlySet<string> = new Set(['solid', 'dashed', 'dotted']);

function toBoolean(raw: unknown): boolean | undefined {
  if (typeof raw === 'boolean') return raw;
  if (raw === 'true' || raw === 1 || raw === '1') return true;
  if (raw === 'false' || raw === 0 || raw === '0') return false;
  return undefined;
}

function toNumber(raw: unknown): number | undefined {
  const n = typeof raw === 'number' ? raw : typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : NaN;
  return Number.isFinite(n) ? n : undefined;
}

/** One level, validated field by field; `null` when the ratio is unusable. */
function toLevel(raw: unknown): FibLevel | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const ratio = toNumber(r.ratio);
  if (ratio === undefined) return null;
  const out: FibLevel = { ratio };
  if (typeof r.color === 'string' && r.color !== '') out.color = r.color;
  const enabled = toBoolean(r.enabled);
  if (enabled !== undefined) out.enabled = enabled;
  if (typeof r.label === 'string' && r.label !== '') out.label = r.label;
  return out;
}

/**
 * A raw control value made into what the field's kind stores, or `undefined`
 * when it cannot be. Form inputs hand back strings; a settings panel should
 * not have to know that `fontSize` is a number and `bold` a boolean.
 */
export function coerceSettingValue(field: SettingsField, raw: unknown): unknown {
  if (raw === undefined || raw === null) return undefined;
  switch (field.kind) {
    case 'color':
    case 'text':
      return typeof raw === 'string' ? raw : String(raw);
    case 'number': {
      const n = toNumber(raw);
      if (n === undefined) return undefined;
      const lo = field.min ?? -Infinity;
      const hi = field.max ?? Infinity;
      return n < lo ? lo : n > hi ? hi : n;
    }
    case 'opacity': {
      const n = toNumber(raw);
      return n === undefined ? undefined : n < 0 ? 0 : n > 1 ? 1 : n;
    }
    case 'boolean':
      return toBoolean(raw);
    case 'lineStyle':
      return typeof raw === 'string' && LINE_STYLES.has(raw) ? raw : undefined;
    case 'select': {
      if (typeof raw !== 'string') return undefined;
      // A select with no option list is free-form (a font stack the user typed).
      return field.options === undefined || field.options.some((o) => o.value === raw) ? raw : undefined;
    }
    case 'interval': {
      // Empty is no limit on that side, which is the key removed.
      const code = typeof raw === 'string' ? raw.trim() : '';
      return code === '' ? undefined : code;
    }
    case 'levels': {
      if (!Array.isArray(raw)) return undefined;
      const out: FibLevel[] = [];
      for (const item of raw) {
        const lv = toLevel(item);
        if (lv !== null) out.push(lv);
      }
      return out;
    }
    default:
      return undefined;
  }
}

/**
 * Turn `{ 'style.color': '#f00', 'text.value': 'Hi', zIndex: 2 }` into the
 * partial a controller's `update` accepts. Bags come back whole
 * (`style: { ...d.style, color }`), so it does not matter whether the
 * controller merges or replaces them. A value of `undefined` removes the key,
 * which is how a host offers "reset to default". The `intervals` pair comes
 * back whole as well, as the range to replace the drawing's; with neither end
 * left it is `{}`, which a controller takes as no range, every interval.
 *
 * With a `schema`, each value is coerced to its field's kind and any path the
 * schema does not declare is dropped: a host can hand over its form state as
 * is. Without one, values are written verbatim. Paths the model has no home
 * for are ignored either way.
 */
export function applyDrawingSettings(
  d: Drawing,
  patch: Record<string, unknown>,
  schema?: SettingsSchema,
): Partial<Drawing> {
  const byPath = schema === undefined ? null : new Map(schema.fields.map((f) => [f.path, f] as const));
  const out: Partial<Drawing> = {};
  const bags: Partial<Record<BagRoot, Record<string, unknown>>> = {};
  for (const path of Object.keys(patch)) {
    const p = parsePath(path);
    if (p === null) continue;
    let value = patch[path];
    if (byPath !== null) {
      const field = byPath.get(path);
      if (field === undefined) continue;
      value = coerceSettingValue(field, value);
    }
    if (p.key === null) {
      if (value === undefined) continue;
      if (p.root === 'zIndex') {
        if (typeof value === 'number' && Number.isFinite(value)) out.zIndex = value;
      } else if (p.root === 'space') {
        if (value === 'data' || value === 'viewport') out.space = value;
      } else if (typeof value === 'boolean') {
        out[p.root] = value;
      }
      continue;
    }
    const bag = bags[p.root] ?? { ...(d[p.root] as Record<string, unknown> | undefined) };
    bags[p.root] = bag;
    if (value === undefined) delete bag[p.key];
    else bag[p.key] = value;
  }
  if (bags.style !== undefined) out.style = bags.style as Drawing['style'];
  if (bags.props !== undefined) out.props = bags.props;
  if (bags.intervals !== undefined) {
    const { from, to } = bags.intervals;
    out.intervals = { ...(typeof from === 'string' ? { from } : {}), ...(typeof to === 'string' ? { to } : {}) };
  }
  if (bags.text !== undefined) {
    // `value` is the one required field, but a tool with only a readout (a fib
    // ladder's labels) carries a face and no content, so a missing value is
    // an empty string rather than a dropped block.
    const t = bags.text;
    if (typeof t.value !== 'string') t.value = '';
    out.text = t as unknown as DrawingText;
  }
  return out;
}
