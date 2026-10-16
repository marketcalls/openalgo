/**
 * The per-tool settings schema.
 *
 * Two contracts are pinned here. The pure one: dot-path read and write over a
 * drawing, with the coercion a form needs. The one that matters more: every
 * built-in tool declares a schema, every path in it resolves on a drawing of
 * that tool, and every field actually changes what the tool paints. That last
 * sweep is the mechanical form of "never ship a control with nothing behind
 * it": a field that leaves the op stream untouched fails here.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { BUILTIN_DRAWING_TOOLS, RECTANGLE, registerBuiltinDrawingTools } from '../src/draw/tools';
import { TEXT } from '../src/draw/annotation-tools';
import { registeredDrawingTools, drawingSettingsSchema } from '../src/draw/registry';
import {
  LINE_FIELDS, FILL_FIELDS, TEXT_FIELDS, LEVEL_FIELDS, EXTEND_FIELDS, FONT_FIELDS,
  SHAPE_TEXT_FIELDS, PLATE_TEXT_FIELDS, COLOR_FIELD,
  composeSettings, readDrawingSetting, readDrawingSettings, applyDrawingSettings, coerceSettingValue,
  type SettingsField, type SettingsSchema,
} from '../src/draw/schema';
import { RecordingContext } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import { projectAnchors } from '../src/draw/layer';
import type { Drawing, DrawingPoint, DrawingTool, DrawContext, FibLevel } from '../src/draw/types';

beforeAll(() => { registerBuiltinDrawingTools(); });

// ── fixtures ──────────────────────────────────────────────────────────────

const RC = {
  plotWidth: 800, plotHeight: 400, dpr: 1, priceAxisWidth: 60,
  theme: { ...darkTheme, background: '#0d0e12', lineColor: '#4f8cff' },
  priceScale: { priceToY: (p: number) => 400 - p, format: (p: number) => p.toFixed(2) },
  timeScale: { indexToX: (i: number) => i },
  dataLayer: { timeToIndexFloat: (t: number) => t / 6 },
  bars: () => Array.from({ length: 60 }, (_, i) => ({
    time: i * 60, open: 100 + i, high: 130 + i, low: 90 + i,
    close: 110 + i + (i % 3) * 7, volume: 100 + i,
  })),
};

// Away from the left edge, so "extend left" has somewhere to extend to.
const ANCHORS: DrawingPoint[] = [
  { time: 300, price: 100 }, { time: 900, price: 300 }, { time: 1500, price: 200 },
  { time: 1800, price: 260 }, { time: 2100, price: 150 }, { time: 2400, price: 280 },
  { time: 2700, price: 220 }, { time: 3000, price: 240 }, { time: 3300, price: 120 },
];

/** A drawing the way the controller would create it: defaults, then `expand`. */
function defaultDrawing(tool: DrawingTool): Drawing {
  const clicked = ANCHORS.slice(0, tool.points === 0 ? 3 : tool.points);
  const points = tool.expand === undefined ? clicked : tool.expand(clicked, { barSeconds: 60, visibleBars: 100 });
  const d: Drawing = {
    id: 'd', tool: tool.id, paneIndex: 0, zIndex: 0, points,
    style: { ...tool.defaultStyle },
  };
  if (tool.defaultText !== undefined) d.text = { ...tool.defaultText };
  // Somewhere else on screen, so the anchor field has a position to move the
  // tool to when it switches space.
  if (tool.viewport === true) d.viewportPoints = points.map((_, i) => ({ x: 0.3 + 0.1 * i, y: 0.2 + 0.15 * i }));
  return d;
}

/**
 * `globalAlpha` is a context property, not an argument, so the shared recorder
 * cannot see an opacity change. Tag every paint op with the alpha in force, or
 * an inert opacity field passes this file.
 */
class AlphaRecordingContext extends RecordingContext {
  public globalAlpha = 1;
  public override fill(): void { super.fill(); this.tag(); }
  public override fillRect(x: number, y: number, w: number, h: number): void { super.fillRect(x, y, w, h); this.tag(); }
  public override stroke(): void { super.stroke(); this.tag(); }
  public override strokeRect(x: number, y: number, w: number, h: number): void {
    super.strokeRect(x, y, w, h);
    // The shared recorder keeps a stroke's width but not a strokeRect's.
    this.ops[this.ops.length - 1].lineWidth = this.lineWidth;
    this.tag();
  }
  public override fillText(t: string, x: number, y: number): void { super.fillText(t, x, y); this.tag(); }
  private tag(): void { this.ops[this.ops.length - 1].args.push(this.globalAlpha); }
}

function paint(tool: DrawingTool, d: Drawing): string {
  const rec = new AlphaRecordingContext();
  const style = { color: '#4f8cff', lineWidth: 1.5, ...d.style };
  tool.draw({
    ctx: rec as unknown as CanvasRenderingContext2D,
    rc: RC as never,
    // The layer's own projection, so a field read there (the space) is checked
    // by what it paints like every other.
    pts: projectAnchors(RC as never, d),
    drawing: d,
    style,
    selected: false,
    formatPrice: (p: number) => p.toFixed(2),
  } as DrawContext);
  return JSON.stringify(rec.ops);
}

const withPatch = (d: Drawing, patch: Record<string, unknown>): Drawing => ({ ...d, ...applyDrawingSettings(d, patch) });

// Long enough to wrap inside the widest shape in the fixture (a circle whose
// radius is the whole leg), at the recorder's six px per character.
const LONG = 'the quick brown fox jumps over the lazy dog again and again and again, and then once more for luck, and again after that';
const ALT_LEVELS: FibLevel[] = [{ ratio: 0.3, color: '#101010' }, { ratio: 0.9, color: '#202020', label: 'NINE' }];

/**
 * What else must be on for a field to have any effect: a fill colour needs the
 * fill on, a wrap width needs wrapping on, a border colour needs the border.
 */
function companions(path: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (path.startsWith('text.') && path !== 'text.value') out['text.value'] = LONG;
  if (path === 'style.fillColor' || path === 'style.fillOpacity') out['style.fill'] = true;
  if (path === 'text.wrapWidth') out['text.wrap'] = true;
  if (path === 'text.backgroundColor' || path === 'text.backgroundOpacity') out['text.background'] = true;
  if (path === 'text.borderColor') out['text.border'] = true;
  return out;
}

/** Two values of a field that must paint differently. */
function variants(field: SettingsField, current: unknown): [unknown, unknown] {
  switch (field.kind) {
    case 'boolean': return [true, false];
    case 'select':
    case 'lineStyle': {
      const opts = field.options ?? [];
      return [opts[0].value, opts[opts.length - 1].value];
    }
    case 'color': return [current, current === '#123456' ? '#654321' : '#123456'];
    case 'number': return [current, typeof current === 'number' ? current * 2 + 7 : 33];
    case 'opacity': return [current, current === 0.37 ? 0.62 : 0.37];
    case 'text': return [current, 'Zebra quokka'];
    case 'levels': return [current, ALT_LEVELS];
    default: return [current, current];
  }
}

/** A well-formed value for the field, for round-trip checks. */
function sampleFor(field: SettingsField): unknown {
  switch (field.kind) {
    case 'color': return '#abcdef';
    // Inside the field's range, or the coercion clamps it and the trip is not round.
    case 'number': return field.min ?? 5;
    case 'opacity': return 0.5;
    case 'boolean': return true;
    case 'select': return (field.options ?? [{ value: 'x' }])[0].value;
    case 'lineStyle': return 'dashed';
    case 'text': return 'hello';
    case 'levels': return [{ ratio: 0.5, color: '#ffffff' }];
    default: return undefined;
  }
}

// ── every tool ────────────────────────────────────────────────────────────

describe('every built-in tool declares a settings schema', () => {
  it('registers 87 tools, each with at least one field', () => {
    const tools = registeredDrawingTools();
    expect(tools.length).toBe(87);
    for (const t of tools) {
      expect(t.settings, t.id).toBeDefined();
      expect(t.settings?.fields.length, t.id).toBeGreaterThan(0);
    }
  });

  it('declares no field twice', () => {
    for (const t of BUILTIN_DRAWING_TOOLS) {
      const paths = t.settings?.fields.map((f) => f.path) ?? [];
      expect(new Set(paths).size, t.id).toBe(paths.length);
    }
  });

  it.each(BUILTIN_DRAWING_TOOLS.map((t) => [t.id, t] as const))('%s: every path resolves and round-trips', (_id, tool) => {
    const schema = tool.settings as SettingsSchema;
    const d = defaultDrawing(tool);
    const read = readDrawingSettings(d, schema);
    for (const f of schema.fields) {
      // Present as a key even when unset, so a host can iterate the schema.
      expect(Object.prototype.hasOwnProperty.call(read, f.path), f.path).toBe(true);
      expect(/^(style|text|props)\.[^.]+$|^(locked|visible|zIndex|space)$/.test(f.path), f.path).toBe(true);
      const sample = sampleFor(f);
      const next = { ...d, ...applyDrawingSettings(d, { [f.path]: sample }, schema) };
      expect(readDrawingSetting(next, f.path), f.path).toEqual(sample);
    }
  });

  it.each(BUILTIN_DRAWING_TOOLS.map((t) => [t.id, t] as const))('%s: every declared field changes what is painted', (_id, tool) => {
    const schema = tool.settings as SettingsSchema;
    for (const f of schema.fields) {
      const base = withPatch(defaultDrawing(tool), companions(f.path));
      const [a, b] = variants(f, readDrawingSetting(base, f.path));
      const painted = [a, b].map((v) => paint(tool, withPatch(base, { [f.path]: v })));
      expect(painted[0] === painted[1], `${tool.id} ${f.path} is inert`).toBe(false);
    }
  });

  it('marks the tools whose text is their content, and only those', () => {
    const content = BUILTIN_DRAWING_TOOLS.filter((t) => t.settings?.textIsContent === true).map((t) => t.id).sort();
    expect(content).toEqual(['balloon', 'callout', 'comment', 'note', 'price-note', 'signpost', 'table', 'text']);
  });

  it('gives every content tool a default text to start from', () => {
    for (const t of BUILTIN_DRAWING_TOOLS) {
      if (t.settings?.textIsContent === true) expect(t.defaultText?.value, t.id).toBeTruthy();
    }
  });

  it('keeps colours where they apply: a ladder with its own level colours offers none', () => {
    const has = (id: string) => drawingSettingsSchema(id).fields.some((f) => f.path === 'style.color');
    expect(has('fib-fan')).toBe(false);
    expect(has('gann-fan')).toBe(false);
    expect(has('fib-channel')).toBe(false);
    // The retracement strokes its leg in the drawing colour, so it does.
    expect(has('fib-retracement')).toBe(true);
    // A measurer is tinted by direction, so it does not.
    expect(has('measure')).toBe(false);
  });
});

describe('drawingSettingsSchema', () => {
  it('returns the tool\'s own schema', () => {
    expect(drawingSettingsSchema('rectangle')).toBe(RECTANGLE.settings);
    expect(drawingSettingsSchema('text')).toBe(TEXT.settings);
  });

  it('falls back to the line fields for an unknown or undeclared tool', () => {
    expect(drawingSettingsSchema('no-such-tool').fields).toEqual(LINE_FIELDS);
  });
});

// ── the pure half ─────────────────────────────────────────────────────────

describe('composeSettings', () => {
  it('flattens lists and single fields, dropping repeated paths', () => {
    const s = composeSettings([LINE_FIELDS, COLOR_FIELD, [COLOR_FIELD], EXTEND_FIELDS]);
    expect(s.fields.map((f) => f.path)).toEqual([
      'style.color', 'style.lineWidth', 'style.lineStyle', 'style.extendLeft', 'style.extendRight',
    ]);
    expect(s.textIsContent).toBeUndefined();
    expect(composeSettings([TEXT_FIELDS], { textIsContent: true }).textIsContent).toBe(true);
  });

  it('ships the shared vocabulary under the expected roots', () => {
    for (const f of [...LINE_FIELDS, ...FILL_FIELDS, ...LEVEL_FIELDS, ...EXTEND_FIELDS]) expect(f.path.startsWith('style.')).toBe(true);
    for (const f of [...TEXT_FIELDS, ...FONT_FIELDS, ...SHAPE_TEXT_FIELDS, ...PLATE_TEXT_FIELDS]) expect(f.path.startsWith('text.')).toBe(true);
  });
});

describe('readDrawingSettings', () => {
  const d: Drawing = {
    id: 'a', tool: 'rectangle', paneIndex: 0, zIndex: -1, locked: true,
    points: [], style: { color: '#fff', levels: [{ ratio: 0.5 }] },
    text: { value: 'hi', bold: true }, props: { side: 'left' },
  };

  it('reads style, text, props and the flags by dot path', () => {
    expect(readDrawingSetting(d, 'style.color')).toBe('#fff');
    expect(readDrawingSetting(d, 'text.bold')).toBe(true);
    expect(readDrawingSetting(d, 'props.side')).toBe('left');
    expect(readDrawingSetting(d, 'zIndex')).toBe(-1);
    expect(readDrawingSetting(d, 'locked')).toBe(true);
    expect(readDrawingSetting(d, 'visible')).toBeUndefined();
  });

  it('answers undefined, never throws, for a path the model has no home for', () => {
    expect(readDrawingSetting(d, 'style')).toBeUndefined();
    expect(readDrawingSetting(d, 'id')).toBeUndefined();
    expect(readDrawingSetting(d, 'style.levels.0')).toBeUndefined();
    expect(readDrawingSetting(d, '')).toBeUndefined();
  });

  it('hands levels back as a copy, so a host cannot edit the drawing behind the controller', () => {
    const levels = readDrawingSetting(d, 'style.levels') as FibLevel[];
    levels[0].ratio = 0.9;
    expect(d.style.levels?.[0].ratio).toBe(0.5);
  });

  it('keys the result by every field of the schema', () => {
    const out = readDrawingSettings(d, composeSettings([LINE_FIELDS]));
    expect(Object.keys(out)).toEqual(['style.color', 'style.lineWidth', 'style.lineStyle']);
    expect(out['style.lineWidth']).toBeUndefined();
  });
});

describe('applyDrawingSettings', () => {
  const d: Drawing = {
    id: 'a', tool: 'text', paneIndex: 0, zIndex: 0,
    points: [], style: { color: '#fff', lineWidth: 2 }, text: { value: 'hi', bold: true },
  };

  it('returns whole bags, so merge and replace both land the same state', () => {
    const p = applyDrawingSettings(d, { 'style.color': '#000', 'text.value': 'yo', 'props.k': 1, zIndex: 3, locked: true });
    expect(p.style).toEqual({ color: '#000', lineWidth: 2 });
    expect(p.text).toEqual({ value: 'yo', bold: true });
    expect(p.props).toEqual({ k: 1 });
    expect(p.zIndex).toBe(3);
    expect(p.locked).toBe(true);
  });

  it('leaves the source drawing untouched', () => {
    applyDrawingSettings(d, { 'style.color': '#000', 'text.bold': false });
    expect(d.style.color).toBe('#fff');
    expect(d.text?.bold).toBe(true);
  });

  it('removes a key on undefined, which is how a host resets to default', () => {
    const p = applyDrawingSettings(d, { 'style.lineWidth': undefined, 'text.bold': undefined });
    expect(p.style).toEqual({ color: '#fff' });
    expect(p.text).toEqual({ value: 'hi' });
  });

  it('touches only the bags named in the patch', () => {
    const p = applyDrawingSettings(d, { 'style.color': '#000' });
    expect(Object.keys(p)).toEqual(['style']);
  });

  it('ignores paths the model has no home for', () => {
    const p = applyDrawingSettings(d, { id: 'evil', 'points.0': 1, 'style.a.b': 2, tool: 'x', createdAt: 1 });
    expect(p).toEqual({});
  });

  it('gives a face-only text block an empty value rather than dropping it', () => {
    const bare: Drawing = { id: 'b', tool: 'fib-retracement', paneIndex: 0, zIndex: 0, points: [], style: {} };
    expect(applyDrawingSettings(bare, { 'text.fontSize': 14 }).text).toEqual({ value: '', fontSize: 14 });
  });

  it('accepts only a boolean for locked and visible, and a finite number for zIndex', () => {
    expect(applyDrawingSettings(d, { locked: 'yes', visible: 1, zIndex: 'top' })).toEqual({});
    expect(applyDrawingSettings(d, { zIndex: Number.NaN })).toEqual({});
    expect(applyDrawingSettings(d, { visible: false })).toEqual({ visible: false });
  });

  it('coerces form strings by kind when given the schema, and drops undeclared paths', () => {
    const p = applyDrawingSettings(d, {
      'text.fontSize': '18', 'text.bold': 'false', 'text.backgroundOpacity': '1.7',
      'text.align': 'center', 'text.wrap': 1, 'style.color': '#000',
    }, TEXT.settings);
    expect(p.text).toEqual({ value: 'hi', fontSize: 18, bold: false, backgroundOpacity: 1, align: 'center', wrap: true });
    // The text tool declares no style.color: it goes nowhere.
    expect(p.style).toBeUndefined();
  });

  it('drops a value the field cannot hold rather than writing garbage', () => {
    const p = applyDrawingSettings(d, { 'text.fontSize': 'big', 'text.align': 'diagonal' }, TEXT.settings);
    // Uncoercible values read as undefined, which removes the key.
    expect(p.text).toEqual({ value: 'hi', bold: true });
  });
});

describe('coerceSettingValue', () => {
  const f = (kind: SettingsField['kind'], extra: Partial<SettingsField> = {}): SettingsField =>
    ({ path: 'style.x', label: 'x', kind, ...extra });

  it('numbers, clamped to the field range', () => {
    expect(coerceSettingValue(f('number', { min: 1, max: 10 }), '12')).toBe(10);
    expect(coerceSettingValue(f('number', { min: 1 }), 0)).toBe(1);
    expect(coerceSettingValue(f('number'), ' ')).toBeUndefined();
    expect(coerceSettingValue(f('number'), 'abc')).toBeUndefined();
  });

  it('opacity within 0..1', () => {
    expect(coerceSettingValue(f('opacity'), '0.25')).toBe(0.25);
    expect(coerceSettingValue(f('opacity'), -1)).toBe(0);
    expect(coerceSettingValue(f('opacity'), 4)).toBe(1);
  });

  it('booleans from the strings a form emits', () => {
    expect(coerceSettingValue(f('boolean'), 'true')).toBe(true);
    expect(coerceSettingValue(f('boolean'), '0')).toBe(false);
    expect(coerceSettingValue(f('boolean'), 'maybe')).toBeUndefined();
  });

  it('line styles and selects only from their options', () => {
    expect(coerceSettingValue(f('lineStyle'), 'dotted')).toBe('dotted');
    expect(coerceSettingValue(f('lineStyle'), 'wavy')).toBeUndefined();
    const sel = f('select', { options: [{ value: 'a', label: 'A' }] });
    expect(coerceSettingValue(sel, 'a')).toBe('a');
    expect(coerceSettingValue(sel, 'b')).toBeUndefined();
    // No option list means free-form, the way a typed font stack is.
    expect(coerceSettingValue(f('select'), 'Georgia, serif')).toBe('Georgia, serif');
  });

  it('levels, validated one by one', () => {
    const out = coerceSettingValue(f('levels'), [
      { ratio: '0.5', color: '#fff', enabled: 'false', label: 'half' },
      { ratio: 'x' }, 'junk', null, { ratio: 1, color: '', label: '' },
    ]);
    expect(out).toEqual([{ ratio: 0.5, color: '#fff', enabled: false, label: 'half' }, { ratio: 1 }]);
    expect(coerceSettingValue(f('levels'), 'not a list')).toBeUndefined();
  });

  it('null and undefined mean unset', () => {
    expect(coerceSettingValue(f('color'), null)).toBeUndefined();
    expect(coerceSettingValue(f('text'), undefined)).toBeUndefined();
  });
});
