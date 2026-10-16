/**
 * Time alignment for chart linking: the one thing that makes a grid of charts
 * behave as a workspace instead of four charts that happen to move together.
 *
 * **The x-axis is a gapless logical index over each chart's own bars, so
 * logical index N is a different instant on every chart.** Two linked charts
 * normally hold different bar arrays: different symbols, different intervals,
 * different history depth, different holidays. Copying a logical index or a
 * logical range straight across looks perfect on two charts of the same symbol
 * and interval, and is wrong everywhere else, so nothing in this module ever
 * moves an index across a chart boundary. Every value is converted index ->
 * time on the sender and time -> index on the receiver, against that chart's
 * own data.
 *
 * The two conversions live here, apart from the group, because they are pure
 * and are the part worth reading twice.
 */
import type { LogicalRange } from '../scale/time-scale';

/**
 * The slice of `DataLayer` alignment reads. Declared structurally, in the
 * spirit of `ComparisonChartHost`, so the conversions can be tested against a
 * literal instead of a live chart.
 */
export interface LinkDataLayer {
  /** Number of logical indices (distinct bar times). */
  readonly length: number;
  indexToTime(index: number): number | undefined;
  timeToIndex(time: number): number | undefined;
  indexToTimeFloat(index: number): number;
  timeToIndexFloat(time: number): number;
}

/**
 * What a follower does when the leader's instant falls between its bars.
 *
 * - `nearest` (default): show the crosshair on the last bar that had OPENED by
 *   the leader's instant. A hole inside the follower's history is a missing bar,
 *   not a missing instant, and snapping to a real bar reads as "this one lines
 *   up" where a line floating between two candles belongs to neither.
 *
 *   Deliberately not the closest bar by timestamp. A bar is stamped at its open
 *   and lasts until the next one opens, so past the halfway point of a daily bar
 *   the arithmetically nearest stamp is tomorrow's, and the follower would
 *   highlight a candle that did not exist yet at the leader's instant.
 * - `hide`: draw nothing unless the follower has a bar at exactly that time.
 *   For a workspace where a linked crosshair is a data claim.
 *
 * Both policies refuse to answer **outside** the follower's coverage: an
 * instant before its first bar or after its last one is not a gap in its data,
 * it is a period the chart does not cover at all, and pinning the crosshair to
 * the first or last bar there would assert an alignment that does not exist.
 */
export type LinkMissingPolicy = 'nearest' | 'hide';

/**
 * Leader instant -> follower logical index, or null for "draw no crosshair".
 *
 * Returns an integer: a linked crosshair always sits on one of the follower's
 * own bars, never interpolated between them.
 */
export function followerIndex(
  follower: LinkDataLayer,
  time: number,
  whenMissing: LinkMissingPolicy = 'nearest',
): number | null {
  if (!Number.isFinite(time) || follower.length === 0) return null;
  const first = follower.indexToTime(0);
  const last = follower.indexToTime(follower.length - 1);
  if (first === undefined || last === undefined) return null;
  // Outside coverage: not a gap, an absence. See the policy note above.
  if (time < first || time > last) return null;

  const exact = follower.timeToIndex(time);
  if (exact !== undefined) return exact;
  if (whenMissing === 'hide') return null;

  // Inside the range with no bar at that exact second: take the last bar that
  // had OPENED by then, which is the floor of the fractional index.
  //
  // Not the nearest bar by timestamp. A bar is stamped at its open and covers
  // the span until the next one opens, so on a daily follower any instant past
  // midday is arithmetically closer to tomorrow's stamp than to today's, and
  // "nearest" would put the crosshair on a candle that did not exist yet at the
  // leader's instant. A follower showing the user a bar from the future is not
  // a rounding preference, it is wrong.
  //
  // The same rule gives the right answer in a real hole. Leader on a Saturday,
  // follower holding Friday and Monday: Friday is the last bar that had opened,
  // and Monday is still the future.
  const lo = Math.floor(follower.timeToIndexFloat(time));
  if (follower.indexToTime(lo) === undefined) return null;
  return Math.max(0, Math.min(lo, follower.length - 1));
}

/**
 * Leader visible range -> the follower range showing the same wall-clock window.
 *
 * Both ends go through the fractional conversions, so the window survives a
 * different bar interval (a daily follower under an hourly leader ends up with
 * a fraction of a bar visible, which is exactly right) and survives an end
 * landing in the empty margin to the right of the last bar, where `indexToTime`
 * has nothing to return.
 *
 * Returns null when the answer would be meaningless rather than guessing:
 * either chart empty, a single-bar follower (every time maps to index 0, so the
 * span collapses), or a non-finite endpoint.
 *
 * A follower whose history does not overlap the window at all is *not* refused.
 * `timeToIndexFloat` extrapolates past either edge (left of the first bar at
 * the first gap, right of the last on the follower's own future bar times), so
 * it scrolls into its own empty margin and shows nothing, which is the truth.
 * Clamping it back onto its last bars would show the user a different period
 * than the leader.
 */
export function followerRange(
  leader: LinkDataLayer,
  follower: LinkDataLayer,
  range: LogicalRange,
): LogicalRange | null {
  if (leader.length === 0 || follower.length < 2) return null;
  const timeFrom = leader.indexToTimeFloat(range.from);
  const timeTo = leader.indexToTimeFloat(range.to);
  if (!Number.isFinite(timeFrom) || !Number.isFinite(timeTo) || timeTo <= timeFrom) return null;

  const from = follower.timeToIndexFloat(timeFrom);
  const to = follower.timeToIndexFloat(timeTo);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return null;
  return { from, to };
}
