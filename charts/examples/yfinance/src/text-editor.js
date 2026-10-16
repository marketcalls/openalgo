// Inline text editing for a drawing: a contentEditable box laid over the
// painted text so its frame coincides with the frame on the canvas. The
// engine draws text on canvas and ships no DOM, so there is no node to edit
// in place; this one is the host's, sized by the same rules the text tool
// paints with (`textBox` in the draw tier): a 5px pad, a 1.35 line gap, a
// soft wrap at `wrapWidth`, and the anchor on the top, middle or bottom edge.
//
// The drawing stays painted underneath at reduced alpha (the box has a
// translucent chart-coloured back) until the edit lands, so the user sees
// the old text dim behind the new. Commit on blur or Ctrl+Enter, cancel on
// Escape; every pointer and key event stops at the box, or the chart under
// it would take the press as a pan and the page's chords would read a
// Backspace as "delete the drawing".

/** The stack the draw tier falls back to when a text block sets no family. */
export const DEFAULT_FONT = 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
export const TEXT_PAD = 5;
export const LINE_GAP = 1.35;
export const TEXT_SIZE = 14;
export const WRAP_WIDTH = 220;

/** The stylesheet the editor needs; properties.js injects it with its own. */
export const EDITOR_CSS = `
.draw-textedit { position: absolute; z-index: 45; box-sizing: border-box; margin: 0; outline: none;
  padding: ${TEXT_PAD - 1}px; border: 1px solid var(--acc); border-radius: 4px;
  background: color-mix(in srgb, var(--bg) 58%, transparent); box-shadow: 0 0 0 3px var(--ring-soft, rgba(34,193,164,.15));
  caret-color: var(--acc-2); cursor: text; overflow: hidden; }
`;

/** The CSS font shorthand the draw tier builds for a text block, at `sizePx`. */
export function fontOf(t, sizePx) {
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
export function wrapLines(measure, t, value, maxWidth) {
  const paragraphs = value.split('\n');
  if (t.wrap !== true) return paragraphs;
  const out = [];
  for (const para of paragraphs) {
    const words = para.split(/\s+/).filter((w) => w !== '');
    if (words.length === 0) { out.push(''); continue; }
    let line = words[0];
    for (let i = 1; i < words.length; i++) {
      const next = `${line} ${words[i]}`;
      if (measure(next) > maxWidth) { out.push(line); line = words[i]; }
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
export function measurer(font, size) {
  let ctx = null;
  try {
    const canvas = typeof document !== 'undefined' && document.createElement ? document.createElement('canvas') : null;
    ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
  } catch (_) { ctx = null; }
  if (ctx && typeof ctx.measureText === 'function') {
    ctx.font = font;
    return (s) => ctx.measureText(s).width;
  }
  return (s) => s.length * size * 0.6;
}

/**
 * Where the text tool paints `d`, in the chart container's media px: the
 * box's top-left, its size, and the typesetting it used. `fallback` is what
 * the tool prints for an empty value (the text tool says "Text"), because
 * that is the frame actually on screen. Null when an anchor is off the pane.
 * `at` is the anchor in the same container px when the caller has it: a note
 * pinned to the screen has no time and price the chart could map.
 */
export function textFrame(chart, d, measure, fallback = 'Text', at = null) {
  const p = d.points && d.points[0];
  const anchor = at || (p ? { x: chart.timeToCoordinate(p.time), y: chart.priceToCoordinate(p.price, d.paneIndex) } : null);
  if (!anchor) return null;
  const { x, y } = anchor;
  if (!Number.isFinite(x) || y === null || !Number.isFinite(y)) return null;
  const t = d.text || { value: '' };
  const size = t.fontSize === undefined ? TEXT_SIZE : t.fontSize;
  const font = fontOf(t, size);
  const value = t.value === undefined || t.value === '' ? fallback : t.value;
  const lines = wrapLines(measure, t, value, t.wrapWidth === undefined ? WRAP_WIDTH : t.wrapWidth);
  let width = 0;
  for (const l of lines) width = Math.max(width, measure(l));
  const lineHeight = size * LINE_GAP;
  const height = lines.length * lineHeight + TEXT_PAD * 2;
  const v = t.valign || 'top';
  const top = v === 'middle' ? y - height / 2 : v === 'bottom' ? y - height : y;
  return { x, y: top, width: width + TEXT_PAD * 2, height, lineHeight, lines, font, size };
}

/**
 * The text in a contentEditable, with the browser's line structure folded
 * back to newlines: a `<br>` is one, and a `<div>` or `<p>` the browser
 * opened for a new line starts on one. The placeholder `<br>` a browser
 * leaves at the very end is not a line the user typed.
 */
export function readEditable(node) {
  let out = '';
  let lastBr = false;
  const walk = (n) => {
    for (const c of n.childNodes || []) {
      if (c.nodeType === 3) { out += c.nodeValue || ''; lastBr = false; continue; }
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

/**
 * Open the editor for drawing `id` inside `host` (the positioned element the
 * chart container `chartEl` sits in). `fallback` is the tool's own empty-text
 * stand-in. Returns the handle, or null when the drawing has no frame on
 * screen. `onDone(committed)` runs once, after the box is gone.
 */
export function openTextEditor({ app, id, host, chartEl, fallback = 'Text', onDone }) {
  const d = app.draw ? app.draw.get(id) : undefined;
  if (!d || !app.chart) return null;
  const t = d.text || { value: '' };
  const size = t.fontSize === undefined ? TEXT_SIZE : t.fontSize;
  const font = fontOf(t, size);
  const measure = measurer(font, size);
  // The controller places a pinned note; a note on time and price the chart does.
  const pinned = d.space === 'viewport' && typeof app.draw.screenPoints === 'function' ? app.draw.screenPoints(id) : null;
  if (d.space === 'viewport' && !pinned) return null;
  const frame = textFrame(app.chart, d, measure, fallback, pinned ? pinned[0] : null);
  if (!frame) return null;

  // Chart coordinates are relative to the chart container; the box lives in
  // the host, which starts further right when the rail is up.
  const hr = host.getBoundingClientRect();
  const cr = chartEl.getBoundingClientRect();
  const dx = cr.left - hr.left;
  const dy = cr.top - hr.top;

  const box = document.createElement('div');
  box.className = 'draw-textedit';
  box.setAttribute('contenteditable', 'plaintext-only');
  box.setAttribute('spellcheck', 'false');
  box.setAttribute('role', 'textbox');
  box.setAttribute('aria-label', 'Drawing text');
  const s = box.style;
  s.left = Math.round(frame.x + dx) + 'px';
  s.top = Math.round(frame.y + dy) + 'px';
  s.font = font;
  s.lineHeight = frame.lineHeight + 'px';
  s.color = t.color || d.style.color || '#d7dce8';
  s.textAlign = t.align || 'left';
  s.minWidth = Math.ceil(frame.width) + 'px';
  s.minHeight = Math.ceil(frame.height) + 'px';
  const wrapping = t.wrap === true;
  const maxWidth = t.wrapWidth === undefined ? WRAP_WIDTH : t.wrapWidth;
  // Wrapping is a fixed width the canvas breaks lines at; unwrapped text
  // makes the box as wide as its longest line, the same as the plate.
  s.whiteSpace = wrapping ? 'pre-wrap' : 'pre';
  if (wrapping) s.width = Math.ceil(frame.width) + 'px';
  const original = t.value === undefined ? '' : t.value;
  box.textContent = original;

  let closed = false;
  const close = (committed) => {
    if (closed) return;
    closed = true;
    box.remove();
    if (onDone) onDone(committed);
  };
  const commit = () => {
    if (closed) return;
    const value = readEditable(box);
    const changed = value !== original;
    if (changed && app.draw && app.draw.get(id)) app.draw.update(id, { text: { value } });
    close(changed);
  };
  const cancel = () => close(false);

  // The chart's pointer capture and the page's chords both live outside
  // this box; nothing that happens inside it is theirs.
  for (const ev of ['pointerdown', 'pointermove', 'pointerup', 'click', 'dblclick', 'contextmenu', 'keyup', 'keypress']) {
    box.addEventListener(ev, (e) => { e.stopPropagation(); });
  }
  box.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); cancel(); return; }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); commit(); }
  });
  box.addEventListener('blur', commit);
  if (wrapping) {
    // The plate is as wide as its longest wrapped line, so the box follows
    // the text rather than sitting at the full wrap width.
    box.addEventListener('input', () => {
      const lines = wrapLines(measure, t, readEditable(box) || fallback, maxWidth);
      let w = 0;
      for (const l of lines) w = Math.max(w, measure(l));
      s.width = Math.ceil(w + TEXT_PAD * 2) + 'px';
    });
  }

  host.appendChild(box);
  if (typeof box.focus === 'function') box.focus();
  // Caret at the end: a click on the text is how the edit began, and the
  // usual next keystroke continues it.
  try {
    if (typeof window !== 'undefined' && window.getSelection && document.createRange) {
      const range = document.createRange();
      range.selectNodeContents(box);
      range.collapse(false);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
  } catch (_) { /* a selection is a convenience, not the edit */ }

  return { el: box, id, frame, commit, cancel, isOpen: () => !closed };
}
