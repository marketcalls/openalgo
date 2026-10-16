/**
 * Seasonality: a heatmap of monthly percentage changes, one row per calendar
 * year, pinned to a corner of its own pane. Part of the lazy
 * `openalgo-charts/indicators` tier.
 *
 * The study answers something a curve cannot: "how has this symbol behaved in
 * October, historically?" That is a matrix keyed by month and year, not a value
 * per bar, so it comes back through the descriptor's `table` hook. The single
 * declared plot returns an all-null column: the one-column-per-plot contract
 * still has to be honoured, but the column draws nothing and is skipped by
 * autoscale, exactly as the fractal study's carrier column is.
 *
 * A month's figure is its close against the previous month's close, the same
 * one-period change the reference takes on a monthly series. Measuring only
 * from the month's own first bar would drop the gap over the turn of the month,
 * which on a gapping instrument is a large part of the move.
 *
 * Months are resolved on the chart's configured calendar, the same clock the
 * VWAP anchors run on, so a month boundary never lands on the UTC midnight seam
 * and never lands mid-afternoon in the market being charted. That calendar used
 * to be IST unconditionally, which on a US symbol put the month boundary at
 * 18:30 UTC and handed the last ninety minutes of a month-end New York session
 * to the following month.
 *
 * Unlike the VWAP and CPR frames, this one is deliberately tested bar by bar
 * rather than on session opens. Those two anchor an accumulation to a trading
 * period, which must not restart mid-session; this one attributes a close to a
 * calendar month, and a session that straddles the turn of the month genuinely
 * has bars in both.
 *
 * Two deliberate departures from the study as published:
 *   - it also draws a dashed projection box on the price pane for the month in
 *     progress, from the previous close to the price the historical average
 *     implies. This library has no box primitive, and that average is the
 *     "Avgs" row of the table, so the number itself is not lost.
 *   - its table width and height are percentages of the pane. A `table` hook
 *     cannot measure the pane it will be drawn into, so those two inputs are
 *     not offered rather than accepted and silently ignored, the same call the
 *     VWAP anchors make about the anchor kinds that need a feed we lack.
 *
 * Original implementation written from the described behaviour, per
 * ARCHITECTURE.md §0.1, not ported from any third-party source.
 */
import { utcSecondsToZonedParts, zonedWallClockToUtcSeconds } from 'openalgo-charts';
import type { Bar, IndicatorDescriptor, TableCell, TablePosition } from 'openalgo-charts';
import { num, str, flag, zoneOf } from './settings';

const POS_DEFAULT = '#089981';
const NEG_DEFAULT = '#F23745';
/** The neutral ink of the reference palette, behind headers and skipped cells. */
const NEUTRAL = '#787b86';

/** Cell opacity at zero magnitude, and at the intensity cutoff. */
const LIGHT_ALPHA = 0.1;
const HEAVY_ALPHA = 0.5;

const MONTH_NAMES: readonly string[] = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/**
 * `#rrggbb` plus an alpha byte. A heatmap that varied hue as well as strength
 * would need three colours read at once; varying only opacity keeps "which way"
 * and "how far" separable, and canvas takes the 8-digit form directly so there
 * is no rgba() detour. Anything that is not plain hex comes back untouched
 * rather than mangled, since a caller may hand us a named or functional colour.
 */
function withOpacity(color: string, alpha: number): string {
  let hex = color;
  if (/^#[0-9a-f]{3}$/i.test(hex)) {
    hex = `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`;
  } else if (/^#[0-9a-f]{8}$/i.test(hex)) {
    hex = hex.slice(0, 7);
  } else if (!/^#[0-9a-f]{6}$/i.test(hex)) {
    return color;
  }
  const byte = Math.round(Math.min(1, Math.max(0, alpha)) * 255);
  return `${hex}${byte.toString(16).padStart(2, '0')}`;
}

/** Fill behind the month header, the year column and the metric labels. */
const HEADER_BG = withOpacity(NEUTRAL, 0.2);
/** Fill for a month that was excluded from the maths. */
const SKIP_BG = withOpacity(NEUTRAL, 0.5);

/**
 * Fill for one percentage. The sign picks the base colour and the magnitude
 * picks the opacity, ramping from `LIGHT_ALPHA` at zero to `HEAVY_ALPHA` at
 * `cutoff` and flat above it. The saturation is the point: without it a single
 * outlier month would flatten every other cell into near-invisibility.
 *
 * A missing value gets no fill at all, so an empty cell reads as absent data
 * rather than as a neutral reading. The cells below carry that as
 * `bgColor: undefined`, which the table paints like an omitted fill; the
 * public `TableCell` keeps the member exact, hence their assertions.
 */
function rampColor(value: number | null, cutoff: number, pos: string, neg: string): string | undefined {
  if (value === null || !Number.isFinite(value)) return undefined;
  const base = value >= 0 ? pos : neg;
  const t = cutoff > 0 ? Math.min(1, Math.abs(value) / cutoff) : 1;
  return withOpacity(base, LIGHT_ALPHA + (HEAVY_ALPHA - LIGHT_ALPHA) * t);
}

const pct = (v: number): string => `${v.toFixed(2)}%`;

/** One calendar month's slice of the bar array, reduced to its closing price. */
interface MonthSpan {
  year: number;
  month: number;
  /** Close of the last bar that landed in this month. */
  last: number;
}

/**
 * Split the bars into calendar months of `zone`. Bars arrive in time order, so
 * a change of month opens a new span and nothing has to be sorted or keyed.
 *
 * The month a bar falls in is decided by the half-open UTC interval the current
 * month occupies rather than by resolving the bar's own calendar parts. The two
 * are the same test (a bar is in this month exactly when it lands inside the
 * month's span), but the interval is computed once per month instead of once
 * per bar, and resolving a zone costs an `Intl` lookup where comparing two
 * numbers costs nothing. A history of fifty thousand bars covers a couple of
 * hundred months.
 */
function monthSpans(bars: readonly Bar[], zone: string): MonthSpan[] {
  const out: MonthSpan[] = [];
  let cur: MonthSpan | null = null;
  let from = 0;
  let until = 0;
  for (const bar of bars) {
    if (cur === null || bar.time < from || bar.time >= until) {
      const p = utcSecondsToZonedParts(bar.time, zone);
      cur = { year: p.year, month: p.month, last: bar.close };
      out.push(cur);
      from = zonedWallClockToUtcSeconds(p.year, p.month, 1, 0, 0, 0, zone);
      // Month 13 is January of the next year, which `Date.UTC` rolls over for
      // us, so December needs no special case.
      until = zonedWallClockToUtcSeconds(p.year, p.month + 1, 1, 0, 0, 0, zone);
    } else {
      cur.last = bar.close;
    }
  }
  return out;
}

/** `YYYYMM`, the one integer that orders and compares a calendar month. */
const monthKey = (year: number, month: number): number => year * 100 + month;

/**
 * Parse the "ignored months" list: `YYYY-MM` entries separated by commas, with
 * spaces anywhere. The default value is the placeholder text itself, which
 * parses to nothing, so an untouched setting excludes no month.
 */
function ignoredKeys(spec: string): Set<number> {
  const out = new Set<number>();
  for (const item of spec.split(',')) {
    const digits = item.replace(/[\s-]/g, '');
    if (!/^\d{6}$/.test(digits)) continue;
    const key = Number(digits);
    const month = key % 100;
    if (month >= 1 && month <= 12) out.add(key);
  }
  return out;
}

interface SeasonalityMatrix {
  /** Years carrying at least one measured month, in the order they appeared. */
  years: number[];
  /** Per year, twelve slots indexed 0..11, null where no month was measured. */
  byYear: Map<number, (number | null)[]>;
  /** Month keys deliberately left out of the maths: ignored, or still forming. */
  skipped: Set<number>;
}

function buildMatrix(
  bars: readonly Bar[],
  settings: Readonly<Record<string, unknown>>,
): SeasonalityMatrix {
  const spans = monthSpans(bars, zoneOf(settings));
  const startYear = Math.round(num(settings, 'startYear', 2015));
  const skipped = ignoredKeys(str(settings, 'ignoredMonths', ''));

  // The last month in the data is still being written, so its change is not yet
  // a month's change. The reference reaches the same place from the other side,
  // by reading only closed monthly bars.
  const forming = spans.length > 0 ? spans[spans.length - 1]! : null;
  if (forming !== null) skipped.add(monthKey(forming.year, forming.month));

  const years: number[] = [];
  const byYear = new Map<number, (number | null)[]>();
  // A month's change is measured against the close of the month before it, so
  // the gap over the turn of the month counts, which on a gapping instrument is
  // most of the move. Index 0 is therefore unmeasurable and stays blank: the
  // first month in the data has no predecessor to measure against.
  for (let i = 1; i < spans.length; i++) {
    const span = spans[i]!;
    // The predecessor is the previous month *present in the data*, so a hole in
    // the series bridges rather than swallowing the month after it.
    const prev = spans[i - 1]!;
    if (span.year < startYear || skipped.has(monthKey(span.year, span.month))) continue;
    // A zero or non-finite previous close has no percentage change to report,
    // and the absolute denominator keeps the sign meaningful on a series that
    // can go negative, such as a spread.
    if (!Number.isFinite(prev.last) || !Number.isFinite(span.last) || prev.last === 0) continue;
    const change = (100 * (span.last - prev.last)) / Math.abs(prev.last);
    // An unavailable return must not create a year or enter its summary counts.
    if (!Number.isFinite(change)) continue;
    let row = byYear.get(span.year);
    if (row === undefined) {
      row = new Array<number | null>(12).fill(null);
      byYear.set(span.year, row);
      years.push(span.year);
    }
    row[span.month - 1] = change;
  }
  return { years, byYear, skipped };
}

/** Every measured reading for one month index, across the years on show. */
function column(matrix: SeasonalityMatrix, month: number): number[] {
  const out: number[] = [];
  for (const year of matrix.years) {
    const v = matrix.byYear.get(year)?.[month];
    if (v !== null && v !== undefined) out.push(v);
  }
  return out;
}

const mean = (v: readonly number[]): number | null => {
  if (v.length === 0) return null;
  let sum = 0;
  for (const x of v) sum += x;
  const result = sum / v.length;
  return Number.isFinite(result) ? result : null;
};

/** Sample standard deviation: these years are a sample of the seasons, not all of them. */
function sampleStdev(v: readonly number[]): number | null {
  if (v.length < 2) return null;
  const mu = mean(v);
  if (mu === null) return null;
  let acc = 0;
  for (const x of v) acc += (x - mu) * (x - mu);
  const result = Math.sqrt(acc / (v.length - 1));
  return Number.isFinite(result) ? result : null;
}

/** Share of readings at or above zero, as a percentage. */
const percentPositive = (v: readonly number[]): number | null => {
  if (v.length === 0) return null;
  let pos = 0;
  for (const x of v) if (x >= 0) pos += 1;
  return (100 * pos) / v.length;
};

const POSITIONS: Readonly<Record<string, TablePosition>> = {
  Left: 'bottom-left',
  Center: 'bottom-center',
  Right: 'bottom-right',
};

/** The year column carries four digits, the month columns a signed percentage. */
const CELL_WIDTHS: readonly number[] = [52, ...new Array<number>(12).fill(46)];

const labelCell = (text: string): TableCell => ({ text, bgColor: HEADER_BG });

export const SEASONALITY: IndicatorDescriptor = {
  id: 'seasonality',
  name: 'Seasonality',
  category: 'Trend',
  placement: 'pane',
  inputs: [
    { key: 'startYear', type: 'number', label: 'Starting year', default: 2015, min: 1800, max: 2999, step: 1 },
    { key: 'posColor', type: 'color', label: 'Positive Color', default: POS_DEFAULT, group: 'Color settings' },
    { key: 'negColor', type: 'color', label: 'Negative Color', default: NEG_DEFAULT, group: 'Color settings' },
    {
      key: 'cutoffPercent', type: 'number', label: 'Color intensity cutoff (%)', default: 10,
      min: 0, max: 100, step: 1, group: 'Color settings',
    },
    {
      key: 'tablePosition', type: 'select', label: 'Table Position', default: 'Center',
      options: [
        { label: 'Left', value: 'Left' },
        { label: 'Center', value: 'Center' },
        { label: 'Right', value: 'Right' },
      ],
      group: 'Heatmap settings',
    },
    {
      key: 'tableWidth', type: 'number', label: 'Table Width (%)', default: 100,
      min: 0, max: 100, step: 1, group: 'Heatmap settings',
    },
    {
      key: 'tableHeight', type: 'number', label: 'Table Height (%)', default: 95,
      min: 0, max: 100, step: 1, group: 'Heatmap settings',
    },
    { key: 'showAvg', type: 'boolean', label: 'Show Averages', default: true, group: 'Heatmap settings' },
    { key: 'showStDev', type: 'boolean', label: 'Show Standard Deviation', default: true, group: 'Heatmap settings' },
    { key: 'showPos', type: 'boolean', label: 'Show Percent Positive', default: true, group: 'Heatmap settings' },
    {
      key: 'ignoredMonths', type: 'text', label: 'Ignored months', default: 'YYYY-MM, YYYY-MM',
      group: 'Additional settings',
    },
  ],
  // The whole output is the grid below. This column exists so the descriptor
  // returns one column per declared plot and so the instance owns a pane; it is
  // all-null, which draws nothing and contributes nothing to autoscale.
  plots: [{ key: 'seasonality', type: 'line', title: 'Seasonality' }],
  calc: (bars) => ({ seasonality: new Array<number | null>(bars.length).fill(null) }),
  table: ({ bars, settings }) => {
    const matrix = buildMatrix(bars, settings);
    // Fewer than one completed month means there is nothing to tabulate, and a
    // header row on its own would read as a broken table rather than an empty one.
    if (matrix.years.length === 0) return null;

    const cutoff = num(settings, 'cutoffPercent', 10);
    const pos = str(settings, 'posColor', POS_DEFAULT);
    const neg = str(settings, 'negColor', NEG_DEFAULT);
    const rows: TableCell[][] = [[labelCell('Year'), ...MONTH_NAMES.map(labelCell)]];
    // Every row takes an equal share of the table's height except the rule
    // between the years and the summary rows, which is a divider and reads as a
    // gap in the data when it is given a full row of its own.
    const rowWeights: number[] = [1];

    for (const year of matrix.years) {
      const row = matrix.byYear.get(year) ?? [];
      const cells: TableCell[] = [labelCell(String(year))];
      for (let m = 0; m < 12; m++) {
        if (matrix.skipped.has(monthKey(year, m + 1))) {
          cells.push({ text: 'SKIP', bgColor: SKIP_BG });
          continue;
        }
        const v = row[m] ?? null;
        cells.push(v === null ? { text: '' } : { text: pct(v), bgColor: rampColor(v, cutoff, pos, neg) } as TableCell);
      }
      rows.push(cells);
      rowWeights.push(1);
    }

    const showAvg = flag(settings, 'showAvg', true);
    const showStDev = flag(settings, 'showStDev', true);
    const showPos = flag(settings, 'showPos', true);
    if (showAvg || showStDev || showPos) {
      // The reference separates the metrics with one cell merged across the
      // table. Without cell merging the same band is thirteen empty cells
      // sharing a fill, which draws identically.
      rows.push(Array.from({ length: 13 }, () => ({ text: '', bgColor: HEADER_BG })));
      rowWeights.push(0.3);

      if (showAvg) {
        const cells: TableCell[] = [labelCell('Avgs:')];
        for (let m = 0; m < 12; m++) {
          const v = mean(column(matrix, m));
          cells.push(v === null ? { text: '' } : { text: pct(v), bgColor: rampColor(v, cutoff, pos, neg) } as TableCell);
        }
        rows.push(cells);
        rowWeights.push(1);
      }
      if (showStDev) {
        // Dispersion has no direction, so this row stays neutral: colouring it
        // by the ramp would imply a sign the number does not carry.
        const cells: TableCell[] = [labelCell('StDev:')];
        for (let m = 0; m < 12; m++) {
          const v = sampleStdev(column(matrix, m));
          cells.push({ text: v === null ? '' : v.toFixed(2), bgColor: HEADER_BG });
        }
        rows.push(cells);
        rowWeights.push(1);
      }
      if (showPos) {
        // Measured against a coin flip rather than zero, hence the offset, and
        // the ramp saturates at 50 because 50 points from the midpoint is as
        // far as this figure can travel.
        const cells: TableCell[] = [labelCell('Pos%:')];
        for (let m = 0; m < 12; m++) {
          const v = percentPositive(column(matrix, m));
          cells.push(v === null
            ? { text: '' }
            : { text: `${Math.round(v)}%`, bgColor: rampColor(v - 50, 50, pos, neg) } as TableCell);
        }
        rows.push(cells);
        rowWeights.push(1);
      }
    }

    return {
      rows,
      options: {
        position: POSITIONS[str(settings, 'tablePosition', 'Center')] ?? 'bottom-center',
        cellWidth: CELL_WIDTHS,
        cellHeight: 18,
        rowWeights,
        // Percentages of the pane, matching the reference: 0 falls back to the
        // fixed cell sizes above, which is how a user asks for a compact grid.
        widthPercent: num(settings, 'tableWidth', 100),
        heightPercent: num(settings, 'tableHeight', 95),
        fontSize: 10,
        margin: 8,
      },
    };
  },
};

export const SEASONALITY_INDICATORS: readonly IndicatorDescriptor[] = [SEASONALITY];
