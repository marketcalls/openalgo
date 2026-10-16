/**
 * Inline text editing for a drawing: a contentEditable box laid over the
 * painted text so its frame coincides with the frame on the canvas. The
 * engine draws text on canvas and ships no DOM, so there is no node to edit
 * in place; this one is the widget's, sized by the same rules the text tool
 * paints with: a 5px pad, a 1.35 line gap, a soft wrap at `wrapWidth`, and
 * the anchor on the top, middle or bottom edge.
 *
 * Commit on blur or Ctrl+Enter, cancel on Escape. Every pointer and key
 * event stops at the box, or the chart under it would take the press as a
 * pan and the widget's chords would read a Backspace as "delete the drawing".
 */
import { widgetText } from '../localization';
import { drawingSettingsSchema } from 'openalgo-charts/draw';
import type { Drawing, DrawingText } from 'openalgo-charts/draw';
import type { Chart } from 'openalgo-charts';
import { boxIn, drawingToolOf, type WidgetContext } from '../context';
import { declinedPanel, el, openPanel, type PanelHandle } from '../form';

export interface TextEditorOptions {
  /** The drawing to edit. Default: the one selected drawing. */
  id?: string;
  /** Runs once after the box is gone; `committed` is true when the text changed. */
  onDone?(committed: boolean): void;
}

export interface TextEditorHandle extends PanelHandle {
  commit(): void;
  cancel(): void;
}

/** The stack the draw tier falls back to when a text block sets no family. */
const DEFAULT_FONT = 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
export const TEXT_PAD = 5;
const LINE_GAP = 1.35;
const TEXT_SIZE = 14;
const WRAP_WIDTH = 220;

type TextLike = Partial<DrawingText>;

/** The CSS font shorthand the draw tier builds for a text block, at `sizePx`. */
function fontOf(t: TextLike, sizePx: number): string {
  const w = t.bold === true ? '700 ' : '';
  const italic = t.italic === true ? 'italic ' : '';
  const family = t.fontFamily === undefined || t.fontFamily === '' ? DEFAULT_FONT : t.fontFamily;
  return `${italic}${w}${sizePx}px ${family}`;
}

/**
 * The lines the tier paints: explicit newlines always, and each paragraph
 * soft-wrapped at `maxWidth` when the block asks for it. `measure` returns
 * the width of a string in the font in force.
 */
function wrapLines(measure: (s: string) => number, t: TextLike, value: string, maxWidth: number): string[] {
  const paragraphs = value.split('\n');
  if (t.wrap !== true) return paragraphs;
  const out: string[] = [];
  for (const para of paragraphs) {
    const words = para.split(/\s+/).filter((w) => w !== '');
    if (words.length === 0) { out.push(''); continue; }
    let line = words[0]!; // not empty, checked above; i below stays inside words
    for (let i = 1; i < words.length; i++) {
      const next = `${line} ${words[i]}`;
      if (measure(next) > maxWidth) { out.push(line); line = words[i]!; }
      else line = next;
    }
    out.push(line);
  }
  return out;
}

/**
 * A width function for `font`: a scratch 2D context where one exists, else
 * the 0.6em-per-character estimate the tier's own hit test falls back to.
 */
function measurer(doc: Document, font: string, size: number): (s: string) => number {
  let ctx: CanvasRenderingContext2D | null = null;
  try {
    const canvas = doc.createElement('canvas');
    ctx = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
  } catch { ctx = null; }
  if (ctx !== null && typeof ctx.measureText === 'function') {
    ctx.font = font;
    const c = ctx;
    return (s) => c.measureText(s).width;
  }
  return (s) => s.length * size * 0.6;
}

interface TextFrame {
  x: number;
  y: number;
  width: number;
  height: number;
  lineHeight: number;
  lines: string[];
  font: string;
  size: number;
}

/**
 * Where the text tool paints `d`, in the chart container's media px: the
 * box's top-left, its size, and the typesetting it used. `fallback` is what
 * the tool prints for an empty value (the text tool says "Text"), because
 * that is the frame actually on screen. Null when an anchor is off the pane.
 * `at` is the anchor in the same container px when the caller already has
 * it, which a drawing pinned to the viewport needs: its position is not a
 * time and a price the chart could map.
 */
export function textFrame(
  chart: Pick<Chart, 'timeToCoordinate' | 'priceToCoordinate'>, d: Drawing, measure: (s: string) => number, fallback = 'Text',
  at?: { x: number; y: number } | null,
): TextFrame | null {
  const p = d.points[0];
  const anchor = at ?? (p === undefined ? null : { x: chart.timeToCoordinate(p.time), y: chart.priceToCoordinate(p.price, d.paneIndex) });
  if (anchor === null) return null;
  const { x, y } = anchor;
  if (!Number.isFinite(x) || y === null || !Number.isFinite(y)) return null;
  const t: TextLike = d.text ?? { value: '' };
  const size = t.fontSize ?? TEXT_SIZE;
  const font = fontOf(t, size);
  const value = t.value === undefined || t.value === '' ? fallback : t.value;
  const lines = wrapLines(measure, t, value, t.wrapWidth ?? WRAP_WIDTH);
  let width = 0;
  for (const l of lines) width = Math.max(width, measure(l));
  const lineHeight = size * LINE_GAP;
  const height = lines.length * lineHeight + TEXT_PAD * 2;
  const v = t.valign ?? 'top';
  const top = v === 'middle' ? y - height / 2 : v === 'bottom' ? y - height : y;
  return { x, y: top, width: width + TEXT_PAD * 2, height, lineHeight, lines, font, size };
}

/**
 * The text in a contentEditable, with the browser's line structure folded
 * back to newlines: a `<br>` is one, and a `<div>` or `<p>` the browser
 * opened for a new line starts on one. The placeholder `<br>` a browser
 * leaves at the very end is not a line the user typed.
 */
export function readEditable(node: Node): string {
  let out = '';
  let lastBr = false;
  const walk = (n: Node): void => {
    for (const c of Array.from(n.childNodes ?? [])) {
      if (c.nodeType === 3) { out += c.nodeValue ?? ''; lastBr = false; continue; }
      if (c.nodeType !== 1) continue;
      const tag = String(c.nodeName).toUpperCase();
      if (tag === 'BR') { out += '\n'; lastBr = true; continue; }
      if ((tag === 'DIV' || tag === 'P') && out !== '' && !out.endsWith('\n')) out += '\n';
      lastBr = false;
      walk(c);
    }
  };
  walk(node);
  return lastBr ? out.slice(0, -1) : out;
}

/** The element the chart's panes sit in, which is where its coordinates are measured from. */
export function chartContainer(chart: Chart): HTMLElement | null {
  return chart.panes()[0]?.element.parentElement ?? null;
}

/** Whether a drawing's text is the drawing (the text tool, a note), rather than a label on a shape. */
export function isTextContent(d: Drawing | undefined): d is Drawing {
  return d !== undefined && drawingSettingsSchema(d.tool).textIsContent === true;
}

function declined(ctx: WidgetContext, why: string, onDone?: (committed: boolean) => void): TextEditorHandle {
  const handle = declinedPanel(ctx, why);
  onDone?.(false);
  return { ...handle, commit: () => {}, cancel: () => {} };
}

/**
 * Open the editor over the drawing. `anchor` is accepted for the registry's
 * uniform signature and not used: the box sits where the text is painted.
 */
export function mountTextEditor(ctx: WidgetContext, _anchor?: HTMLElement, opts: TextEditorOptions = {}): TextEditorHandle {
  const doc = ctx.document;
  const { chart, draw } = ctx;
  const sel = draw.selection();
  const id = opts.id ?? (sel.length === 1 ? sel[0] : undefined);
  const d = id === undefined ? undefined : draw.get(id);
  if (!isTextContent(d)) return declined(ctx, widgetText(ctx, 'Select a text drawing first'), opts.onDone);
  // A box whose commit the controller would refuse is not offered.
  if (d.policy?.editable === false) return declined(ctx, widgetText(ctx, 'read-only'), opts.onDone);
  const tool = drawingToolOf(d.tool);
  const fallback = tool?.defaultText?.value !== undefined && tool.defaultText.value !== '' ? tool.defaultText.value : widgetText(ctx, 'Text');
  const t: TextLike = d.text ?? { value: '' };
  const size = t.fontSize ?? TEXT_SIZE;
  const font = fontOf(t, size);
  const measure = measurer(doc, font, size);
  // A pinned note has no time and price to map; the controller knows where it is.
  const frame = textFrame(chart, d, measure, fallback, d.space === 'viewport' ? draw.screenPoints(d.id)?.[0] ?? null : undefined);
  const container = chartContainer(chart);
  if (frame === null || container === null) return declined(ctx, widgetText(ctx, 'That text is off the chart'), opts.onDone);

  // Chart coordinates are relative to the chart container; the box lives in
  // the overlay layer, which spans the widget root, and the chart starts
  // further right when the rail is up.
  const off = boxIn(ctx.root, container);

  const box = el(doc, 'div', 'oac-textedit');
  box.setAttribute('contenteditable', 'plaintext-only');
  box.setAttribute('spellcheck', 'false');
  box.setAttribute('role', 'textbox');
  box.setAttribute('aria-multiline', 'true');
  box.setAttribute('aria-label', widgetText(ctx, 'Drawing text'));
  box.tabIndex = 0;
  const s = box.style;
  s.left = `${Math.round(frame.x + off.left)}px`;
  s.top = `${Math.round(frame.y + off.top)}px`;
  s.font = font;
  s.lineHeight = `${frame.lineHeight}px`;
  s.color = t.color ?? d.style.color ?? 'inherit';
  s.textAlign = t.align ?? 'left';
  s.minWidth = `${Math.ceil(frame.width)}px`;
  s.minHeight = `${Math.ceil(frame.height)}px`;
  const wrapping = t.wrap === true;
  const maxWidth = t.wrapWidth ?? WRAP_WIDTH;
  // Wrapping is a fixed width the canvas breaks lines at; unwrapped text
  // makes the box as wide as its longest line, the same as the plate.
  s.whiteSpace = wrapping ? 'pre-wrap' : 'pre';
  if (wrapping) s.width = `${Math.ceil(frame.width)}px`;
  const original = t.value ?? '';
  box.textContent = original;

  let settled = false;
  const settle = (committed: boolean): void => {
    if (settled) return;
    settled = true;
    handle.close();
    opts.onDone?.(committed);
  };
  const commit = (): void => {
    if (settled) return;
    const value = readEditable(box);
    const changed = value !== original;
    if (changed && draw.get(d.id) !== undefined) draw.update(d.id, { text: { ...(draw.get(d.id)?.text ?? { value: '' }), value } });
    settle(changed);
  };
  const cancel = (): void => settle(false);

  // The chart's pointer capture and the widget's chords both live outside
  // this box; nothing that happens inside it is theirs.
  for (const ev of ['pointerdown', 'pointermove', 'pointerup', 'click', 'dblclick', 'contextmenu', 'keyup', 'keypress']) {
    box.addEventListener(ev, (e) => { e.stopPropagation(); });
  }
  box.addEventListener('keydown', (e) => {
    const k = (e as KeyboardEvent).key;
    if (k !== 'Tab') e.stopPropagation();
    if (k === 'Escape') { e.preventDefault(); cancel(); return; }
    if (k === 'Enter' && ((e as KeyboardEvent).ctrlKey || (e as KeyboardEvent).metaKey)) { e.preventDefault(); commit(); }
  });
  box.addEventListener('blur', () => commit());
  if (wrapping) {
    // The plate is as wide as its longest wrapped line, so the box follows
    // the text rather than sitting at the full wrap width.
    box.addEventListener('input', () => {
      const lines = wrapLines(measure, t, readEditable(box) || fallback, maxWidth);
      let w = 0;
      for (const l of lines) w = Math.max(w, measure(l));
      s.width = `${Math.ceil(w + TEXT_PAD * 2)}px`;
    });
  }

  // Not dismissed by an outside press: the press blurs the box, and blur is
  // the commit. Escape through the stack is the cancel.
  const handle = openPanel(ctx, box, { placement: 'below', modal: false, dismissOnOutside: false, initialFocus: box }, cancel);

  // Caret at the end: a click on the text is how the edit began, and the
  // usual next keystroke continues it.
  try {
    const win = doc.defaultView;
    if (win !== null && typeof win.getSelection === 'function' && typeof doc.createRange === 'function') {
      const range = doc.createRange();
      range.selectNodeContents(box);
      range.collapse(false);
      const selection = win.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    }
  } catch { /* a selection is a convenience, not the edit */ }

  return { el: box, isOpen: handle.isOpen, close: () => commit(), commit, cancel };
}
