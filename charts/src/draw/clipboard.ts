/**
 * Clipboard transfer for drawings: the layer between the drawing model and the
 * OS clipboard.
 *
 * Two things make this more than `JSON.stringify`:
 *
 * 1. **The OS clipboard is shared with everything else on the machine.** A
 *    paste can arrive from a spreadsheet, another application, or a hand-edited
 *    copy of our own payload. So the payload is written under a namespaced key
 *    and everything read back is validated field by field before it can reach
 *    the model. Foreign text is *not ours* and is ignored, never an exception
 *    the host has to catch on every Ctrl+V.
 * 2. **Clipboard access is async and permission-gated.** `navigator.clipboard`
 *    rejects when the document is not focused, the page is not secure, or the
 *    user denied the permission. Copy must still work inside the tab, so every
 *    write also lands in a module-level in-memory clipboard which is shared by
 *    every controller in the page. That is what makes chart-to-chart paste work
 *    with the permission denied, and it is why the memory store is a singleton
 *    rather than per-controller state.
 *
 * The payload body is a drawings document (`DrawingsDocument`), so a copy made
 * by a 1.9.x build (a version 1 body carrying the old style-bag text fields)
 * is upgraded by the same migration a saved layout goes through.
 *
 * A `paneIndex` in the payload counts the price pane as 0 and the study panes
 * after it in their order, whatever slot the price pane holds on the chart it
 * came from: `DrawingController` converts on copy and on paste, so a drawing
 * copied beside the candles pastes beside the candles on a chart that keeps
 * its price pane below its studies. On a chart with the price pane on top,
 * the default, that is the chart's own slot, as it always was.
 */
import type { Drawing, DrawingIntervalRange, DrawingPoint, DrawingStyle, DrawingText, FibLevel } from './types';
import { DRAWING_STATE_VERSION } from './types';
import { hasDrawingTool, viewportDrawingTool } from './registry';
import { migrateDrawings } from './migrate';
import { readViewportPoints } from './viewport';
import { drawingsDocumentVersion, readIntervalRange } from './intervals';
import {
  isNum, isRecord, isUnsafeKey, legacyTextFields, oneOf, readPoints, readText,
  LINE_STYLES, STYLE_FLAGS, STYLE_NUMBERS, STYLE_STRINGS,
} from './drawing-fields';

/**
 * Top-level key of the JSON payload. Namespaced so a paste of arbitrary text,
 * or of JSON belonging to some other application, is recognisable as not ours
 * by looking at one property.
 */
export const DRAWING_CLIPBOARD_KEY = 'openalgo-charts/drawings';

/**
 * The newest payload version this build reads. Tracks the model version, since
 * the body *is* a drawings document: version 1 carried 1.9.x drawings,
 * version 2 carries the split text and levelled fibs, and version 3 adds the
 * interval range a drawing is shown on. A payload is written as the lowest
 * version that holds it, so a copy with no range still pastes into a build
 * that reads only version 2, which refuses anything newer.
 */
export const DRAWING_CLIPBOARD_VERSION: number = DRAWING_STATE_VERSION;

/**
 * Caps applied to anything crossing the process boundary. They exist to keep a
 * hostile or corrupt payload from turning into a multi-megabyte model, not to
 * constrain honest use: the largest built-in tool is a freehand path, and a
 * stroke of 20k samples is already far past what a pointer can produce.
 */
const MAX_DRAWINGS = 512;
const MAX_POINTS = 20000;
const MAX_KEYS = 64;
const MAX_STRING = 4096;
const MAX_ARRAY = 64;
/** How deep `props` may nest. A table's cells are two levels; three is plenty. */
const MAX_PROPS_DEPTH = 3;

/** The async slice of `navigator.clipboard` this module uses. */
export interface ClipboardPort {
  writeText(text: string): Promise<void>;
  readText(): Promise<string>;
}

/**
 * Process-wide fallback store. Shared deliberately: two charts in one page must
 * be able to exchange a drawing even when the OS clipboard is unavailable.
 */
let memoryText: string | null = null;

/** Test seam: drop whatever the in-memory clipboard is holding. */
export function clearMemoryClipboard(): void {
  memoryText = null;
}

/** `navigator.clipboard` when the browser exposes it, else null. */
export function systemClipboard(): ClipboardPort | null {
  const nav = (globalThis as { navigator?: { clipboard?: Partial<ClipboardPort> } }).navigator;
  const c = nav?.clipboard;
  if (c === undefined || typeof c.writeText !== 'function' || typeof c.readText !== 'function') return null;
  return c as ClipboardPort;
}

/**
 * A deep copy of `d` to insert as the user's own new drawing: no id, no
 * creation time and no policy, as a duplicate or a drag that copies makes.
 */
export function freshCopy(d: Drawing): Omit<Drawing, 'id' | 'createdAt' | 'policy'> {
  const { id: _id, createdAt: _createdAt, policy: _policy, ...rest } = cloneDrawing(d);
  void _id; void _createdAt; void _policy;
  return rest;
}

/** Deep copy of the persisted fields, so a clone shares nothing with its source. */
export function cloneDrawing(d: Drawing): Drawing {
  const out: Drawing = {
    ...d,
    points: d.points.map(clonePoint),
    style: cloneStyle(d.style),
  };
  if (d.viewportPoints !== undefined) out.viewportPoints = d.viewportPoints.map((p) => ({ x: p.x, y: p.y }));
  if (d.text !== undefined) out.text = { ...d.text };
  if (d.props !== undefined) out.props = JSON.parse(JSON.stringify(d.props)) as Record<string, unknown>;
  if (d.policy !== undefined) out.policy = { ...d.policy };
  if (d.intervals !== undefined) out.intervals = { ...d.intervals };
  return out;
}

// Pressure rides with a brush sample; dropping it here would repaint a pen
// stroke at the configured width after a paste.
function clonePoint(p: DrawingPoint): DrawingPoint {
  return p.pressure === undefined ? { time: p.time, price: p.price } : { time: p.time, price: p.price, pressure: p.pressure };
}

function cloneStyle(style: DrawingStyle): DrawingStyle {
  const out: DrawingStyle = { ...style };
  if (style.levels !== undefined) out.levels = style.levels.map((l) => ({ ...l }));
  return out;
}

/** Serialise drawings into the namespaced payload written to the clipboard. */
export function encodeClipboardPayload(drawings: readonly Drawing[]): string {
  return JSON.stringify({
    [DRAWING_CLIPBOARD_KEY]: {
      version: drawingsDocumentVersion(drawings),
      drawings: drawings.map((d) => ({
        tool: d.tool,
        points: d.points.map(clonePoint),
        // Fractions of the pane, so a paste lands at the same place on any
        // chart, whatever its size.
        ...(d.space === 'viewport'
          ? { space: 'viewport', viewportPoints: (d.viewportPoints ?? []).map((p) => ({ x: p.x, y: p.y })) }
          : {}),
        style: d.style ?? {},
        ...(d.text === undefined ? {} : { text: d.text }),
        ...(d.props === undefined ? {} : { props: d.props }),
        paneIndex: d.paneIndex,
        zIndex: Number.isFinite(d.zIndex) ? d.zIndex : 0,
        // Where it sits in the stack travels like its z-index; on a chart
        // without that entry it paints in front.
        ...(d.stackAbove === undefined ? {} : { stackAbove: d.stackAbove }),
        ...(d.locked === undefined ? {} : { locked: d.locked }),
        ...(d.visible === undefined ? {} : { visible: d.visible }),
        ...(d.intervals === undefined ? {} : { intervals: { ...d.intervals } }),
        // No `policy`: it binds the drawing the host placed, and a paste is
        // the user's own drawing.
      })),
    },
  });
}

const isShortString = (v: unknown): v is string => typeof v === 'string' && v.length <= MAX_STRING;

/**
 * The 1.9.x text fields, and where each one went. Anything still carrying them
 * in `style` is an old payload or a hand-edited one; either way they are lifted
 * out here so the style bag stays closed.
 */
const LEGACY_TEXT_KEYS = [
  'text', 'fontSize', 'fontFamily', 'fontWeight', 'fontStyle', 'background', 'backgroundColor',
  'backgroundOpacity', 'border', 'borderColor', 'wrap', 'wrapWidth', 'textAlign', 'textVAlign',
  'textPosition', 'fontColor',
] as const;

function liftLegacyText(style: Record<string, unknown>): DrawingText | null {
  return typeof style.text === 'string' ? sanitizeText({ value: style.text, ...legacyTextFields(style) }) : null;
}

/**
 * One level survives as `{ ratio }` from a bare number (the 1.9.x shape) or as
 * a validated record. A malformed entry drops the whole list rather than one
 * level: a fib with a hole in it is a different tool from the one copied.
 */
function sanitizeLevels(value: unknown): FibLevel[] | null {
  if (!Array.isArray(value) || value.length > MAX_ARRAY) return null;
  const out: FibLevel[] = [];
  for (const v of value) {
    if (isNum(v)) {
      out.push({ ratio: v });
    } else if (isRecord(v) && isNum(v.ratio)) {
      const l: FibLevel = { ratio: v.ratio };
      if (isShortString(v.color)) l.color = v.color;
      if (typeof v.enabled === 'boolean') l.enabled = v.enabled;
      if (isShortString(v.label)) l.label = v.label;
      out.push(l);
    } else {
      return null;
    }
  }
  return out;
}

/**
 * The style bag, one key at a time. A known key with the wrong type is
 * dropped, not fatal; an unknown primitive is kept, because it is far more
 * likely to be a newer version's style property than an attack, and keeping it
 * still yields a drawing the current renderer can handle. Functions, nested
 * objects and giant strings are dropped. The 1.9.x text keys are removed here
 * and reappear as the drawing's `text`, see {@link liftLegacyText}.
 *
 * Kept by `sanitizeDrawing` called directly, that is. A paste goes on through
 * the migration (`decodeClipboardPayload`), whose style bag is closed to the
 * keys this build declares, so a pasted drawing carries no unknown key.
 */
function sanitizeStyle(value: unknown): DrawingStyle | null {
  if (value === undefined) return {};
  if (!isRecord(value)) return null;
  const out: Record<string, unknown> = {};
  let n = 0;
  for (const [key, v] of Object.entries(value)) {
    if (isUnsafeKey(key)) continue;
    if (++n > MAX_KEYS) return null;
    if ((LEGACY_TEXT_KEYS as readonly string[]).includes(key)) continue;
    if (oneOf(key, STYLE_STRINGS)) {
      if (isShortString(v)) out[key] = v;
    } else if (oneOf(key, STYLE_NUMBERS)) {
      if (isNum(v)) out[key] = v;
    } else if (oneOf(key, STYLE_FLAGS)) {
      if (typeof v === 'boolean') out[key] = v;
    } else if (key === 'lineStyle') {
      if (oneOf(v, LINE_STYLES)) out[key] = v;
    } else if (key === 'levels') {
      const levels = sanitizeLevels(v);
      if (levels !== null) out[key] = levels;
    } else if (typeof v === 'string') {
      if (v.length > MAX_STRING) return null;
      out[key] = v;
    } else if (typeof v === 'boolean' || isNum(v)) {
      out[key] = v;
    } else if (Array.isArray(v)) {
      if (v.length > MAX_ARRAY) return null;
      if (v.every(isNum)) out[key] = v.slice();
    }
    // Anything else (null, undefined, object, function) is simply not copied.
  }
  return out as DrawingStyle;
}

/** The text block. Closed: a key this build does not draw is dropped. */
function sanitizeText(value: unknown): DrawingText | null {
  return isRecord(value) && isShortString(value.value) ? readText(value.value, value, isShortString) : null;
}

/**
 * Per-tool extras. JSON primitives, short arrays of them, and plain records a
 * few levels deep; anything else is dropped. Bounded the same way as the
 * style bag so `props` cannot be the way around its caps.
 */
function sanitizeProps(value: unknown, depth = 0): Record<string, unknown> | null {
  if (!isRecord(value)) return null;
  const out: Record<string, unknown> = {};
  let n = 0;
  for (const [key, v] of Object.entries(value)) {
    if (isUnsafeKey(key)) continue;
    if (++n > MAX_KEYS) return null;
    const clean = sanitizePropValue(v, depth);
    if (clean !== undefined) out[key] = clean;
  }
  return out;
}

function sanitizePropValue(v: unknown, depth: number): unknown {
  if (typeof v === 'boolean' || isNum(v)) return v;
  if (typeof v === 'string') return v.length <= MAX_STRING ? v : undefined;
  if (Array.isArray(v)) {
    if (v.length > MAX_ARRAY || depth + 1 >= MAX_PROPS_DEPTH) return undefined;
    const out: unknown[] = [];
    for (const item of v) {
      const clean = sanitizePropValue(item, depth + 1);
      if (clean === undefined) return undefined;
      out.push(clean);
    }
    return out;
  }
  if (isRecord(v)) {
    if (depth + 1 >= MAX_PROPS_DEPTH) return undefined;
    return sanitizeProps(v, depth + 1) ?? undefined;
  }
  return undefined;
}

/**
 * The interval range, all or nothing like the rest of an entry: a bound that
 * was written and cannot be read, or a range naming none, refuses the paste.
 */
function sanitizeIntervals(value: unknown): DrawingIntervalRange | null {
  const range = readIntervalRange(value);
  if (range === null || !isRecord(value)) return null;
  const kept = (key: 'from' | 'to'): boolean => (value[key] === undefined) === (range[key] === undefined);
  return kept('from') && kept('to') ? range : null;
}

/**
 * Validate one entry into a drawing with no id. Returns null for anything that
 * cannot be rendered: an unknown tool would throw inside the controller, and a
 * NaN anchor produces a drawing that can never be drawn or hit-tested again.
 * Accepts the 1.9.x shape too, lifting its text fields into `text`.
 */
export function sanitizeDrawing(value: unknown): Omit<Drawing, 'id'> | null {
  if (!isRecord(value)) return null;
  if (typeof value.tool !== 'string' || value.tool === '' || value.tool.length > MAX_STRING) return null;
  if (!hasDrawingTool(value.tool)) return null;
  // A viewport entry is all-or-nothing like the rest: its tool must be able to
  // hold the space, and every anchor must be a finite fraction.
  const viewport = value.space === 'viewport' ? readViewportPoints(value.viewportPoints, MAX_POINTS) : undefined;
  if (viewport === null || (viewport !== undefined && !viewportDrawingTool(value.tool))) return null;
  const points = viewport === undefined ? readPoints(value.points, MAX_POINTS) : [];
  if (points === null) return null;
  const style = sanitizeStyle(value.style);
  if (style === null) return null;
  // An absent pane is pane zero; a bogus one is a rejection, because a drawing
  // parked on a pane that does not exist is invisible and unfindable.
  const paneIndex = value.paneIndex === undefined ? 0 : value.paneIndex;
  if (!isNum(paneIndex) || paneIndex < 0 || !Number.isInteger(paneIndex)) return null;
  if (value.locked !== undefined && typeof value.locked !== 'boolean') return null;
  if (value.visible !== undefined && typeof value.visible !== 'boolean') return null;
  const intervals = value.intervals === undefined ? undefined : sanitizeIntervals(value.intervals);
  if (intervals === null) return null;
  // A text block on the entry wins; the old style-bag keys only fill the gap.
  const text = sanitizeText(value.text) ?? (isRecord(value.style) ? liftLegacyText(value.style) : null);
  const props = value.props === undefined ? null : sanitizeProps(value.props);
  const out: Omit<Drawing, 'id'> = {
    tool: value.tool,
    points,
    ...(viewport === undefined ? {} : { space: 'viewport' as const, viewportPoints: viewport }),
    style,
    paneIndex,
    zIndex: isNum(value.zIndex) ? value.zIndex : 0,
  };
  if (text !== null) out.text = text;
  if (props !== null) out.props = props;
  if (value.locked !== undefined) out.locked = value.locked;
  if (value.visible !== undefined) out.visible = value.visible;
  if (intervals !== undefined) out.intervals = intervals;
  if (isShortString(value.stackAbove) && value.stackAbove !== '') out.stackAbove = value.stackAbove;
  if (isNum(value.createdAt)) out.createdAt = value.createdAt;
  return out;
}

/**
 * Parse clipboard text into drawings, or null when the text is not ours or is
 * not usable. All-or-nothing on purpose: a payload with one corrupt entry is a
 * corrupt payload, and pasting the other nine silently would be worse than
 * pasting none.
 */
export function decodeClipboardPayload(text: unknown): Omit<Drawing, 'id'>[] | null {
  if (typeof text !== 'string' || text.length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;                       // plain text from somewhere else
  }
  if (!isRecord(parsed)) return null;
  const body = parsed[DRAWING_CLIPBOARD_KEY];
  if (!isRecord(body)) return null;    // valid JSON, but not ours
  // A payload from a future version may carry fields this build cannot honour,
  // so refuse it rather than paste a half-understood drawing. Older versions
  // are accepted: they go through the same upgrade a saved layout does.
  if (!isNum(body.version) || body.version < 1 || body.version > DRAWING_CLIPBOARD_VERSION) return null;
  const list = body.drawings;
  if (!Array.isArray(list) || list.length === 0 || list.length > MAX_DRAWINGS) return null;
  // The gate runs on the raw entries first. The migration keeps any drawing it
  // can render and merely drops a corrupt optional field, which is right for a
  // saved layout and wrong for a paste, where one bad field refuses the lot.
  for (const entry of list) {
    if (sanitizeDrawing(entry) === null) return null;
  }
  // What passed takes the same upgrade a saved layout does (level colours,
  // lifted text), then the caps above apply to the result. A shorter result
  // is the migration refusing something the gate let through.
  const upgraded = migrateDrawings(list).drawings;
  if (upgraded.length !== list.length) return null;
  const out: Omit<Drawing, 'id'>[] = [];
  for (const entry of upgraded) {
    const d = sanitizeDrawing(entry);
    if (d === null) return null;
    out.push(d);
  }
  return out;
}

export interface DrawingClipboardOptions {
  /** Where to read and write. Defaults to `navigator.clipboard` when present. */
  port?: ClipboardPort | null;
  /**
   * Keep a copy in the shared in-memory clipboard so copy and paste keep
   * working when the OS clipboard is unavailable or the permission is refused.
   * Default true. Set false to make a failed system write a failed copy, which
   * a host that must not silently lose cross-tab transfer may prefer.
   */
  fallbackToMemory?: boolean;
}

/**
 * The clipboard as the controller sees it: drawings in, drawings out, no
 * exceptions escaping. Every failure mode (no clipboard API, refused
 * permission, foreign text, corrupt payload) reduces to `false` or `null`.
 */
export class DrawingClipboard {
  private _port: ClipboardPort | null;
  private _fallback: boolean;
  /** Why the last operation did not reach the OS clipboard, if it did not. */
  private _lastError: string | null = null;

  public constructor(options: DrawingClipboardOptions = {}) {
    this._port = options.port === undefined ? systemClipboard() : options.port;
    this._fallback = options.fallbackToMemory ?? true;
  }

  /** Swap the port at runtime (a host granting permission later, or a test). */
  public setPort(port: ClipboardPort | null): void {
    this._port = port;
  }

  /**
   * Turn the in-memory backstop off or on. With it off, a refused system write
   * is a failed copy, which is what a host wants when a cut that cannot reach
   * the OS clipboard must not delete the drawing.
   */
  public setFallbackToMemory(enabled: boolean): void {
    this._fallback = enabled;
  }

  /**
   * Why the OS clipboard was not used by the last call, or null when it was.
   * Set on a successful copy too, when the payload reached memory but not the
   * system clipboard: that copy works in this tab and will not appear in
   * another, which is exactly what a host wants to be able to tell the user.
   */
  public lastError(): string | null {
    return this._lastError;
  }

  /**
   * Write drawings out. Resolves true when the payload is retrievable by a
   * later `read()` (through the system clipboard, or through memory when the
   * fallback is on), false when it is not, so a caller doing a cut knows
   * whether it is safe to delete the original.
   */
  public async write(drawings: readonly Drawing[]): Promise<boolean> {
    if (drawings.length === 0) return false;
    let text: string;
    try {
      text = encodeClipboardPayload(drawings);
    } catch (e) {
      this._lastError = String(e);
      return false;
    }
    this._lastError = null;
    let systemOk = false;
    if (this._port !== null) {
      try {
        await this._port.writeText(text);
        systemOk = true;
      } catch (e) {
        this._lastError = String(e);   // typically a refused permission
      }
    } else {
      this._lastError = 'openalgo-charts: no system clipboard available';
    }
    if (this._fallback) {
      memoryText = text;
      return true;
    }
    return systemOk;
  }

  /**
   * Read drawings back, or null when there is nothing of ours to paste. The
   * system clipboard wins when it holds our payload, so a copy made in another
   * tab beats a stale in-tab one; memory is consulted when the read fails or
   * returns something that is not ours. That last case can paste an older copy
   * after the user has copied unrelated text elsewhere, which is the deliberate
   * trade: losing the copy whenever a browser refuses the read half of the
   * permission would be the worse surprise.
   */
  public async read(): Promise<Omit<Drawing, 'id'>[] | null> {
    this._lastError = null;
    if (this._port !== null) {
      try {
        const decoded = decodeClipboardPayload(await this._port.readText());
        if (decoded !== null) return decoded;
      } catch (e) {
        this._lastError = String(e);
      }
    }
    if (!this._fallback) return null;
    return decodeClipboardPayload(memoryText);
  }
}
