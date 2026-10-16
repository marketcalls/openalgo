/**
 * Axis label rendering (ARCHITECTURE.md §6, §5.3). Price axis (right strip) and
 * time axis (bottom strip). Time labels switch from clock to date at a day
 * boundary in the chart's configured zone, IST by default; gaps are already
 * collapsed by the logical-index time scale.
 *
 * Past the tick ladders, the file also owns the chrome that lives on the axis
 * strips: the countdown to the next bar close inside the last-price tag, the
 * crosshair's date pill, the corner session clock, and the priority rule that
 * decides which price-axis label survives a pile-up. All of it is opt-in, and an
 * axis nobody configured draws what it always drew.
 */
import type { PriceScale } from '../scale/price-scale';
import type { TimeScale } from '../scale/time-scale';
import type { DataLayer } from '../model/data-layer';
import { contrastText } from './pill';
import {
  DEFAULT_TIMEZONE, IST_OFFSET_SECONDS, formatIstDate, formatIstTime, formatIstTimeSeconds,
  formatZonedDate, formatZonedTime, formatZonedTimeSeconds, isNewZonedDay,
  isNewZonedMonth, isNewZonedYear, isValidTimezone, utcSecondsToIstParts, zoneOffsetSeconds,
} from '../feed/time';
import { roundRectPath } from './pill';

/**
 * Boundary class of a time-axis label, passed to a custom `timeFormatter` as a
 * hint so a host can render adaptive labels (year at year boundaries, month at
 * month boundaries, day otherwise, clock intraday): parity with common
 * `tickMarkFormatter(time, tickMarkType)` APIs.
 */
export type TickMarkType = 'year' | 'month' | 'day' | 'time' | 'timeWithSeconds';

export interface AxisStyle {
  textColor: string;
  lineColor: string;
  font: string; // CSS font at dpr=1; scaled by dpr at draw time
}

export const DEFAULT_AXIS_STYLE: AxisStyle = {
  textColor: '#8b91a7',
  lineColor: '#2a3046',
  font: '11px system-ui, sans-serif',
};

export interface PlotLayout {
  plotWidth: number;
  plotHeight: number;
  priceAxisWidth: number;
  timeAxisHeight: number;
  /** Left inset (px) reserved for a left price axis; 0 when there is no left axis. */
  plotLeft: number;
}

// ---------------------------------------------------------------------------
// Axis chrome
//
// Four pieces of furniture that sit on the axis strips rather than in the plot:
// the countdown inside the last-price tag, the crosshair's date pill, the corner
// session clock, and the rule that decides which price-axis label survives when
// several land on the same few pixels.
//
// Every one of them is inert unless the caller asks for it. A chart that
// configures nothing draws exactly the axes it drew before this section existed,
// which is pinned in tests/axis-chrome.test.ts.
// ---------------------------------------------------------------------------

/**
 * A clock reading UTC seconds (fractional allowed).
 *
 * Live chrome takes one of these rather than calling `Date.now()` itself: a test
 * has to hold time still, replay runs on the time of the bar being replayed, and
 * a terminal that trusts the exchange's clock over the browser's has to be able
 * to substitute its own. A renderer that reached for the global clock could
 * serve none of the three.
 */
type ClockSource = () => number;

/** Height of a price-axis tag in media px: last price, crosshair, price line. */
export const AXIS_TAG_HEIGHT = 16;

/**
 * Media px of axis height one price label is given.
 *
 * The ladder used to ask for a flat six labels whatever the pane measured, so a
 * tall chart read one price every 120 px and a short indicator pane crammed six
 * into 90. Six is right for the short pane and far too sparse for the tall one:
 * a trader reading a level off the axis ends up interpolating between labels
 * that are hundreds of points apart.
 *
 * Deriving the count from the height instead keeps the *spacing* constant, which
 * is what the eye actually reads. 32 px against an 11 px font is close to what
 * a professional terminal prints (measured: 21 labels down 630 px, so 30 px
 * apart) and lands a 700 px pane on about twenty prices rather than six.
 *
 * The ladder still snaps to a round step, so this is a request and not a
 * promise: `niceTicks` walks up the 1 / 2 / 2.5 / 5 ladder until the count fits,
 * and a range that has no round step at this density simply prints fewer.
 */
const PRICE_LABEL_SPACING = 32;

/** Labels that fit in `plotHeight`, clamped so a tiny pane still shows a ladder. */
export function priceTickCount(plotHeight: number): number {
  if (!Number.isFinite(plotHeight) || plotHeight <= 0) return 2;
  return Math.max(2, Math.min(30, Math.round(plotHeight / PRICE_LABEL_SPACING)));
}

/** Height of the last-price tag once the countdown adds its second row. */
export const AXIS_TAG_HEIGHT_COUNTDOWN = 28;

/**
 * How much of the price axis one label occupies, in device px, and how hard it
 * fights for the space. `y` is the label's centre, the same y its renderer
 * positions on.
 */
export interface AxisLabelBand {
  /** Centre of the label, device px. */
  y: number;
  /** Full height of the label, device px. */
  height: number;
  /** Higher wins a contested slot. See `AXIS_LABEL_PRIORITY`. */
  priority: number;
}

/**
 * Priority order for price-axis labels, highest first. The rule behind the
 * numbers: a label is worth more the less recoverable it is from the rest of the
 * axis, and the more directly the user asked for it.
 *
 *  - `crosshair`     the reading under the cursor. The user is pointing at it.
 *  - `lastPrice`     where the market is now. Nothing outranks it but the cursor.
 *  - `priceLine`     a level the user placed: an order, a stop, a target. It is
 *                    theirs, and it is the one they are watching for a touch.
 *  - `sessionLevel`  a session high or low drawn by a study. Derived, but not
 *                    reconstructible by eye.
 *  - `previousClose` yesterday's close. Same class, and less often the reason
 *                    the chart is open, so it yields to a live session extreme.
 *  - `seriesValue`   the current reading of a plotted series, typically an
 *                    indicator's. A reader can recover it by following the line
 *                    to the edge, so it yields to every level above it, but it
 *                    is the number the line exists to communicate and a plain
 *                    tick beside it is the more expendable of the two.
 *  - `tick`          the plain ladder. The one label a reader can interpolate
 *                    from its neighbours, so it is the one to drop.
 *
 * The gaps are wide on purpose: a host with a level of its own can slot it
 * between two of these without editing the table.
 */
export const AXIS_LABEL_PRIORITY = {
  crosshair: 100,
  lastPrice: 90,
  priceLine: 70,
  sessionLevel: 50,
  previousClose: 40,
  seriesValue: 30,
  tick: 10,
} as const;

/**
 * Decide which labels may draw. Returns one flag per input band, in input order:
 * true to draw, false to suppress.
 *
 * Greedy in priority order, so a high-priority label always survives and takes
 * the lower-priority ones overlapping it down with it. Ties break on input
 * order rather than arbitrarily, so two labels of equal rank resolve the same
 * way on every frame instead of trading places and flickering.
 *
 * `minGap` is the clear space demanded between two labels on top of their own
 * heights, in device px: touching tags still read as mush, so a couple of pixels
 * of daylight is part of not overlapping.
 */
export function resolveAxisLabels(bands: readonly AxisLabelBand[], minGap = 0): boolean[] {
  const allowed = new Array<boolean>(bands.length).fill(false);
  // `order` holds the indices of `bands`, so every read of it by one is there.
  const order = bands.map((_, i) => i);
  order.sort((a, b) => bands[b]!.priority - bands[a]!.priority || a - b);
  const taken: AxisLabelBand[] = [];
  for (const i of order) {
    const band = bands[i]!;
    if (!Number.isFinite(band.y) || !Number.isFinite(band.height)) continue;
    let clear = true;
    for (const t of taken) {
      if (Math.abs(t.y - band.y) < (t.height + band.height) / 2 + minGap) {
        clear = false;
        break;
      }
    }
    if (!clear) continue;
    allowed[i] = true;
    taken.push(band);
  }
  return allowed;
}

/**
 * Which ticks of the ladder survive the labels the caller has reserved. Null
 * means "no reservations, draw them all", which is the path every existing
 * caller takes and the reason an unconfigured chart cannot move a pixel.
 */
function survivingTicks(
  ticks: readonly number[],
  priceScale: PriceScale,
  dpr: number,
  reserved: readonly AxisLabelBand[] | undefined,
): boolean[] | null {
  if (reserved === undefined || reserved.length === 0) return null;
  const bands: AxisLabelBand[] = ticks.map((price) => ({
    y: Math.round(priceScale.priceToY(price) * dpr),
    height: AXIS_TAG_HEIGHT * dpr,
    priority: AXIS_LABEL_PRIORITY.tick,
  }));
  // The reserved bands are resolved alongside the ticks so a tick loses to them,
  // but their own flags are dropped: their renderers have already decided to
  // draw, and a caller with two of its own colliding levels resolves that set
  // itself by calling `resolveAxisLabels` directly.
  return resolveAxisLabels([...bands, ...reserved], 2 * dpr).slice(0, ticks.length);
}

/**
 * Whether a tick label centred on `y` fits whole between the strip's top and
 * `bottom`, in device px. A label is a tag-height band here, as it is to the
 * collision rule above, so a rung within half a tag of the pane's edge, where
 * the next pane or the time axis would cut its label in two and leave a
 * different number, or none, is not labelled. The gridline stays, and so do
 * its neighbours. Judged on the band rather than on measured ink, so the same
 * rungs are labelled in every engine and with every font.
 */
function tickFits(y: number, bottom: number, dpr: number): boolean {
  const half = (AXIS_TAG_HEIGHT / 2) * dpr;
  return y >= half && y <= bottom - half;
}

/**
 * Draw price tick labels in an axis strip (bitmap scope). On the right the
 * strip starts at `layout.plotWidth` and the labels are left-aligned into it;
 * on the left it ends at `layout.plotLeft` (absolute pane coordinates, not the
 * shifted plot frame) and they are right-aligned. The separator sits at the
 * strip's inner edge either way.
 *
 * `reserved` lists the bands other labels have already claimed (last price,
 * price lines, session levels). A tick colliding with one of them is dropped
 * rather than drawn through it. Omit it and every tick draws, exactly as before.
 */
export function drawPriceAxis(
  ctx: CanvasRenderingContext2D,
  priceScale: PriceScale,
  layout: PlotLayout,
  dpr: number,
  style: AxisStyle = DEFAULT_AXIS_STYLE,
  reserved?: readonly AxisLabelBand[],
  side: 'left' | 'right' = 'right',
): void {
  // The scale owns the ladder: in the rebasing modes a nice price is an ugly
  // percentage, so the values have to be chosen in label space (see
  // `PriceScale.ticks`). Linear and log get the same ladder as before.
  const ticks = priceScale.ticks(priceTickCount(layout.plotHeight));
  const keep = survivingTicks(ticks, priceScale, dpr, reserved);
  const left = side === 'left';
  const edge = Math.round((left ? layout.plotLeft : layout.plotWidth) * dpr);
  const rule = left ? edge - 0.5 : edge + 0.5, textX = left ? edge - 6 * dpr : edge + 6 * dpr;

  ctx.save();
  ctx.strokeStyle = style.lineColor;
  ctx.fillStyle = style.textColor;
  ctx.font = scaleFont(style.font, dpr);
  ctx.textAlign = left ? 'right' : 'left';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 1;

  // axis separator
  ctx.beginPath();
  ctx.moveTo(rule, 0);
  ctx.lineTo(rule, Math.round(layout.plotHeight * dpr));
  ctx.stroke();

  for (let i = 0; i < ticks.length; i++) {
    if (keep !== null && !keep[i]) continue;
    const price = ticks[i]!;
    const y = Math.round(priceScale.priceToY(price) * dpr);
    if (!tickFits(y, layout.plotHeight * dpr, dpr)) continue;
    ctx.fillText(priceScale.format(price), textX, y);
  }
  ctx.restore();
}

/**
 * Which boundary two adjacent ticks straddle, decided on the calendar of `zone`.
 *
 * Reading it in the wrong zone is not a cosmetic slip: a New York chart whose
 * ticks are compared in IST turns its day over at 14:30 local, so the date label
 * lands in the middle of the trading afternoon. Same shape as the session anchor
 * fixed in 1.2.0.
 */
function tickMarkBetween(
  prevUtcSeconds: number,
  utcSeconds: number,
  zone: string,
  subMinute: boolean,
): TickMarkType {
  const clock: TickMarkType = subMinute ? 'timeWithSeconds' : 'time';
  if (zone === DEFAULT_TIMEZONE) {
    const a = utcSecondsToIstParts(prevUtcSeconds);
    const b = utcSecondsToIstParts(utcSeconds);
    return a.year !== b.year ? 'year'
      : a.month !== b.month ? 'month'
        : a.day !== b.day ? 'day'
          : clock;
  }
  // The zoned tests read the parts cache the labels already filled for these two
  // instants, so escalating a tick mark is a pair of map reads and an integer
  // compare. No Intl call happens twice for the same second, per frame or ever.
  return isNewZonedYear(prevUtcSeconds, utcSeconds, zone) ? 'year'
    : isNewZonedMonth(prevUtcSeconds, utcSeconds, zone) ? 'month'
      : isNewZonedDay(prevUtcSeconds, utcSeconds, zone) ? 'day'
        : clock;
}

/**
 * Whether two instants fall on different IST dates, as `isNewIstDay` answers it
 * but without its two dates and two part objects per call: the time axis asks
 * for every bar in view on every frame of a pan. IST keeps one offset all
 * year, so the date is the day count of the shifted instant, taken the way a
 * `Date` takes it (whole milliseconds, then days); an instant a `Date` cannot
 * hold is a new day, as it is there.
 */
export function isNewIstDayCount(prevUtcSeconds: number, utcSeconds: number): boolean {
  const a = istDayCount(prevUtcSeconds);
  return a !== a || a !== istDayCount(utcSeconds);
}

function istDayCount(utcSeconds: number): number {
  const ms = Math.trunc((utcSeconds + IST_OFFSET_SECONDS) * 1000);
  return Math.abs(ms) <= 8.64e15 ? Math.floor(ms / 86_400_000) : NaN;
}

/**
 * Draw time tick labels along the bottom axis strip (bitmap scope).
 *
 * `timezone` is the IANA zone the labels read in; absent means the shipped
 * default. A custom `timeFormatter` still owns the label text, but it is handed
 * a `tickMark` hint computed on the same zone, so a host formatter and a default
 * one agree on where the day turns over.
 */
export function drawTimeAxis(
  ctx: CanvasRenderingContext2D,
  timeScale: TimeScale,
  dataLayer: DataLayer,
  layout: PlotLayout,
  dpr: number,
  style: AxisStyle = DEFAULT_AXIS_STYLE,
  timeFormatter?: (utcSeconds: number, tickMark?: TickMarkType) => string,
  timezone?: string,
): void {
  const range = timeScale.visibleRange();
  const from = Math.max(0, Math.floor(range.from));
  const to = Math.min(dataLayer.baseIndex, Math.ceil(range.to));
  if (to < from) return;

  // Label roughly every ~80px to avoid crowding.
  const stride = Math.max(1, Math.round(80 / Math.max(1, timeScale.barSpacing)));
  const yBase = Math.round(layout.plotHeight * dpr);

  // Detect sub-minute (seconds / tick) timeframes from the visible data so the
  // axis shows HH:MM:SS instead of collapsing same-minute bars to one label.
  // Use the smallest positive gap between adjacent bars as the bar interval,
  // and of those, one that crosses into another minute where there is one: a
  // seconds chart crosses each minute a few seconds at a time, while elements
  // a transform formed on one bar sit a second apart inside that bar's minute
  // and say nothing about the chart's resolution.
  let barIntervalSec = Number.POSITIVE_INFINITY;
  {
    let prev = dataLayer.indexToTime(from);
    let within = Number.POSITIVE_INFINITY;
    for (let i = from + 1; i <= to; i++) {
      const t = dataLayer.indexToTime(i);
      if (t !== undefined && prev !== undefined) {
        const d = t - prev;
        if (d > 0 && Math.floor(t / 60) !== Math.floor(prev / 60)) barIntervalSec = Math.min(barIntervalSec, d);
        else if (d > 0) within = Math.min(within, d);
      }
      if (t !== undefined) prev = t;
    }
    if (!Number.isFinite(barIntervalSec)) barIntervalSec = within;
  }
  // Seconds resolution only helps when the labelled step itself is sub-minute.
  const labelStepSec = barIntervalSec * stride;
  const subMinute = Number.isFinite(labelStepSec) && labelStepSec < 60;

  // The chart rejects an unknown zone where the caller set it, but this runs on
  // every pan frame and a throw here would take the render loop down with it: a
  // name that got past validation anyway (a hand-built render context, a saved
  // layout from a richer ICU build) costs a wrong-zone axis, never the chart.
  const zone = timezone === undefined || timezone === DEFAULT_TIMEZONE || !isValidTimezone(timezone)
    ? DEFAULT_TIMEZONE
    : timezone;
  // The default zone keeps the offset arithmetic it has always used. The two
  // paths agree (pinned in tests/axis-timezone.test.ts), so this buys no answer
  // the zoned path would not give; it buys that an existing chart's labels
  // cannot move, and that they never depend on the host's ICU build.
  const defaultZone = zone === DEFAULT_TIMEZONE;
  const isNewDay = defaultZone
    ? isNewIstDayCount
    : (prev: number, t: number): boolean => isNewZonedDay(prev, t, zone);
  const dateLabel = defaultZone ? formatIstDate : (t: number): string => formatZonedDate(t, zone);
  const timeLabel = defaultZone ? formatIstTime : (t: number): string => formatZonedTime(t, zone);
  const secondsLabel = defaultZone
    ? formatIstTimeSeconds
    : (t: number): string => formatZonedTimeSeconds(t, zone);

  ctx.save();
  ctx.fillStyle = style.textColor;
  ctx.strokeStyle = style.lineColor;
  ctx.font = scaleFont(style.font, dpr);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, yBase + 0.5);
  ctx.lineTo(Math.round(layout.plotWidth * dpr), yBase + 0.5);
  ctx.stroke();

  // Where to put a label: the regular grid, plus the first bar of every new day.
  //
  // A day boundary does not land on the grid in general, and it is exactly the
  // label a reader needs most. With a session that has just opened there may be
  // only a handful of bars after it, so the next grid tick is past the right
  // edge and the date is never drawn at all: the axis then shows today's bars
  // sitting under yesterday's date, with nothing marking the change. Forcing a
  // mark at the boundary is what a professional terminal does, and it is why one
  // prints "Sep" between two hourly labels rather than on the hour.
  const boundaries = new Set<number>();
  {
    let prev = dataLayer.indexToTime(from);
    for (let i = from + 1; i <= to; i++) {
      const t = dataLayer.indexToTime(i);
      if (t === undefined) continue;
      if (prev !== undefined && isNewDay(prev, t)) boundaries.add(i);
      prev = t;
    }
  }
  const marks = [...new Set([...gridIndices(from, to, stride), ...boundaries])]
    .sort((a, b) => a - b);

  // Text is resolved in index order, because choosing between a date and a clock
  // reading depends on the previous label, then placed in a second pass. The two
  // cannot be one loop: a boundary has to be able to displace a grid tick drawn
  // before it, and by then that tick is already on the canvas.
  interface TimeLabel { x: number; text: string; half: number; boundary: boolean }
  const placed: TimeLabel[] = [];
  let prevTime: number | undefined;
  for (const i of marks) {
    const time = dataLayer.indexToTime(i);
    if (time === undefined) continue;
    const x = Math.round(timeScale.indexToX(i) * dpr);
    if (x < 0 || x > layout.plotWidth * dpr) {
      prevTime = time;
      continue;
    }
    let label: string;
    if (timeFormatter) {
      const tm = prevTime === undefined
        ? 'day'
        : tickMarkBetween(prevTime, time, zone, subMinute);
      label = timeFormatter(time, tm);
    } else {
      label = prevTime === undefined || isNewDay(prevTime, time)
        ? dateLabel(time)
        : subMinute
          ? secondsLabel(time)
          : timeLabel(time);
    }
    placed.push({
      x,
      text: label,
      half: ctx.measureText(label).width / 2,
      boundary: boundaries.has(i),
    });
    prevTime = time;
  }

  // Boundaries claim their space first, so a date always survives and the grid
  // tick beside it yields. The other way round loses "Sep" to a 10:00 that its
  // neighbours already imply, which is the whole point of forcing the mark.
  const gap = 4 * dpr;
  const taken: TimeLabel[] = [];
  const fits = (l: TimeLabel): boolean =>
    taken.every((t) => l.x + l.half + gap <= t.x - t.half || l.x - l.half - gap >= t.x + t.half);
  // Boundaries still check each other: zoomed far out, two day changes can land
  // within a label's width and would otherwise print through one another.
  for (const l of placed) if (l.boundary && fits(l)) taken.push(l);
  for (const l of placed) if (!l.boundary && fits(l)) taken.push(l);

  // Resolved by priority, drawn left to right: the order labels are chosen in is
  // not the order they belong on the axis.
  taken.sort((a, b) => a.x - b.x);
  for (const l of taken) ctx.fillText(l.text, l.x, yBase + 4 * dpr);
  ctx.restore();
}

/** Indices on the regular label grid. */
function gridIndices(from: number, to: number, stride: number): number[] {
  const out: number[] = [];
  for (let i = from; i <= to; i += stride) out.push(i);
  return out;
}

/** The last price's up and down fills, and the text written on them. */
interface LastPriceColors {
  up: string;
  down: string;
  text: string;
}

const DEFAULT_LAST_PRICE_COLORS: LastPriceColors = { up: '#26a69a', down: '#ef5350', text: '#0d0e12' };

/** Anything that can answer "what time is bar `index`", i.e. a `DataLayer`. */
export interface BarTimeSource {
  indexToTime(index: number): number | undefined;
  readonly baseIndex: number;
}

/**
 * Bar interval in seconds, read back from the last `sample` bars. 0 when the
 * series says nothing usable (empty, a single bar, timestamps that never
 * advance).
 *
 * Median and not mean, for the reason `sessionStartIndices` uses a median: an
 * overnight break, a holiday or a feed outage leaves gaps orders of magnitude
 * wider than the timeframe and an average would chase them. Median and not
 * minimum either, which is the other tempting reading: a backfilled duplicate or
 * a conflated tick lands two bars a second apart and would halve the answer.
 *
 * Only the tail is sampled. The countdown wants the cadence the feed is running
 * at now, not the one a year of history was recorded at, and a chart that
 * switched timeframe mid-session should follow within a screen of bars.
 */
export function medianBarInterval(bars: BarTimeSource, sample = 64): number {
  const to = bars.baseIndex;
  const from = Math.max(0, to - sample);
  const gaps: number[] = [];
  let prev: number | undefined;
  for (let i = from; i <= to; i++) {
    const t = bars.indexToTime(i);
    if (t === undefined) continue;
    if (prev !== undefined && t - prev > 0) gaps.push(t - prev);
    prev = t;
  }
  if (gaps.length === 0) return 0;
  gaps.sort((a, b) => a - b);
  return gaps[gaps.length >> 1]!; // gaps is not empty (above)
}

/** The countdown row inside the last-price tag. Absent or `visible: false` draws no row. */
export interface BarCountdownOptions {
  /** Draw the row. Unset or false leaves the tag exactly one line, as before. */
  visible?: boolean;
  /** UTC seconds now. Never `Date.now()` reached for here, see `ClockSource`. */
  now: ClockSource;
  /** Open time (UTC seconds) of the last bar on the chart. */
  lastBarTime: number;
  /** Bar interval in seconds, e.g. from `medianBarInterval`. */
  intervalSec: number;
}

/**
 * Seconds left before the bar that opened at `lastBarTime` closes. Null when
 * there is nothing to count: no readable interval, or a clock that gave up.
 *
 * Past the close the answer rolls into the next bar's cycle rather than sitting
 * at zero or going negative, so a feed that is a little late with the new bar
 * shows a countdown that keeps running instead of a stalled 00:00:00. At the
 * exact instant of a close it therefore reads a full interval: that is the bar
 * which just started, and it is the honest answer even before its first tick
 * arrives.
 */
export function barCountdownSeconds(
  lastBarTime: number,
  intervalSec: number,
  nowSeconds: number,
): number | null {
  if (!Number.isFinite(intervalSec) || intervalSec <= 0) return null;
  if (!Number.isFinite(lastBarTime) || !Number.isFinite(nowSeconds)) return null;
  const elapsed = nowSeconds - lastBarTime;
  // A clock behind the bar (a stale reading, a machine running slow) is still
  // counting down to this bar's close, so it gets the longer answer rather than
  // being folded backwards into the previous bar's cycle by the modulo.
  if (elapsed < 0) return intervalSec - elapsed;
  return intervalSec - (elapsed % intervalSec);
}

const pad2 = (n: number): string => (n < 10 ? `0${n}` : String(n));

/**
 * `HH:MM:SS` for a countdown. Null (nothing to count) reads `--:--:--` rather
 * than vanishing: the caller asked for the row, so the row appears and says it
 * has no cadence to work from. A row that silently disappeared would look like
 * the option had not taken effect.
 *
 * Hours are not capped at 24. A daily bar counts down from 24:00:00 and a weekly
 * one from further out; truncating either would be a lie about which bar closes.
 */
export function formatCountdown(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '--:--:--';
  // Ceil, so the last full second on screen is 00:00:01 and the roll to the next
  // bar happens as the close passes, not a second before it.
  const total = Math.max(0, Math.ceil(seconds));
  return `${pad2(Math.floor(total / 3600))}:${pad2(Math.floor((total % 3600) / 60))}:${pad2(total % 60)}`;
}

/** Height of the last-price tag in device px, with or without the countdown row. */
export function lastPriceTagHeight(dpr: number, countdown = false): number {
  return (countdown ? AXIS_TAG_HEIGHT_COUNTDOWN : AXIS_TAG_HEIGHT) * dpr;
}

/** Shared placement keeps left-axis collision reservations aligned with their tags. */
export function axisTagY(y: number, plotHeight: number, tagHeight: number, side: 'left' | 'right'): number | null {
  if (!Number.isFinite(y) || y < 0 || y > plotHeight) return null;
  if (side === 'right') return y;
  if (plotHeight < tagHeight) return null;
  return Math.max(tagHeight / 2, Math.min(plotHeight - tagHeight / 2, y));
}

/** Fit left labels inside their existing column without changing right-axis geometry. */
function fillLeftTag(
  ctx: CanvasRenderingContext2D, y: number, height: number,
  rows: readonly { text: string; font: string; offset: number }[],
  layout: PlotLayout, dpr: number, fill: string, text: string,
): void {
  const available = Math.round(layout.plotLeft * dpr) - 1;
  if (!(available > 0)) return;
  const pad = Math.min(6 * dpr, available / 4);
  const widths = rows.map(row => { ctx.font = row.font; return ctx.measureText(row.text).width; });
  const width = Math.min(available, Math.max(...widths) + pad * 2);
  const x = -1 - width;
  ctx.fillStyle = fill;
  ctx.fillRect(x, y - height / 2, width, height);
  ctx.fillStyle = text;
  // widths maps rows, so both hold every i of the loop.
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]!;
    const size = Number(/(^|[^\d.])(\d{1,5}(?:\.\d{1,4})?)px/.exec(row.font)?.[2]);
    const heightFactor = size > 0 ? (height / rows.length - 2 * dpr) / size : 1;
    const widthFactor = widths[i]! > 0 ? (width - pad * 2) / widths[i]! : 1;
    ctx.font = scaleFont(row.font, Math.min(1, widthFactor, heightFactor));
    ctx.fillText(row.text, x + pad, y + row.offset);
  }
}

/**
 * One filled tag in the axis strip, sized to its own text. Shared by the
 * last-price tag and the per-series ones so the two cannot drift apart in
 * padding, height or baseline.
 */
function fillTag(
  ctx: CanvasRenderingContext2D,
  xStart: number, y: number, boxH: number, padX: number,
  label: string, fill: string, text: string,
): void {
  const textW = ctx.measureText(label).width;
  ctx.fillStyle = fill;
  ctx.fillRect(xStart + 1, y - boxH / 2, textW + padX * 2, boxH);
  ctx.fillStyle = text;
  ctx.fillText(label, xStart + 1 + padX, y);
}

/**
 * The current value of one plotted series, as a tag in the price-axis strip.
 *
 * This is the last-price tag's smaller sibling and is deliberately the same
 * shape, because it means the same thing: where this line is right now. What it
 * does not get is the dashed line across the plot, since the series already
 * draws itself all the way to the edge, nor the bar countdown, which belongs to
 * the instrument and not to a study computed from it.
 *
 * The price is formatted by the scale the series maps to, so a tag reads at the
 * same precision as the ticks above and below it.
 */
export function drawSeriesValueTag(
  ctx: CanvasRenderingContext2D,
  priceScale: PriceScale,
  price: number,
  fill: string,
  layout: PlotLayout,
  dpr: number,
  style: AxisStyle = DEFAULT_AXIS_STYLE,
  side: 'left' | 'right' = 'right',
): void {
  if (!Number.isFinite(price)) return;
  const y = axisTagY(Math.round(priceScale.priceToY(price) * dpr), layout.plotHeight * dpr, lastPriceTagHeight(dpr), side);
  if (y === null) return;
  ctx.save();
  ctx.font = scaleFont(style.font, dpr);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  if (side === 'left') {
    fillLeftTag(ctx, y, lastPriceTagHeight(dpr), [{ text: priceScale.format(price), font: ctx.font, offset: 0 }],
      layout, dpr, fill, contrastText(fill));
  } else {
    fillTag(ctx, Math.round(layout.plotWidth * dpr), y, lastPriceTagHeight(dpr), 6 * dpr,
      priceScale.format(price), fill, contrastText(fill));
  }
  ctx.restore();
}

/**
 * The last price's dashed line across the plot, coloured up or down. Updates
 * cheaply with every live tick. Draws nothing for a price off the plot.
 */
export function drawLastPriceLine(
  ctx: CanvasRenderingContext2D,
  priceScale: PriceScale,
  price: number,
  up: boolean,
  layout: PlotLayout,
  dpr: number,
  colors: LastPriceColors = DEFAULT_LAST_PRICE_COLORS,
): void {
  const y = Math.round(priceScale.priceToY(price) * dpr);
  if (!Number.isFinite(y) || y < 0 || y > layout.plotHeight * dpr) return;
  const color = up ? colors.up : colors.down;
  const xStart = Math.round(layout.plotWidth * dpr);
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1, Math.round(dpr));
  ctx.setLineDash([3 * dpr, 3 * dpr]);
  ctx.beginPath();
  ctx.moveTo(0, y + 0.5);
  ctx.lineTo(xStart, y + 0.5);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
}

/** How `drawLastPriceTag` fills its tag and what it adds under the price. */
export interface LastPriceTagOptions {
  colors?: LastPriceColors;
  /** The bar-close countdown, as a second row, when it is visible. */
  countdown?: BarCountdownOptions | undefined;
  /** The strip the tag sits in. Default 'right'. */
  side?: 'left' | 'right';
}

/**
 * The last price's filled tag on an axis strip, coloured up or down, with the
 * bar-close countdown under the price when one is given. At the plot edges
 * the tag moves to stay inside; the line keeps the quoted value. Draws nothing
 * for a price off the plot.
 */
export function drawLastPriceTag(
  ctx: CanvasRenderingContext2D,
  priceScale: PriceScale,
  price: number,
  up: boolean,
  layout: PlotLayout,
  dpr: number,
  style: AxisStyle = DEFAULT_AXIS_STYLE,
  { colors = DEFAULT_LAST_PRICE_COLORS, countdown, side = 'right' }: LastPriceTagOptions = {},
): void {
  const y = Math.round(priceScale.priceToY(price) * dpr);
  if (!Number.isFinite(y) || y < 0 || y > layout.plotHeight * dpr) return;
  const color = up ? colors.up : colors.down;
  const xStart = Math.round(layout.plotWidth * dpr);

  ctx.save();
  // The price line stays at the quoted value when an edge tag is shifted to fit.
  const label = priceScale.format(price);
  const withCountdown = countdown !== undefined && countdown.visible === true;
  const priceFont = scaleFont(style.font, dpr);
  ctx.font = priceFont;
  const padX = 6 * dpr;
  const boxH = lastPriceTagHeight(dpr, withCountdown);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  if (side === 'left') {
    const tagY = axisTagY(y, layout.plotHeight * dpr, boxH, side);
    if (tagY !== null) {
      const rows = [{ text: label, font: priceFont, offset: withCountdown ? -boxH / 4 : 0 }];
      if (withCountdown) rows.push({
        text: formatCountdown(barCountdownSeconds(countdown.lastBarTime, countdown.intervalSec, countdown.now())),
        font: scaleFont(style.font, dpr * 0.9), offset: boxH / 4,
      });
      fillLeftTag(ctx, tagY, boxH, rows, layout, dpr, color, colors.text);
    }
  } else if (!withCountdown) {
    fillTag(ctx, xStart, y, boxH, padX, label, color, colors.text);
  } else {
    const clock = formatCountdown(
      barCountdownSeconds(countdown.lastBarTime, countdown.intervalSec, countdown.now()),
    );
    // A size down, so the price stays the headline and the countdown reads as
    // the subtitle it is. `HH:MM:SS` is fixed width, so the tag does not
    // breathe in and out once a second.
    const clockFont = scaleFont(style.font, dpr * 0.9);
    const priceW = ctx.measureText(label).width;
    ctx.font = clockFont;
    const clockW = ctx.measureText(clock).width;
    ctx.fillStyle = color;
    ctx.fillRect(xStart + 1, y - boxH / 2, Math.max(priceW, clockW) + padX * 2, boxH);
    ctx.fillStyle = colors.text;
    // Rows at the quarter points: the price keeps the line the price line
    // points at, and the countdown sits under it inside the same tag.
    ctx.font = priceFont;
    ctx.fillText(label, xStart + 1 + padX, y - boxH / 4);
    ctx.font = clockFont;
    ctx.fillText(clock, xStart + 1 + padX, y + boxH / 4);
  }
  ctx.restore();
}

/** Look of the crosshair's date pill on the time axis. */
interface TimePillStyle {
  /** Pill fill. */
  background: string;
  /** Label colour on that fill. */
  textColor: string;
  /** Optional hairline outline, for a theme where fill and strip sit close together. */
  border?: string;
  /** Corner radius in media px. Default 4. */
  radius?: number;
  /**
   * Opaque under-fill. The pill is drawn on the overlay canvas over tick labels
   * already on the base canvas, so a translucent theme colour would let one show
   * through the other; pass the theme background to cut it out cleanly.
   */
  backplate?: string;
}

/** Vertical inset of the pill from the axis separator, media px. */
const TIME_PILL_INSET = 1;
/** Pill height, media px. Taller than a plain tag so it sits proudly in the strip. */
const TIME_PILL_HEIGHT = 18;

/**
 * The crosshair's date pill on the time axis: a filled rounded pill carrying the
 * hovered timestamp, drawn over the tick row so it reads as a separate object
 * rather than as one more tick label that happens to be a different colour.
 *
 * `centerX` and `topY` are device px, `topY` being the top of the time-axis
 * strip (the axis separator). The pill is clamped at the left edge so a cursor
 * on the first bar does not push half its date off the canvas. The caller owns
 * the label text, and with it the zone it was formatted in.
 */
export function drawTimeAxisPill(
  ctx: CanvasRenderingContext2D,
  label: string,
  centerX: number,
  topY: number,
  dpr: number,
  style: TimePillStyle,
  axisStyle: AxisStyle = DEFAULT_AXIS_STYLE,
): void {
  ctx.save();
  ctx.font = scaleFont(axisStyle.font, dpr);
  const padX = 7 * dpr;
  const h = TIME_PILL_HEIGHT * dpr;
  const w = ctx.measureText(label).width + padX * 2;
  const x = Math.max(0, centerX - w / 2);
  const yTop = topY + TIME_PILL_INSET * dpr;
  const r = (style.radius ?? 4) * dpr;

  ctx.beginPath();
  roundRectPath(ctx, x, yTop, w, h, r);
  if (style.backplate !== undefined) {
    ctx.fillStyle = style.backplate;
    ctx.fill();
  }
  ctx.fillStyle = style.background;
  ctx.fill();
  if (style.border !== undefined) {
    ctx.strokeStyle = style.border;
    ctx.lineWidth = Math.max(1, Math.round(dpr));
    ctx.stroke();
  }
  ctx.fillStyle = style.textColor;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, x + w / 2, yTop + h / 2);
  ctx.restore();
}

/** The corner session clock. Absent or `visible: false` leaves the corner empty. */
export interface SessionClockOptions {
  /** Draw the clock. Unset or false draws nothing at all. */
  visible?: boolean;
  /** UTC seconds now. Never `Date.now()` reached for here, see `ClockSource`. */
  now: ClockSource;
  /** IANA zone the clock reads in; unset means the shipped default. */
  timezone?: string;
  /** Second row carrying the zone's offset from UTC. Default true. */
  showOffset?: boolean | undefined;
}

/**
 * A zone's offset from UTC, written the way a trading desk writes it: `UTC+5:30`,
 * `UTC-4`, and plain `UTC` at zero. Minutes appear only when there are any, so
 * the common whole-hour zones stay short in a corner that has no room to spare.
 */
export function formatUtcOffset(offsetSeconds: number): string {
  const minutes = Math.round(offsetSeconds / 60);
  if (minutes === 0) return 'UTC';
  const abs = Math.abs(minutes);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return `UTC${minutes < 0 ? '-' : '+'}${h}${m === 0 ? '' : `:${pad2(m)}`}`;
}

/**
 * A live wall clock in the corner where the price axis meets the time axis: the
 * one rectangle on the chart that no series, tick or tag ever occupies.
 *
 * Formatted in the chart's configured zone, so a trader on a New York chart
 * reads New York's clock and not their laptop's, with the zone's offset under it
 * to say which clock that is. The offset is read at the instant on the clock,
 * which is what makes it right on both sides of a DST changeover.
 *
 * Coordinates come from `layout` and are plot-relative, matching `drawPriceAxis`.
 */
export function drawSessionClock(
  ctx: CanvasRenderingContext2D,
  layout: PlotLayout,
  dpr: number,
  opts: SessionClockOptions,
  style: AxisStyle = DEFAULT_AXIS_STYLE,
): void {
  if (opts.visible !== true) return;
  // No time axis means no corner: `PlotLayout` zeroes the strip when it is
  // hidden, and painting a clock into the plot instead would be worse than none.
  if (layout.timeAxisHeight <= 0 || layout.priceAxisWidth <= 0) return;
  const nowSeconds = opts.now();
  if (!Number.isFinite(nowSeconds)) return;
  const t = Math.floor(nowSeconds);

  // Same guard as the time axis: an unknown zone costs a wrong-zone clock, never
  // a throw out of the render loop.
  const zone = opts.timezone === undefined || opts.timezone === DEFAULT_TIMEZONE
    || !isValidTimezone(opts.timezone)
    ? DEFAULT_TIMEZONE
    : opts.timezone;
  const defaultZone = zone === DEFAULT_TIMEZONE;
  const clock = defaultZone ? formatIstTimeSeconds(t) : formatZonedTimeSeconds(t, zone);
  // The default zone keeps the frozen offset arithmetic the rest of the file
  // uses for it, so the shipped clock never depends on the host's ICU build.
  const offset = defaultZone ? IST_OFFSET_SECONDS : zoneOffsetSeconds(t, zone);

  const cx = Math.round((layout.plotWidth + layout.priceAxisWidth / 2) * dpr);
  const top = Math.round(layout.plotHeight * dpr);
  const h = layout.timeAxisHeight * dpr;
  // Two rows need roughly twenty media px of strip. In anything shorter the
  // offset would be clipped, and half an offset is worse than none.
  const twoRows = opts.showOffset !== false && layout.timeAxisHeight >= 20;

  ctx.save();
  ctx.fillStyle = style.textColor;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = scaleFont(style.font, dpr);
  if (twoRows) {
    ctx.fillText(clock, cx, top + h * 0.3);
    ctx.font = scaleFont(style.font, dpr * 0.82);
    ctx.fillText(formatUtcOffset(offset), cx, top + h * 0.74);
  } else {
    ctx.fillText(clock, cx, top + h / 2);
  }
  ctx.restore();
}

export function scaleFont(font: string, dpr: number): string {
  // Multiply the leading "<n>px" by dpr; leave the rest of the font string intact.
  //
  // The digit runs are BOUNDED deliberately. `\d+(?:\.\d+)?px` is quadratic: on a
  // long run of digits that is not followed by `px`, the engine retries from
  // every start position and backtracks the whole run each time. A font string
  // is normally the host's own constant, but it can also arrive from a restored
  // chart layout, and a layout is shareable, so it is not necessarily the host's
  // own text. Five integer digits and four decimals covers every real font size
  // and makes the work linear.
  return font.replace(
    /(^|[^\d.])(\d{1,5}(?:\.\d{1,4})?)px/,
    (_, pre: string, px: string) => `${pre}${Number(px) * dpr}px`,
  );
}
