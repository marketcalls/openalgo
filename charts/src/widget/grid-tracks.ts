/**
 * The chart grid's tracks: the CSS grid template the weights make, the
 * splitters between the tracks that resize them by pointer and by keyboard,
 * and the dense mark a cell too small for its full chrome carries.
 *
 * Its own module so grid.ts carries the charts and their links. Each function
 * takes the grid's state (`GridState`, grid.ts).
 */
import { h } from './context';
import { widgetText } from './localization';
import { saveNow, saveSoon, scheduleSave } from './grid-persist';
import type { GridState } from './grid';

type Axis = 'row' | 'column';

/** Pixels between tracks, and the track a splitter sits in. */
const GUTTER = 4;
/** The smaller of two resized tracks keeps at least this share of the pair. */
const MIN_SHARE = 0.15;
/**
 * A cell narrower or shorter than this, in CSS px, is dense: its rail and the
 * secondary controls of its bar give their room to the chart. A four by four
 * grid on a laptop is about 300 by 180 per cell, and a full top bar there
 * wraps over a third of the chart; maximizing a cell brings everything back.
 */
const DENSE_WIDTH = 560;
const DENSE_HEIGHT = 340;

const round = (v: number): number => Math.round(v * 1e4) / 1e4;
export const tracks = (weights: readonly number[]): string => weights.map(w => `minmax(0,${w}fr)`).join(` ${GUTTER}px `);

/** One chart at a time: below the compact width, or while one is maximized. */
export const solo = (s: GridState): boolean => s.compact || s.maxed;

/** Mark each cell dense or not from its size; unmeasured cells keep their mark. */
export function density(s: GridState): void {
  for (const c of s.cells) {
    const box = c.element.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) c.element.dataset.dense = String(box.width < DENSE_WIDTH || box.height < DENSE_HEIGHT);
  }
}

// A splitter at boundary b sits between tracks b and b + 1, so both weights
// are there: whatever changes how many there are renders the splitters again.
function valueNow(s: GridState, split: HTMLElement): void {
  const w = split.dataset.axis === 'column' ? s.colW : s.rowW;
  const b = Number(split.dataset.index);
  split.setAttribute('aria-valuenow', String(Math.round(w[b]! / (w[b]! + w[b + 1]!) * 100)));
}

function resize(s: GridState, axis: Axis, b: number, first: number, dragging = false): void {
  const w = (axis === 'column' ? s.colW : s.rowW).slice();
  const pair = w[b]! + w[b + 1]!;
  const next = round(Math.min(pair * (1 - MIN_SHARE), Math.max(pair * MIN_SHARE, first)));
  if (next === w[b]) return;
  w[b] = next;
  w[b + 1] = round(pair - next);
  if (axis === 'column') { s.colW = w; s.body.style.gridTemplateColumns = tracks(w); }
  else { s.rowW = w; s.body.style.gridTemplateRows = tracks(w); }
  s.splits.forEach(split => valueNow(s, split));
  density(s);
  if (dragging) scheduleSave(s);
  else saveSoon(s);
  s.bus.emit('layout', { reason: 'weights' });
}

function splitter(s: GridState, axis: Axis, b: number, area: string): void {
  const { doc, body } = s;
  const col = axis === 'column';
  const split = h(doc, 'div', 'oac-grid__split', {
    role: 'separator', tabindex: '0', 'aria-orientation': col ? 'vertical' : 'horizontal',
    'aria-label': widgetText(s.text, col ? 'Resize columns {first} and {second}' : 'Resize rows {first} and {second}', { first: b + 1, second: b + 2 }),
    'aria-valuemin': '15', 'aria-valuemax': '85',
  });
  split.dataset.axis = axis;
  split.dataset.index = String(b);
  split.style.gridArea = area;
  const weights = (): number[] => (col ? s.colW : s.rowW);
  split.addEventListener('pointerdown', (e: PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const rect = body.getBoundingClientRect();
    const w = weights();
    const size = (col ? rect.width : rect.height) - GUTTER * (w.length - 1);
    const total = w.reduce((a, v) => a + v, 0);
    const start = col ? e.clientX : e.clientY;
    const first = w[b]!;
    split.setPointerCapture?.(e.pointerId);
    split.classList.add('is-drag');
    const move = (m: PointerEvent): void => {
      if (size > 0) resize(s, axis, b, first + ((col ? m.clientX : m.clientY) - start) / size * total, true);
    };
    const end = (): void => {
      // The drag is over, so its last weights are written now, not after the debounce.
      if (s.saveTimer !== 0) saveNow(s);
      split.classList.remove('is-drag');
      split.removeEventListener('pointermove', move);
      split.removeEventListener('pointerup', end);
      split.removeEventListener('pointercancel', end);
    };
    split.addEventListener('pointermove', move);
    split.addEventListener('pointerup', end);
    split.addEventListener('pointercancel', end);
  });
  split.addEventListener('keydown', (e: KeyboardEvent) => {
    const dir = (col ? ['ArrowLeft', 'ArrowRight'] : ['ArrowUp', 'ArrowDown']).indexOf(e.key);
    if (dir < 0) return;
    // Claimed here so neither the charts' keymaps nor the engine pan with it.
    e.preventDefault();
    e.stopPropagation();
    const w = weights();
    resize(s, axis, b, w[b]! + (dir * 2 - 1) * (w[b]! + w[b + 1]!) * (e.shiftKey ? 0.2 : 0.05));
  });
  split.addEventListener('dblclick', () => { const w = weights(); resize(s, axis, b, (w[b]! + w[b + 1]!) / 2); });
  split.hidden = solo(s);
  body.appendChild(split);
  s.splits.push(split);
  valueNow(s, split);
}

/** One splitter per run of tracks a boundary separates; a spanning chart interrupts the run. */
export function splitters(s: GridState, axis: Axis): void {
  const col = axis === 'column';
  const across = col ? s.rows : s.cols;
  for (let b = 0; b < (col ? s.cols : s.rows) - 1; b++) {
    let start = -1;
    for (let i = 0; i <= across; i++) {
      const open = i < across && !s.cells.some(c => {
        const [lo, len, at, span] = col ? [c.column, c.columnSpan, c.row, c.rowSpan] : [c.row, c.rowSpan, c.column, c.columnSpan];
        return lo <= b && lo + len > b + 1 && at <= i && at + span > i;
      });
      if (open && start < 0) start = i;
      if (!open && start >= 0) {
        // Grid lines, with a gutter track between every two chart tracks.
        const [from, to, gap] = [2 * start + 1, 2 * i, 2 * b + 2];
        splitter(s, axis, b, (col ? [from, gap, to, gap + 1] : [gap, from, gap + 1, to]).join(' / '));
        start = -1;
      }
    }
  }
}
