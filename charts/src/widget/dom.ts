/**
 * The widget's small DOM kit: element and glyph factories, the focus rules
 * the overlay stack and the keymap share, and the placement maths that puts
 * a panel beside, below or over its anchor inside the widget. No state, and
 * nothing of the widget's own: the leaf the rest of the chrome builds on.
 */

// ── small DOM helpers ───────────────────────────────────────────────────

/** HTML-escape the four characters that matter in text and attribute values. */
export const esc = (s: unknown): string =>
  String(s).replace(/[&<>"]/g, (c) => (c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&quot;'));

/** Create an element with a class and optional attributes. */
export function h<K extends keyof HTMLElementTagNameMap>(
  doc: Document, tag: K, className?: string, attrs?: Record<string, string>,
): HTMLElementTagNameMap[K] {
  const el = doc.createElement(tag);
  if (className) el.className = className;
  if (attrs) for (const [k, val] of Object.entries(attrs)) el.setAttribute(k, val);
  return el;
}

/**
 * A glyph span. The markup is a string from the draw tier's icon builders,
 * so this is the one place `innerHTML` is written, and it only ever wraps a
 * trusted `<svg>` from the registry.
 */
export function glyph(doc: Document, svg: string, kind: 'tool' | 'chrome'): HTMLSpanElement {
  const span = doc.createElement('span');
  span.className = 'oac-glyph oac-glyph--' + kind;
  span.setAttribute('aria-hidden', 'true');
  span.innerHTML = svg;
  return span;
}

/** Whether a key event came from a text control, where chords stay out of the way. */
export function inTextField(target: unknown): boolean {
  const t = target as { tagName?: string; isContentEditable?: boolean; type?: string } | null;
  if (t === null || t === undefined) return false;
  if (t.isContentEditable === true) return true;
  const tag = (t.tagName ?? '').toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  // A checkbox or a button-shaped input takes no typing.
  const type = (t.type ?? 'text').toLowerCase();
  return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color'].includes(type);
}

/** Whether `n` can take focus: a control, enabled, and not under a `hidden`. */
export function focusable(n: Element | null): n is HTMLElement {
  if (n === null) return false;
  const el = n as HTMLElement & { disabled?: boolean };
  if (el.disabled === true) return false;
  const ti = el.getAttribute('tabindex');
  if (ti !== null && Number(ti) < 0) return false;
  const tag = el.tagName;
  const natural = tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA'
    || (tag === 'A' && el.hasAttribute('href'));
  if (!natural && ti === null) return false;
  for (let p: HTMLElement | null = el; p !== null; p = p.parentElement) if (p.hidden) return false;
  return true;
}

export const focusables = (root: Element): HTMLElement[] =>
  Array.from(root.querySelectorAll('*')).filter(focusable);

export interface Box { left: number; top: number; right: number; bottom: number; width: number; height: number }
export interface Size { width: number; height: number }

/**
 * Where a panel of `size` goes beside `anchor` without leaving `bounds`: to
 * the right of it by `gap`, its top on the anchor's top, then pulled up (never
 * past `pad`) when it would run off the bottom, and flipped to the left only
 * when the right has no room at all. Coordinates are in whatever space the
 * anchor and the bounds share.
 */
export function placeBeside(anchor: Box, size: Size, bounds: Size, gap = 6, pad = 8): { left: number; top: number; side: 'left' | 'right' } {
  let left = anchor.right + gap;
  let side: 'left' | 'right' = 'right';
  if (left + size.width > bounds.width - pad && anchor.left - gap - size.width >= pad) {
    left = anchor.left - gap - size.width;
    side = 'left';
  }
  left = Math.max(pad, Math.min(left, bounds.width - size.width - pad));
  const top = Math.max(pad, Math.min(anchor.top, bounds.height - size.height - pad));
  return { left, top, side };
}

/** A panel under `anchor`, left-aligned with it, flipped above when there is no room below. */
export function placeBelow(anchor: Box, size: Size, bounds: Size, gap = 4, pad = 8): { left: number; top: number } {
  let top = anchor.bottom + gap;
  if (top + size.height > bounds.height - pad && anchor.top - gap - size.height >= pad) {
    top = anchor.top - gap - size.height;
  }
  return {
    left: Math.max(pad, Math.min(anchor.left, bounds.width - size.width - pad)),
    top: Math.max(pad, Math.min(top, bounds.height - size.height - pad)),
  };
}

export type TipSide = 'right' | 'left' | 'top' | 'bottom';

/** A tip centred on the anchor's edge, flipped across it when its side has no room. */
export function placeTip(anchor: Box, size: Size, bounds: Size, side: TipSide = 'right', gap = 8, pad = 6): { left: number; top: number } {
  let x: number;
  let y: number;
  if (side === 'right' || side === 'left') {
    const wantRight = side === 'right';
    x = wantRight ? anchor.right + gap : anchor.left - gap - size.width;
    if (wantRight ? x + size.width > bounds.width - pad : x < pad) {
      x = wantRight ? anchor.left - gap - size.width : anchor.right + gap;
    }
    y = anchor.top + anchor.height / 2 - size.height / 2;
  } else {
    const wantBelow = side !== 'top';
    y = wantBelow ? anchor.bottom + gap : anchor.top - gap - size.height;
    if (wantBelow ? y + size.height > bounds.height - pad : y < pad) {
      y = wantBelow ? anchor.top - gap - size.height : anchor.bottom + gap;
    }
    x = anchor.left + anchor.width / 2 - size.width / 2;
  }
  return {
    left: Math.max(pad, Math.min(x, bounds.width - size.width - pad)),
    top: Math.max(pad, Math.min(y, bounds.height - size.height - pad)),
  };
}

/** An element's box in the coordinate space of `root` (the widget), not the viewport. */
export function boxIn(root: HTMLElement, el: Element): Box {
  const r = root.getBoundingClientRect();
  const b = el.getBoundingClientRect();
  return {
    left: b.left - r.left, top: b.top - r.top, right: b.right - r.left, bottom: b.bottom - r.top,
    width: b.width, height: b.height,
  };
}
