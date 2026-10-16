/**
 * Aligning a second instrument onto the primary series' bars.
 *
 * The x-axis is a gapless logical index over the times the shared DataLayer
 * holds (ARCHITECTURE.md §4.1, §5.3), so two instruments do not share a bar
 * index and cannot be laid side by side by position. They are matched by
 * timestamp, and the two directions of mismatch get opposite answers:
 *
 * - **A comparison bar with no primary bar is dropped.** The DataLayer merges
 *   *every* series' times into one index space, so a time only the comparison
 *   has would mint a new logical index: a column the primary instrument has no
 *   candle for, inserted mid-chart, shifting every bar after it. That happens
 *   for real (a different exchange's holiday calendar, a 24/7 instrument next
 *   to an NSE one, a feed that emits a stray print), and warping the primary's
 *   own axis to accommodate a comparison is never the right trade. The print is
 *   counted in `dropped` so a host can say so rather than silently losing it.
 *
 * - **A primary bar with no comparison bar becomes whitespace**, which is a NaN
 *   bar the line renderer breaks across, so the comparison shows a *gap*. The
 *   alternative, carrying the last known value forward, draws a flat segment
 *   through a session the instrument never traded and, worse, in percentage
 *   mode it anchors the move on the far side of the gap to a print that does
 *   not exist. Omitting the bar entirely is worse still: the renderer would
 *   join the two sides with one straight line across the holiday.
 *
 * Matching is on the exact timestamp. Bar-open times are bucketed by the candle
 * builder (§10.2) and stored as UTC seconds (§4.0), so two instruments on the
 * same interval agree to the second; anything that does not agree is a
 * different interval, which no tolerance window could rescue.
 */
import type { Bar, SeriesDataItem, UTCSeconds } from '../model/bar';
import { toBar } from '../model/bar';

/** What one alignment pass did, for a host that wants to report coverage. */
export interface ComparisonAlignment {
  /** Items handed to the comparison series: one per primary bar. */
  bars: number;
  /** Primary bars the comparison also traded (a value is drawn). */
  matched: number;
  /** Primary bars with no comparison print (drawn as a gap). */
  gaps: number;
  /** Comparison prints discarded for having no primary bar at that time. */
  dropped: number;
}

export const EMPTY_ALIGNMENT: ComparisonAlignment = { bars: 0, matched: 0, gaps: 0, dropped: 0 };

/**
 * Project `comparison` onto `primary`'s bars: one item per primary bar, in the
 * primary's order, so the result occupies exactly the logical indices the chart
 * already has and adds none of its own.
 *
 * Neither input is mutated and neither has to be sorted: matching goes through
 * a time map, which also collapses a repeated timestamp to its last item, the
 * same rule the DataLayer applies when it merges (`sortedUniqueByTime`).
 */
export function alignToPrimary(
  primary: readonly Bar[],
  comparison: readonly SeriesDataItem[],
): { items: SeriesDataItem[]; alignment: ComparisonAlignment } {
  const byTime = new Map<UTCSeconds, Bar>();
  for (const item of comparison) {
    const bar = toBar(item);
    // A correction can retract a prior reading. Its gap wins without claiming
    // overlap or counting a removed print as a dropped trade.
    if (isFinite(bar.close)) byTime.set(bar.time, bar);
    else byTime.delete(bar.time);
  }
  const items: SeriesDataItem[] = [];
  let matched = 0;
  for (const bar of primary) {
    const hit = byTime.get(bar.time);
    if (hit === undefined) {
      items.push({ time: bar.time }); // whitespace: holds the index, draws a gap
      continue;
    }
    // The comparison's own bar passes through whole, so a candlestick or
    // high-low comparison keeps its OHLC rather than being flattened to close.
    items.push(hit);
    matched++;
  }
  return {
    items,
    alignment: { bars: items.length, matched, gaps: items.length - matched, dropped: byTime.size - matched },
  };
}
