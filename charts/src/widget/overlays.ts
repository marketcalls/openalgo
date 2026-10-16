/**
 * What sits over the widget: the overlay stack, which knows what is open and
 * so owns Escape, the focus trap, the outside press and where focus goes
 * back, and the tooltip every control's hover label shares.
 */
import { boxIn, focusables, h, placeBelow, placeBeside, placeTip, type TipSide } from './dom';

// ── overlay stack ──────────────────────────────────────────────────────

export interface OverlayOptions {
  /** The control the panel opens from; positions the panel and keeps a click on it from counting as outside. */
  anchor?: HTMLElement | undefined;
  /** Where the panel goes relative to the anchor. Default `below`; `center` ignores the anchor. */
  placement?: 'below' | 'beside' | 'center';
  /** A second element the panel should clear when placed beside (the rail, not just the button in it). */
  edge?: HTMLElement | undefined;
  /** Draw a scrim and refuse outside dismissal. Default false; `center` placement implies it. */
  modal?: boolean;
  /** Where focus lands: an element, `null` to leave focus where it is, or the first control (default). */
  initialFocus?: HTMLElement | null | undefined;
  /** Close on a press outside the panel and its anchor. Default: not modal. */
  dismissOnOutside?: boolean;
  /** Close on Escape. Default true. */
  dismissOnEscape?: boolean;
  /** Give focus back to the opener on close. Default true. */
  restoreFocus?: boolean;
  onClose?: () => void;
}

interface OverlayEntry {
  el: HTMLElement;
  opts: OverlayOptions;
  scrim: HTMLElement | null;
  restore: HTMLElement | null;
  closed: boolean;
  suspended: number;
  suspension?: { hidden: boolean; scrimHidden: boolean; focus: HTMLElement | null } | undefined;
}

export interface OverlayStack {
  open(el: HTMLElement, opts?: OverlayOptions): () => void;
  /** Close the newest overlay. False when nothing is open. */
  closeTop(): boolean;
  closeAll(): void;
  top(): HTMLElement | null;
  size(): number;
  /** Hide one overlay and its scrim without closing its session. Returns an idempotent resume. */
  suspend?(el: HTMLElement): () => void;
  /** The layer element overlays are appended to. */
  readonly layer: HTMLElement;
  destroy(): void;
}

/**
 * One stack per widget. Each module opens and closes its own panel; what none
 * of them can know is what else is open. The stack knows: Escape closes only
 * the newest thing, Tab stays inside it, a press outside closes a popover but
 * not a dialog, and focus goes back where it came from.
 */
export function createOverlayStack(root: HTMLElement, doc: Document): OverlayStack {
  const layer = h(doc, 'div', 'oac-layer');
  root.appendChild(layer);
  const stack: OverlayEntry[] = [];
  const visibleTop = (): OverlayEntry | undefined => [...stack].reverse().find(entry => entry.suspended === 0);

  const close = (entry: OverlayEntry): void => {
    if (entry.closed) return;
    entry.closed = true;
    const i = stack.indexOf(entry);
    if (i >= 0) stack.splice(i, 1);
    const active = doc.activeElement as HTMLElement | null;
    const inside = active !== null && entry.el.contains(active);
    entry.el.remove();
    entry.scrim?.remove();
    entry.opts.anchor?.setAttribute('aria-expanded', 'false');
    // Only when focus was still in the overlay, or was lost with it: a click
    // that opened something else has already decided where focus goes next.
    const lost = active === null || active === doc.body || inside;
    if (entry.opts.restoreFocus !== false && lost && entry.restore !== null && entry.restore.isConnected) {
      entry.restore.focus();
    }
    entry.opts.onClose?.();
    if (stack.length === 0) unlisten();
  };

  const onKey = (e: KeyboardEvent): void => {
    const top = visibleTop();
    if (top === undefined) return;
    if (e.key === 'Escape') {
      if (top.opts.dismissOnEscape === false) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      close(top);
      return;
    }
    if (e.key !== 'Tab') return;
    const f = focusables(top.el);
    if (f.length === 0) { e.preventDefault(); return; }
    const at = f.indexOf(doc.activeElement as HTMLElement);
    // Outside the overlay (index -1) or past either end wraps; anywhere else
    // the browser's own move stays inside and is left alone.
    let next: number | null = null;
    if (e.shiftKey) { if (at <= 0) next = f.length - 1; } else if (at === -1 || at >= f.length - 1) next = 0;
    if (next !== null) { e.preventDefault(); f[next]!.focus(); } // f is not empty, and next is its first or last
  };

  const onPointerDown = (e: Event): void => {
    const target = e.target as Node | null;
    // Newest first: an outside press closes every popover above the one it
    // landed in, and stops at a modal. An onClose may close older overlays
    // too, which leaves i past the end of the stack.
    for (let i = stack.length - 1; i >= 0; i--) {
      const o = stack[i];
      if (o === undefined || o.suspended > 0) continue;
      if (target !== null && (o.el.contains(target) || o.opts.anchor?.contains(target) === true)) break;
      if (o.opts.dismissOnOutside === false || (o.opts.modal === true && o.opts.dismissOnOutside !== true)) break;
      close(o);
    }
  };

  let listening = false;
  const listen = (): void => {
    if (listening) return;
    listening = true;
    doc.addEventListener('keydown', onKey as EventListener, true);
    doc.addEventListener('pointerdown', onPointerDown, true);
  };
  const unlisten = (): void => {
    if (!listening) return;
    listening = false;
    doc.removeEventListener('keydown', onKey as EventListener, true);
    doc.removeEventListener('pointerdown', onPointerDown, true);
  };

  const open = (el: HTMLElement, opts: OverlayOptions = {}): (() => void) => {
    const placement = opts.placement ?? (opts.anchor ? 'below' : 'center');
    const modal = opts.modal ?? placement === 'center';
    const active = doc.activeElement as HTMLElement | null;
    // WebKit does not focus a button on click or tap, so an overlay a tap opened
    // finds nothing focused here. Its anchor is the control that opened it, and
    // is where focus returns on close rather than nowhere.
    const restore = active !== null && active !== doc.body && !el.contains(active) ? active : opts.anchor ?? null;
    let scrim: HTMLElement | null = null;
    const entry: OverlayEntry = { el, opts: { ...opts, modal }, scrim: null, restore, closed: false, suspended: 0 };
    if (modal) {
      scrim = h(doc, 'div', 'oac-scrim');
      if (opts.dismissOnOutside === true) scrim.addEventListener('pointerdown', () => close(entry));
      layer.appendChild(scrim);
      entry.scrim = scrim;
    }
    // The chart captures the pointer on press and would start a pan under a
    // panel that let the event through.
    el.addEventListener('pointerdown', (e) => e.stopPropagation());
    if (placement === 'center') {
      el.classList.add('oac-dialog');
      if (!el.hasAttribute('role')) el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
    } else {
      el.classList.add('oac-pop');
    }
    if (!el.hasAttribute('tabindex')) el.tabIndex = -1;
    layer.appendChild(el);
    if (placement !== 'center' && opts.anchor) {
      const bounds = root.getBoundingClientRect();
      let anchorBox = boxIn(root, opts.anchor);
      if (placement === 'beside' && opts.edge) {
        const edge = boxIn(root, opts.edge);
        const right = Math.max(anchorBox.right, edge.right);
        anchorBox = { ...anchorBox, right, width: right - anchorBox.left };
      }
      const size = { width: el.offsetWidth, height: el.offsetHeight };
      const at = placement === 'beside'
        ? placeBeside(anchorBox, size, bounds)
        : placeBelow(anchorBox, size, bounds);
      el.style.left = at.left + 'px';
      el.style.top = at.top + 'px';
      opts.anchor.setAttribute('aria-expanded', 'true');
    }
    stack.push(entry);
    listen();
    if (opts.initialFocus !== null) {
      const first = opts.initialFocus ?? firstControl(el);
      (first ?? el).focus();
    }
    return () => close(entry);
  };

  return {
    open,
    suspend: (el) => {
      const entry = stack.find(item => item.el === el);
      if (!entry || entry.closed) return () => {};
      if (entry.suspended === 0) entry.suspension = { hidden: entry.el.hidden,
        scrimHidden: entry.scrim?.hidden ?? false, focus: doc.activeElement as HTMLElement | null };
      entry.suspended++;
      entry.el.hidden = true;
      if (entry.scrim) entry.scrim.hidden = true;
      let resumed = false;
      return () => {
        if (resumed) return;
        resumed = true;
        entry.suspended--;
        if (entry.closed || entry.suspended > 0) return;
        const saved = entry.suspension!;
        entry.suspension = undefined;
        entry.el.hidden = saved.hidden;
        if (entry.scrim) entry.scrim.hidden = saved.scrimHidden;
        if (!saved.hidden && saved.focus?.isConnected && entry.el.contains(saved.focus)) saved.focus.focus();
      };
    },
    closeTop: () => {
      const top = visibleTop();
      if (top === undefined) return false;
      close(top);
      return true;
    },
    closeAll: () => { for (const o of stack.slice().reverse()) close(o); },
    top: () => visibleTop()?.el ?? null,
    size: () => stack.length,
    layer,
    destroy: () => {
      for (const o of stack.slice().reverse()) close(o);
      unlisten();
      layer.remove();
    },
  };
}

/**
 * Where focus lands in a freshly opened overlay: the first control of its
 * body. A dialog's close button comes first in the markup, and landing on it
 * reads as "press Enter to leave", which is not what a dialog is for.
 */
function firstControl(node: HTMLElement): HTMLElement | null {
  const all = focusables(node);
  return all.find((n) => n.closest('.oac-dialog__head') === null) ?? all[0] ?? null;
}

// ── tooltip ────────────────────────────────────────────────────────────

export interface TipSpec {
  title: string;
  /** The accessible name, when it must say more than the title. Default: the title. Since 2.5.10. */
  label?: string | undefined;
  /** The chord, shown in monospace after the title. */
  chord?: string | undefined;
  /** A second, muted line. */
  sub?: string | undefined;
  side?: TipSide;
}

/** A spec, or a function read at show time for a control whose label follows its state. */
export type TipSource = TipSpec | (() => TipSpec | null);

export interface TipController {
  /** Give `target` a hover label. `dwellMs` delays it; 0 shows on entry. */
  attach(target: HTMLElement, spec: TipSource, dwellMs?: number): void;
  /** Re-read a control's spec into its accessible name. */
  refreshLabel(target: HTMLElement): void;
  show(target: HTMLElement): void;
  hide(): void;
  /** The control the tip is up for, or null. */
  target(): HTMLElement | null;
  destroy(): void;
}

/** How long the pointer rests on a rail control before its label appears. */
export const TIP_DWELL_MS = 600;

/**
 * One tip node per widget. A `title` waits about a second, cannot be styled
 * and cannot carry a second line, which is no use on a rail of near-identical
 * glyphs or on a bar of bare icons. Specs are read at show time, because a
 * group button stands for whichever tool was last picked from it.
 */
export function createTipController(root: HTMLElement, layer: HTMLElement, doc: Document): TipController {
  const specs = new WeakMap<HTMLElement, TipSource>();
  let node: HTMLElement | null = null;
  let timer: ReturnType<typeof setTimeout> | 0 = 0;
  let tipFor: HTMLElement | null = null;

  const read = (raw: TipSource): TipSpec | null => (typeof raw === 'function' ? raw() : raw);

  const hide = (): void => {
    if (timer !== 0) clearTimeout(timer);
    timer = 0;
    tipFor = null;
    node?.classList.remove('is-on');
  };

  const show = (target: HTMLElement): void => {
    const raw = specs.get(target);
    if (raw === undefined || !target.isConnected) return;
    const spec = read(raw);
    if (spec === null || !spec.title) { hide(); return; }
    if (typeof raw === 'function') target.setAttribute('aria-label', spec.label ?? spec.title);
    if (node === null) {
      node = h(doc, 'div', 'oac-tip', { role: 'presentation' });
    }
    if (node.parentNode !== layer) layer.appendChild(node);
    tipFor = target;
    node.textContent = '';
    node.appendChild(doc.createTextNode(spec.title));
    if (spec.chord) {
      const k = h(doc, 'kbd', 'oac-tip__chord');
      k.textContent = spec.chord;
      node.appendChild(k);
    }
    if (spec.sub) {
      const s = h(doc, 'span', 'oac-tip__sub');
      s.textContent = spec.sub;
      node.appendChild(s);
    }
    const bounds = root.getBoundingClientRect();
    const at = placeTip(boxIn(root, target), { width: node.offsetWidth, height: node.offsetHeight }, bounds, spec.side ?? 'right');
    node.style.left = at.left + 'px';
    node.style.top = at.top + 'px';
    node.classList.add('is-on');
  };

  return {
    attach: (target, spec, dwellMs = 0) => {
      specs.set(target, spec);
      const first = read(spec);
      if (first !== null && first.title && !target.getAttribute('aria-label')) target.setAttribute('aria-label', first.label ?? first.title);
      target.removeAttribute('title');
      const arm = (): void => {
        if (timer !== 0) clearTimeout(timer);
        if (dwellMs > 0) timer = setTimeout(() => show(target), dwellMs);
        else show(target);
      };
      target.addEventListener('pointerenter', arm);
      target.addEventListener('focus', arm);
      target.addEventListener('pointerleave', hide);
      target.addEventListener('blur', hide);
      // A press means the user has decided; a label left over a menu that
      // just opened reads as part of the menu.
      target.addEventListener('pointerdown', hide);
      target.addEventListener('keydown', hide);
    },
    refreshLabel: (target) => {
      const raw = specs.get(target);
      if (typeof raw !== 'function') return;
      const spec = raw();
      if (spec !== null && spec.title) target.setAttribute('aria-label', spec.label ?? spec.title);
    },
    show,
    hide,
    target: () => tipFor,
    destroy: () => { hide(); node?.remove(); node = null; },
  };
}
