/**
 * Moving between the grid's charts and moving the charts themselves: the
 * grid's chords, the neighbour a chord or a swap reaches, and dragging a
 * chart by its bar onto another chart's place; and the mark a chart shows for
 * its link group.
 *
 * The chords go on each chart's own keymap, in a Chart grid section of its
 * shortcuts panel, so they are listed with every other chord and checked
 * against them for conflicts. Only the active chart's keymap answers
 * (`keyboardRoute`), so a chord acts once whatever the pointer rests on.
 * None uses Alt with a bare arrow, which is the browser's back and forward.
 */
import { chromeIconSvg } from 'openalgo-charts/draw';
import { h } from './context';
import type { ChartGridLinkGroup } from './grid-links';
import type { Keymap } from './keymap';
import { widgetText, type WidgetTranslationOptions } from './localization';

/** A group's mark: its letter on its colour. The letter carries the meaning; the colour only helps. */
export function groupMark(doc: Document, group: Pick<ChartGridLinkGroup, 'letter'> | null): HTMLSpanElement {
  const mark = h(doc, 'span', 'oac-grid__chip', { 'aria-hidden': 'true' });
  if (group === null) {
    mark.dataset.group = 'none';
    mark.innerHTML = chromeIconSvg('unlink');
  } else {
    mark.dataset.group = group.letter;
    mark.textContent = group.letter;
  }
  return mark;
}

type GridDirection = 'left' | 'right' | 'up' | 'down';

/** The slice of a cell the moves read. */
interface PlacedCell {
  readonly element: HTMLElement;
  readonly widget: { readonly root: HTMLElement };
  row: number;
  column: number;
  rowSpan: number;
  columnSpan: number;
}

/**
 * The chart beside `cell` in `dir`: one whose edge meets `cell`'s edge and
 * whose span overlaps it across, the one nearest its top or left corner when
 * a spanning chart has several neighbours on that side.
 */
export function neighbour<C extends PlacedCell>(cells: readonly C[], cell: C, dir: GridDirection): C | undefined {
  const across = dir === 'left' || dir === 'right';
  const meets = (c: C): boolean => {
    if (dir === 'right') return c.column === cell.column + cell.columnSpan;
    if (dir === 'left') return c.column + c.columnSpan === cell.column;
    if (dir === 'down') return c.row === cell.row + cell.rowSpan;
    return c.row + c.rowSpan === cell.row;
  };
  const [at, len] = across ? [cell.row, cell.rowSpan] : [cell.column, cell.columnSpan];
  const overlaps = (c: C): boolean => {
    const [lo, n] = across ? [c.row, c.rowSpan] : [c.column, c.columnSpan];
    return lo < at + len && lo + n > at;
  };
  const start = (c: C): number => Math.abs((across ? c.row : c.column) - at);
  return cells.filter(c => c !== cell && meets(c) && overlaps(c)).sort((a, b) => start(a) - start(b))[0];
}

interface GridKeysHost {
  readonly keymap: Keymap;
  readonly text: WidgetTranslationOptions;
  /** Maximize or restore this chart; false declines the chord. */
  toggleMaximize(): boolean;
  maximized(): boolean;
  restore(): void;
  /** Make the neighbouring chart active; false when there is none. */
  focus(dir: GridDirection): boolean;
  /** Trade places with the neighbouring chart; false when there is none or the grid shows one chart. */
  swap(dir: GridDirection): boolean;
}

const ARROWS: Readonly<Record<GridDirection, string>> = { left: 'ArrowLeft', right: 'ArrowRight', up: 'ArrowUp', down: 'ArrowDown' };
const FOCUS_LABEL = {
  left: 'Make the chart to the left active', right: 'Make the chart to the right active',
  up: 'Make the chart above active', down: 'Make the chart below active',
} as const;
const SWAP_LABEL = {
  left: 'Swap with the chart to the left', right: 'Swap with the chart to the right',
  up: 'Swap with the chart above', down: 'Swap with the chart below',
} as const;

/**
 * Register the grid's chords on one chart's keymap and return their
 * disposers. Alt+Enter maximizes or restores; Escape restores when nothing
 * else on the chart wants it (layered under the widget's own Escape);
 * Alt+Shift+arrow moves to a neighbour; Ctrl or Cmd with Shift and an arrow
 * swaps with it.
 */
export function installGridKeys(host: GridKeysHost): Array<() => void> {
  const km = host.keymap, t = host.text;
  const group = 'Chart grid';
  const offs = [
    km.register('Alt+Enter', () => host.toggleMaximize(), 'widget', { label: widgetText(t, 'Maximize or restore the chart'), group }),
    km.register('Escape', () => {
      if (!host.maximized()) return false;
      host.restore();
      return true;
    }, 'widget', { label: widgetText(t, 'Restore the grid'), group, layered: true }),
  ];
  for (const dir of ['left', 'right', 'up', 'down'] as const) {
    offs.push(
      km.register(`Alt+Shift+${ARROWS[dir]}`, () => host.focus(dir), 'widget', { label: widgetText(t, FOCUS_LABEL[dir]), group }),
      km.register(`Mod+Shift+${ARROWS[dir]}`, () => host.swap(dir), 'widget', { label: widgetText(t, SWAP_LABEL[dir]), group }),
    );
  }
  return offs;
}

interface HeaderDragHost<C extends PlacedCell> {
  readonly doc: Document;
  /** The cells area, which hears the press. */
  readonly body: HTMLElement;
  /** The grid root, which carries the drag state for the stylesheet. */
  readonly root: HTMLElement;
  cells(): readonly C[];
  /** False while the grid shows one chart at a time or has only one. */
  enabled(): boolean;
  swap(from: C, to: C): void;
  toggleMaximize(cell: C): void;
}

/** A press this far from where it started is a drag, not a click. */
const DRAG_THRESHOLD = 6;
/** Where a press on a chart's bar is a press on a control, not on the bar. */
const CONTROL = 'button, input, select, textarea, a, label, [role="button"], [role="radio"], [role="tab"], [contenteditable="true"]';
const HEAD = '.oac-topbar';

/**
 * Drag a chart by its bar's background onto another chart to trade places,
 * and double-click that background to maximize it. A press on a control on
 * the bar stays the control's. Escape or a cancelled pointer drops the drag
 * where it started. Returns the detacher.
 */
export function installHeaderDrag<C extends PlacedCell>(host: HeaderDragHost<C>): () => void {
  const { doc, body, root } = host;
  interface Drag { cell: C; head: HTMLElement; x: number; y: number; pointer: number; moving: boolean; over: C | null }
  let drag: Drag | null = null;

  /** The cell whose bar background `target` is on, or undefined. */
  const headOf = (target: EventTarget | null): { cell: C; head: HTMLElement } | undefined => {
    const el = target as (Element & { closest?: Element['closest'] }) | null;
    if (el === null || typeof el.closest !== 'function' || el.closest(CONTROL) !== null) return undefined;
    const head = el.closest(HEAD) as HTMLElement | null;
    if (head === null) return undefined;
    const cell = host.cells().find(c => c.element.contains(head));
    return cell === undefined ? undefined : { cell, head };
  };
  const inside = (c: C, x: number, y: number): boolean => {
    const r = c.element.getBoundingClientRect();
    return r.width > 0 && x >= r.left && x < r.left + r.width && y >= r.top && y < r.top + r.height;
  };
  const mark = (over: C | null): void => {
    if (drag === null) return;
    drag.over?.element.removeAttribute('data-drop');
    drag.over = over;
    over?.element.setAttribute('data-drop', 'true');
  };
  const end = (commit: boolean): void => {
    const d = drag;
    if (d === null) return;
    drag = null;
    doc.removeEventListener('pointermove', onMove as EventListener, true);
    doc.removeEventListener('pointerup', onUp as EventListener, true);
    doc.removeEventListener('pointercancel', onCancel, true);
    doc.removeEventListener('keydown', onKey as EventListener, true);
    if (!d.moving) return;
    d.over?.element.removeAttribute('data-drop');
    d.cell.element.removeAttribute('data-dragging');
    root.removeAttribute('data-dragging');
    try { d.head.releasePointerCapture?.(d.pointer); } catch { /* the pointer is gone already */ }
    if (commit && d.over !== null) host.swap(d.cell, d.over);
  };
  const onMove = (e: PointerEvent): void => {
    const d = drag;
    if (d === null || e.pointerId !== d.pointer) return;
    if (!d.moving) {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < DRAG_THRESHOLD) return;
      if (!host.enabled()) { end(false); return; }
      d.moving = true;
      root.setAttribute('data-dragging', 'true');
      d.cell.element.setAttribute('data-dragging', 'true');
      try { d.head.setPointerCapture?.(d.pointer); } catch { /* a synthetic pointer has nothing to capture */ }
    }
    e.preventDefault();
    mark(host.cells().find(c => c !== d.cell && inside(c, e.clientX, e.clientY)) ?? null);
  };
  const onUp = (e: PointerEvent): void => { if (drag !== null && e.pointerId === drag.pointer) end(true); };
  const onCancel = (): void => end(false);
  const onKey = (e: KeyboardEvent): void => {
    if (e.key !== 'Escape' || drag === null) return;
    // Only a drag in progress claims Escape; a press that never moved leaves it to the chart.
    if (drag.moving) { e.preventDefault(); e.stopPropagation(); }
    end(false);
  };
  const onDown = (e: PointerEvent): void => {
    if (e.button !== 0 || drag !== null || !host.enabled()) return;
    const at = headOf(e.target);
    if (at === undefined) return;
    drag = { ...at, x: e.clientX, y: e.clientY, pointer: e.pointerId, moving: false, over: null };
    doc.addEventListener('pointermove', onMove as EventListener, true);
    doc.addEventListener('pointerup', onUp as EventListener, true);
    doc.addEventListener('pointercancel', onCancel, true);
    doc.addEventListener('keydown', onKey as EventListener, true);
  };
  const onDouble = (e: MouseEvent): void => {
    const at = headOf(e.target);
    if (at !== undefined) host.toggleMaximize(at.cell);
  };
  body.addEventListener('pointerdown', onDown as EventListener);
  body.addEventListener('dblclick', onDouble as EventListener);
  return () => {
    end(false);
    body.removeEventListener('pointerdown', onDown as EventListener);
    body.removeEventListener('dblclick', onDouble as EventListener);
  };
}
