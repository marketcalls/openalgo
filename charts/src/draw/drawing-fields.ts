/**
 * The fields of the drawing model as the readers of outside input know them:
 * the migration (the load path, lenient) and the clipboard (a paste, strict),
 * with the viewport and interval readers beside them. One statement of every
 * style and text key and of the guards, so a key added to `DrawingStyle` or
 * `DrawingText` is added here once and neither path drops it. Each reader
 * keeps its own policy: the clipboard's caps and its all-or-nothing gate,
 * the migration's one-field-at-a-time leniency. Pure: no registry, no chart.
 */
import type { DrawingPoint, DrawingText } from './types';
import { isRecord } from '../helpers/validate';

// The readers here take keyed fields from any object that is not an array:
// the shared test the widget readers use too, so the two cannot drift apart.
export { isRecord };

/** A finite number. */
export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

export const isString = (v: unknown): v is string => typeof v === 'string';

export const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): v is T =>
  typeof v === 'string' && (allowed as readonly string[]).includes(v);

/** A key that would reach Object.prototype through a spread or a dynamic assignment. */
export const isUnsafeKey = (key: string): boolean =>
  key === '__proto__' || key === 'constructor' || key === 'prototype';

export const LINE_STYLES = ['solid', 'dashed', 'dotted'] as const;
const ALIGNS = ['left', 'center', 'right'] as const;
const VALIGNS = ['top', 'middle', 'bottom'] as const;
const POSITIONS = ['inside', 'outside'] as const;

/** The style keys by the type they hold; `lineStyle` and `levels` are read on their own. */
export const STYLE_STRINGS = ['color', 'fillColor'] as const;
export const STYLE_NUMBERS = ['lineWidth', 'fillOpacity', 'accountSize', 'risk'] as const;
export const STYLE_FLAGS = ['fill', 'extendLeft', 'extendRight', 'showLabels', 'showStats', 'pressure'] as const;

const TEXT_STRINGS = ['color', 'fontFamily', 'backgroundColor', 'borderColor'] as const;
const TEXT_NUMBERS = ['fontSize', 'wrapWidth', 'backgroundOpacity'] as const;
const TEXT_FLAGS = ['bold', 'italic', 'wrap', 'background', 'border'] as const;

/**
 * A text block with `value` as its content and every key `fields` holds with
 * the right type, closed to the keys {@link DrawingText} declares. `str` is
 * what a string must pass: any string on the load path, a short one in a paste.
 */
export function readText(value: string, fields: Record<string, unknown>, str: (v: unknown) => v is string): DrawingText {
  const t: DrawingText = { value };
  for (const key of TEXT_STRINGS) {
    const v = fields[key];
    if (str(v)) t[key] = v;
  }
  for (const key of TEXT_NUMBERS) {
    const v = fields[key];
    if (isNum(v)) t[key] = v;
  }
  for (const key of TEXT_FLAGS) {
    const v = fields[key];
    if (typeof v === 'boolean') t[key] = v;
  }
  if (oneOf(fields.align, ALIGNS)) t.align = fields.align;
  if (oneOf(fields.valign, VALIGNS)) t.valign = fields.valign;
  if (oneOf(fields.position, POSITIONS)) t.position = fields.position;
  return t;
}

/**
 * The 1.9.x text fields of a style bag, each under its current name.
 * `fontWeight` and `fontStyle` were enums whose only non-default value is now
 * a flag, so `'normal'` simply disappears.
 */
export function legacyTextFields(style: Record<string, unknown>): Record<string, unknown> {
  return {
    color: style.fontColor,
    fontSize: style.fontSize,
    fontFamily: style.fontFamily,
    bold: style.fontWeight === 'bold' ? true : undefined,
    italic: style.fontStyle === 'italic' ? true : undefined,
    align: style.textAlign,
    valign: style.textVAlign,
    position: style.textPosition,
    wrap: style.wrap,
    wrapWidth: style.wrapWidth,
    background: style.background,
    backgroundColor: style.backgroundColor,
    backgroundOpacity: style.backgroundOpacity,
    border: style.border,
    borderColor: style.borderColor,
  };
}

/**
 * Anchors in data space, all or nothing: one unmappable anchor is a shape
 * that can never be drawn or hit-tested. At most `max` of them.
 */
export function readPoints(value: unknown, max = Infinity): DrawingPoint[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > max) return null;
  const out: DrawingPoint[] = [];
  for (const p of value) {
    if (!isRecord(p) || !isNum(p.time) || !isNum(p.price)) return null;
    const q: DrawingPoint = { time: p.time, price: p.price };
    if (isNum(p.pressure) && p.pressure >= 0 && p.pressure <= 1) q.pressure = p.pressure;
    out.push(q);
  }
  return out;
}
