/**
 * The chart grid's layouts: every arrangement `setPreset` and the grid bar's
 * picker offer, from one chart to sixteen.
 *
 * A layout is data, not code: its rows and columns, one slot per chart with
 * the spans the workspace schema already carries, and the track weights it
 * starts with. The grid builds from the slots, the picker draws its tiles
 * from the same slots, and a saved desk records the id, so a layout added
 * here needs no code anywhere else.
 *
 * Every layout stays inside what a workspace document accepts: at most four
 * tracks a side (the document takes eight; a picker tile reads to four) and
 * sixteen charts. Slots are listed in reading order, by row and then column,
 * which is the order `cells()` promises.
 */

/**
 * The uniform layouts, rows by columns: every chart one cell, no spans. The
 * first six are the ones 2.5.9 shipped.
 */
export type ChartGridPreset =
  | '1x1' | '1x2' | '1x3' | '2x1' | '3x1' | '2x2'
  | '1x4' | '4x1' | '2x3' | '3x2' | '2x4' | '4x2' | '3x3' | '3x4' | '4x3' | '4x4';

/**
 * The uneven layouts, named for where the large chart sits and how many
 * charts share the rest: `left-3` is a large chart on the left with three
 * stacked beside it, `corner-5` a large chart in the top left corner with
 * five around it on a three by three grid.
 */
export type ChartGridUnevenLayout =
  | 'left-2' | 'right-2' | 'top-2' | 'bottom-2' | 'left-3' | 'top-3' | 'left-4' | 'top-4' | 'corner-5' | 'corner-7';

/** Any layout the grid can take: a uniform preset or an uneven layout. */
export type ChartGridLayoutId = ChartGridPreset | ChartGridUnevenLayout;

/** One chart's place in a layout, in the workspace schema's own terms. */
export interface ChartGridLayoutSlot {
  readonly row: number;
  readonly column: number;
  readonly rowSpan: number;
  readonly columnSpan: number;
}

export interface ChartGridLayoutSpec {
  readonly rows: number;
  readonly columns: number;
  /** One slot per chart, in reading order. */
  readonly slots: readonly ChartGridLayoutSlot[];
  /** The weights the tracks start with; a splitter changes them afterwards. */
  readonly rowWeights: readonly number[];
  readonly columnWeights: readonly number[];
}

/** Rows and columns of each uniform preset. The first six keep their 2.5.9 order. */
export const CHART_GRID_PRESETS: Readonly<Record<ChartGridPreset, readonly [rows: number, columns: number]>> = {
  '1x1': [1, 1], '1x2': [1, 2], '1x3': [1, 3], '2x1': [2, 1], '3x1': [3, 1], '2x2': [2, 2],
  '1x4': [1, 4], '4x1': [4, 1], '2x3': [2, 3], '3x2': [3, 2], '2x4': [2, 4], '4x2': [4, 2],
  '3x3': [3, 3], '3x4': [3, 4], '4x3': [4, 3], '4x4': [4, 4],
};

const slot = (row: number, column: number, rowSpan = 1, columnSpan = 1): ChartGridLayoutSlot => ({ row, column, rowSpan, columnSpan });
const even = (n: number): number[] => Array.from({ length: n }, () => 1);

function uniform(rows: number, columns: number): ChartGridLayoutSpec {
  const slots: ChartGridLayoutSlot[] = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < columns; c++) slots.push(slot(r, c));
  return { rows, columns, slots, rowWeights: even(rows), columnWeights: even(columns) };
}

/** A layout whose charts are spelt out; weights default to even tracks. */
function uneven(rows: number, columns: number, slots: ChartGridLayoutSlot[], rowWeights = even(rows), columnWeights = even(columns)): ChartGridLayoutSpec {
  return { rows, columns, slots, rowWeights, columnWeights };
}

/** The large chart beside a stack of `n`, on the left: one column of stacked charts is narrower than the large one. */
const leftOf = (n: number, weights: number[]): ChartGridLayoutSpec =>
  uneven(n, 2, [slot(0, 0, n), ...Array.from({ length: n }, (_, r) => slot(r, 1))], even(n), weights);
/** The large chart over a row of `n`. */
const topOf = (n: number, weights: number[]): ChartGridLayoutSpec =>
  uneven(2, n, [slot(0, 0, 1, n), ...Array.from({ length: n }, (_, c) => slot(1, c))], weights, even(n));

/**
 * One large chart in the top left corner of an `n` by `n` grid, taking all but
 * the last row and column, with the rest around it: down the right, then along
 * the bottom. Listed in reading order like every other layout.
 */
function corner(n: number): ChartGridLayoutSpec {
  const slots = [slot(0, 0, n - 1, n - 1)];
  for (let r = 0; r < n - 1; r++) slots.push(slot(r, n - 1));
  for (let c = 0; c < n; c++) slots.push(slot(n - 1, c));
  return uneven(n, n, slots);
}

/**
 * Every layout, in the order the grid bar's picker lists them: by the number
 * of charts, and within one count the uniform ones first.
 */
export const CHART_GRID_LAYOUTS: Readonly<Record<ChartGridLayoutId, ChartGridLayoutSpec>> = {
  '1x1': uniform(1, 1),
  '1x2': uniform(1, 2), '2x1': uniform(2, 1),
  '1x3': uniform(1, 3), '3x1': uniform(3, 1),
  'left-2': uneven(2, 2, [slot(0, 0, 2), slot(0, 1), slot(1, 1)]),
  'right-2': uneven(2, 2, [slot(0, 0), slot(0, 1, 2), slot(1, 0)]),
  'top-2': uneven(2, 2, [slot(0, 0, 1, 2), slot(1, 0), slot(1, 1)]),
  'bottom-2': uneven(2, 2, [slot(0, 0), slot(0, 1), slot(1, 0, 1, 2)]),
  '2x2': uniform(2, 2), '1x4': uniform(1, 4), '4x1': uniform(4, 1),
  // Three stacked beside a chart as wide as they are would leave the large one
  // no larger than a quarter of the desk: it takes two thirds of the width.
  'left-3': leftOf(3, [2, 1]),
  'top-3': topOf(3, [2, 1]),
  'left-4': uneven(2, 3, [slot(0, 0, 2), slot(0, 1), slot(0, 2), slot(1, 1), slot(1, 2)], even(2), [2, 1, 1]),
  'top-4': topOf(4, [2, 1]),
  '2x3': uniform(2, 3), '3x2': uniform(3, 2),
  'corner-5': corner(3),
  '2x4': uniform(2, 4), '4x2': uniform(4, 2),
  'corner-7': corner(4),
  '3x3': uniform(3, 3),
  '3x4': uniform(3, 4), '4x3': uniform(4, 3),
  '4x4': uniform(4, 4),
};

/** Whether `id` names a layout, read without trusting the prototype chain. */
export function isChartGridLayout(id: unknown): id is ChartGridLayoutId {
  return typeof id === 'string' && Object.prototype.hasOwnProperty.call(CHART_GRID_LAYOUTS, id);
}

/**
 * The slot the active chart takes when a layout is chosen: the largest one, the
 * first in reading order among equals. -1 for a uniform layout, where every
 * chart simply keeps its reading order.
 */
export function focusSlot(spec: ChartGridLayoutSpec): number {
  const areas = spec.slots.map(s => span(spec.rowWeights, s.row, s.rowSpan) * span(spec.columnWeights, s.column, s.columnSpan));
  const most = Math.max(...areas);
  return areas.every(a => a === most) ? -1 : areas.indexOf(most);
}

/** The share of the desk a run of tracks takes, in weight units. */
const span = (weights: readonly number[], at: number, count: number): number => {
  let sum = 0;
  for (let i = at; i < at + count; i++) sum += weights[i]!; // a catalogue slot lies inside its layout's tracks
  return sum;
};
