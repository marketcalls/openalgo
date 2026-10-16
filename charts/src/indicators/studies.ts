/**
 * Study overlays and panes that sit outside the trend / momentum / volatility
 * buckets: a period pivot frame, a money-flow-gated trailing band, and a plain
 * bar-range pane. Part of the lazy `openalgo-charts/indicators` tier.
 *
 * Written from the published formulas rather than transcribed, per
 * ARCHITECTURE.md 0.1. Warmup slots return `null`, never a guessed value, so a
 * plot that starts one bar early reads as the bug it is.
 */
import { trueRange, rsi, sourceValues, sessionStartFlags, calendarPeriodFlags } from 'openalgo-charts';
import type { Bar, IndicatorDescriptor, IndicatorInput, IndicatorPlot } from 'openalgo-charts';
import { sma, nulls, barsSince, mfiFromFlows } from './calc';
import { windowMean } from './window-mean';
import { num, int, str, flag, src, zoneOf } from './settings';
import { crossesAbove, crossesBelow } from './statistics';
import { shift, shiftFlags } from './series';
import { periodBoundary } from './calendar';

/** A NaN-filled column of the right length, the shape every `calc` here starts from. */
const blank = (n: number): number[] => new Array<number>(n).fill(NaN);

// ── CPR with Floor Pivot ─────────────────────────────────────────────────────

/**
 * The three pivot frames on offer. A frame is only informative when it is
 * coarser than the bars under it, which is what the automatic choice below
 * keys off.
 */
type PivotPeriod = 'daily' | 'weekly' | 'monthly';

const DAY_SECONDS = 86400;


/**
 * Per-bar flags for the first bar of each pivot frame.
 *
 * A daily frame is a trading session, which the bar gaps show directly, so it
 * is read from the data rather than from a calendar. A fixed midnight would be
 * mid-session for every exchange but the one it was chosen for: on New York
 * five-minute bars an IST midnight cuts each session at 18:30 UTC and glues its
 * tail to the next session's head across the overnight gap, which on a month of
 * AAPL turns a 11-point widest day into a 35-point one and drags S3 roughly 37
 * points below where it belongs.
 *
 * The weekly and monthly frames are calendar tests, and the calendar is the
 * chart's zone rather than IST: on America/New_York the same 18:30 UTC seam used
 * to hand the last ninety minutes of a month-end session to the next month's
 * frame, so a monthly pivot opened while the old month was still trading.
 */
function pivotFrameStarts(bars: readonly Bar[], period: PivotPeriod, zone: string): boolean[] {
  const times = bars.map((b) => b.time);
  return period === 'daily'
    ? sessionStartFlags(times, zone)
    : calendarPeriodFlags(times, periodBoundary(period === 'weekly' ? 'week' : 'month', zone));
}

/**
 * Median gap between consecutive bars. Median and not mean: a weekend, a
 * holiday or an outage leaves a handful of gaps orders of magnitude wider than
 * the timeframe, and an average would chase them.
 */
function medianSpacing(bars: readonly Bar[]): number {
  if (bars.length < 2) return 0;
  const gaps: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    const d = bars[i]!.time - bars[i - 1]!.time;
    if (d > 0) gaps.push(d);
  }
  if (gaps.length === 0) return 0;
  gaps.sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)]!;
}

/**
 * One step coarser than the bars themselves: intraday bars get daily pivots,
 * daily bars get weekly, weekly or coarser gets monthly. With nothing to
 * measure (one bar, none, or timestamps that never advance) daily is the safe
 * answer, being the only frame a short series can resolve at all.
 */
function autoPivotPeriod(bars: readonly Bar[]): PivotPeriod {
  const gap = medianSpacing(bars);
  if (gap <= 0 || gap < DAY_SECONDS) return 'daily';
  if (gap < 7 * DAY_SECONDS) return 'weekly';
  return 'monthly';
}

const PERIOD_PREFIX: Record<PivotPeriod, string> = { daily: 'd', weekly: 'w', monthly: 'm' };
const PERIOD_LABEL: Record<PivotPeriod, string> = { daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' };
const PIVOT_PERIODS: readonly PivotPeriod[] = ['daily', 'weekly', 'monthly'];

/** A dotted level, which is what the published script's circle style means here. */
const levelPlot = (key: string, title: string, colorKey: string, radius: number): IndicatorPlot => ({
  key, type: 'line', title, colorKey, style: { markersOnly: true, markerRadius: radius },
});

/**
 * One period's nine plots. Three frames can be on screen at once, so the keys
 * carry a period prefix and cannot collide.
 */
function pivotPlots(period: PivotPeriod): IndicatorPlot[] {
  const p = PERIOD_PREFIX[period];
  const name = PERIOD_LABEL[period];
  const sup = `${p}SupportColor`;
  const res = `${p}ResistanceColor`;
  const cpr = `${p}CprColor`;
  return [
    {
      key: `${p}Pivot`, type: 'line', title: `${name} Pivot`,
      colorKey: `${p}PivotColor`, style: { lineWidth: 2 },
    },
    levelPlot(`${p}S1`, `${name} S1`, sup, 1),
    levelPlot(`${p}S2`, `${name} S2`, sup, 1),
    levelPlot(`${p}S3`, `${name} S3`, sup, 1),
    levelPlot(`${p}R1`, `${name} R1`, res, 1),
    levelPlot(`${p}R2`, `${name} R2`, res, 1),
    levelPlot(`${p}R3`, `${name} R3`, res, 1),
    levelPlot(`${p}Bc`, `${name} Bottom Pivot`, cpr, 2),
    levelPlot(`${p}Tc`, `${name} Top Pivot`, cpr, 2),
  ];
}

/**
 * Per-period colours, all defaulting to the same palette. Identical defaults
 * keep the single-frame case looking exactly as it did, while separate keys let
 * a user pull the frames apart when more than one is on.
 */
function pivotColorInputs(period: PivotPeriod): IndicatorInput[] {
  const p = PERIOD_PREFIX[period];
  const group = PERIOD_LABEL[period];
  return [
    { key: `${p}PivotColor`, type: 'color', label: 'Pivot', default: '#ffeb3b', group },
    { key: `${p}SupportColor`, type: 'color', label: 'Support', default: '#4caf50', group },
    { key: `${p}ResistanceColor`, type: 'color', label: 'Resistance', default: '#ff5252', group },
    { key: `${p}CprColor`, type: 'color', label: 'CPR', default: '#ff9800', group },
    { key: `${p}FillColor`, type: 'color', label: 'CPR Fill', default: '#f47676', group },
  ];
}

/** Which of the nine levels a user has left switched on. Applies to every period. */
interface PivotVisibility {
  pivot: boolean;
  support: boolean;
  resistance: boolean;
  cpr: boolean;
  s1r1: boolean;
}

/**
 * One period's nine columns.
 *
 * The published script pulls the previous higher-timeframe bar through a
 * timeframe request. There is no such request here, so the previous period is
 * derived from the bars themselves: extremes accumulate inside a period and are
 * handed over whole at the boundary. Every bar of a period therefore carries
 * one frozen frame, and the first period has nothing behind it and stays null.
 */
function pivotColumns(
  bars: readonly Bar[],
  period: PivotPeriod,
  active: boolean,
  show: PivotVisibility,
  zone: string,
): Record<string, (number | null)[]> {
  const n = bars.length;
  const pivot = blank(n);
  const s1 = blank(n);
  const s2 = blank(n);
  const s3 = blank(n);
  const r1 = blank(n);
  const r2 = blank(n);
  const r3 = blank(n);
  const bc = blank(n);
  const tc = blank(n);

  if (active) {
    const opensFrame = pivotFrameStarts(bars, period, zone);
    let prevHigh = NaN;
    let prevLow = NaN;
    let prevClose = NaN;
    let curHigh = NaN;
    let curLow = NaN;
    let curClose = NaN;

    for (let i = 0; i < n; i++) {
      if (opensFrame[i]) {
        prevHigh = curHigh;
        prevLow = curLow;
        prevClose = curClose;
      }
      const bar = bars[i]!;
      const high = Number.isFinite(bar.high) ? bar.high : NaN;
      const low = Number.isFinite(bar.low) ? bar.low : NaN;
      // An unknown extreme invalidates this period; only a boundary can seed again.
      const starts = i === 0 || opensFrame[i];
      curHigh = starts ? high : Math.max(curHigh, high);
      curLow = starts ? low : Math.min(curLow, low);
      curClose = bar.close;
      if (!Number.isFinite(prevHigh) || !Number.isFinite(prevLow) || !Number.isFinite(prevClose)) continue;

      const p = (prevHigh + prevLow + prevClose) / 3;
      const width = prevHigh - prevLow;
      const sup1 = 2 * p - prevHigh;
      const res1 = 2 * p - prevLow;
      const bottom = (prevHigh + prevLow) / 2;

      if (show.pivot) pivot[i] = p;
      if (show.support) {
        if (show.s1r1) s1[i] = sup1;
        s2[i] = p - width;
        s3[i] = sup1 - width;
      }
      if (show.resistance) {
        if (show.s1r1) r1[i] = res1;
        r2[i] = p + width;
        r3[i] = res1 + width;
      }
      if (show.cpr) {
        bc[i] = bottom;
        // Mirrored through the pivot, so the pivot always bisects the range.
        tc[i] = 2 * p - bottom;
      }
    }
  }

  const k = PERIOD_PREFIX[period];
  return {
    [`${k}Pivot`]: nulls(pivot),
    [`${k}S1`]: nulls(s1),
    [`${k}S2`]: nulls(s2),
    [`${k}S3`]: nulls(s3),
    [`${k}R1`]: nulls(r1),
    [`${k}R2`]: nulls(r2),
    [`${k}R3`]: nulls(r3),
    [`${k}Bc`]: nulls(bc),
    [`${k}Tc`]: nulls(tc),
  };
}

export const CPR: IndicatorDescriptor = {
  id: 'cpr',
  name: 'CPR with Floor Pivot',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    {
      key: 'pivotMode', type: 'select', label: 'Select Pivot Mode', default: 'auto',
      options: [{ label: 'Auto', value: 'auto' }, { label: 'Manual', value: 'manual' }],
    },
    { key: 'showDaily', type: 'boolean', label: 'Show Daily CPR (Manual)', default: true },
    { key: 'showWeekly', type: 'boolean', label: 'Show Weekly CPR (Manual)', default: false },
    { key: 'showMonthly', type: 'boolean', label: 'Show Monthly CPR (Manual)', default: false },
    { key: 'displaypivots', type: 'boolean', label: 'Plot Pivot', default: true },
    { key: 'displaysupport', type: 'boolean', label: 'Plot Support', default: true },
    { key: 'displayresistance', type: 'boolean', label: 'Plot Resistance', default: true },
    { key: 'displaycpr', type: 'boolean', label: 'Plot CPR', default: true },
    // S1 and R1 are computed in the published script but their plot calls are
    // commented out, so the default here is off: on by choice, never by accident.
    { key: 'displayS1R1', type: 'boolean', label: 'Plot S1 / R1', default: false },
    ...pivotColorInputs('daily'),
    ...pivotColorInputs('weekly'),
    ...pivotColorInputs('monthly'),
  ],
  plots: [...pivotPlots('daily'), ...pivotPlots('weekly'), ...pivotPlots('monthly')],
  // The central range is the point of the study, so it is shaded rather than
  // left as two bare rows of dots. Both edges of an inactive period are null, so
  // that period's band resolves to nothing without a second switch.
  fills: PIVOT_PERIODS.map((period) => {
    const p = PERIOD_PREFIX[period];
    return {
      between: [`${p}Tc`, `${p}Bc`] as [string, string],
      colorUpKey: `${p}FillColor`,
      colorDownKey: `${p}FillColor`,
      opacity: 0.48,
    };
  }),
  calc: (bars, s) => {
    const manual = s.pivotMode === 'manual';
    const auto = autoPivotPeriod(bars);
    const show: PivotVisibility = {
      pivot: flag(s, 'displaypivots', true),
      support: flag(s, 'displaysupport', true),
      resistance: flag(s, 'displayresistance', true),
      cpr: flag(s, 'displaycpr', true),
      s1r1: flag(s, 'displayS1R1', false),
    };
    // Manual lets a user stack frames; Auto resolves to exactly one, so the
    // toggles are read only on the branch that owns them.
    const wanted: Record<PivotPeriod, boolean> = manual
      ? {
        daily: flag(s, 'showDaily', true),
        weekly: flag(s, 'showWeekly', false),
        monthly: flag(s, 'showMonthly', false),
      }
      : { daily: auto === 'daily', weekly: auto === 'weekly', monthly: auto === 'monthly' };

    const zone = zoneOf(s);
    return {
      ...pivotColumns(bars, 'daily', wanted.daily, show, zone),
      ...pivotColumns(bars, 'weekly', wanted.weekly, show, zone),
      ...pivotColumns(bars, 'monthly', wanted.monthly, show, zone),
    };
  },
};

// ── AlphaTrend ───────────────────────────────────────────────────────────────

/**
 * Money Flow Index over an explicit typical-price series, for AlphaTrend.
 *
 * The flows follow the published script: a bar whose typical price is missing
 * compares false both ways and adds no flow, where the MFI study marks it
 * absent. The window sums and the ratio are the MFI study's own
 * (`mfiFromFlows`). First value lands at index `period`: bar 0 has no prior
 * price to compare against, so it contributes no flow in either direction.
 */
function moneyFlowIndex(
  typical: readonly number[],
  volume: readonly number[],
  period: number,
): number[] {
  const n = typical.length;
  const positive = new Array<number>(n).fill(0);
  const negative = new Array<number>(n).fill(0);
  // `volume` runs alongside `typical`, and both sums keep their length.
  for (let i = 1; i < n; i++) {
    const flow = typical[i]! * volume[i]!;
    if (typical[i]! > typical[i - 1]!) positive[i] = flow;
    else if (typical[i]! < typical[i - 1]!) negative[i] = flow;
  }
  // A window with no down-flow pins at 100, which also covers a feed with no
  // volume at all, where both sides are zero.
  return mfiFromFlows(positive, negative, period);
}

export const ALPHATREND: IndicatorDescriptor = {
  id: 'alphatrend',
  name: 'AlphaTrend',
  category: 'Trend',
  placement: 'onchart',
  inputs: [
    { key: 'coeff', type: 'number', label: 'Multiplier', default: 1, min: 0, max: 20, step: 0.1 },
    { key: 'AP', type: 'number', label: 'Common Period', default: 14, min: 1, max: 500, step: 1 },
    { key: 'source', type: 'source', label: 'Source', default: 'close' },
    { key: 'showsignalsk', type: 'boolean', label: 'Show Signals', default: true },
    {
      key: 'novolumedata', type: 'boolean',
      label: 'Change calculation (no volume data)', default: false,
    },
    { key: 'color', type: 'color', label: 'AlphaTrend', default: '#0022fc' },
    { key: 'lagColor', type: 'color', label: 'AlphaTrend Lag', default: '#fc0400' },
    { key: 'risingFillColor', type: 'color', label: 'Rising Fill', default: '#00e60f' },
    { key: 'fallingFillColor', type: 'color', label: 'Falling Fill', default: '#80000b' },
    { key: 'buyColor', type: 'color', label: 'Buy', default: '#0022fc' },
    { key: 'sellColor', type: 'color', label: 'Sell', default: '#880e4f' },
  ],
  plots: [
    { key: 'alphatrend', type: 'line', title: 'AlphaTrend', colorKey: 'color', style: { lineWidth: 3 } },
    { key: 'lagged', type: 'line', title: 'AlphaTrend Lag', colorKey: 'lagColor', style: { lineWidth: 3 } },
  ],
  // Opaque, matching the reference. The two filled columns are the level and the
  // same level two bars back, so the reference direction test is identical to
  // "first column above second", which is what the fill spec already evaluates.
  // Only the tie-break differs: on an equal pair the reference reuses the prior
  // bar comparison, and a fill spec has no state to do that with. Flat stretches
  // of the level, which the clamping recursion produces often, are where the two
  // disagree. Lower the opacity to taste if the band hides too much of the candles.
  fills: [{
    between: ['alphatrend', 'lagged'],
    colorUpKey: 'risingFillColor',
    colorDownKey: 'fallingFillColor',
    opacity: 1,
  }],
  // A crossover is an event with a name, not a column of prices, so it is a
  // marker rather than a plot. The plate hangs off the lagged line it is
  // measured against: buy points up from below it, sell points down from above.
  // The renderer picks the text colour for contrast, which is white on both of
  // these fills.
  markers: ({ bars, values, settings }) => {
    if (settings.showsignalsk === false) return [];
    const buy = values.buySignal ?? [];
    const sell = values.sellSignal ?? [];
    const out = [];
    for (let i = 0; i < bars.length; i++) {
      const b = buy[i];
      if (b !== null && b !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'atPrice' as const, price: b,
          shape: 'labelUp' as const, size: 'tiny' as const,
          color: str(settings, 'buyColor', '#0022fc'), text: 'BUY',
        });
        continue;
      }
      const sg = sell[i];
      if (sg !== null && sg !== undefined) {
        out.push({
          time: bars[i]!.time, position: 'atPrice' as const, price: sg,
          shape: 'labelDown' as const, size: 'tiny' as const,
          color: str(settings, 'sellColor', '#880e4f'), text: 'SELL',
        });
      }
    }
    return out;
  },
  calc: (bars, s) => {
    const n = bars.length;
    const level = blank(n);
    const buy = blank(n);
    const sell = blank(n);
    if (n === 0) return { alphatrend: [], lagged: [], buySignal: [], sellSignal: [] };

    const period = int(s, 'AP', 14);
    const coeff = num(s, 'coeff', 1);
    const noVolume = s.novolumedata === true;
    const showSignals = s.showsignalsk !== false;

    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const closes = bars.map((b) => b.close);
    // A plain average of true range, not Wilder's: the published formula uses
    // the simple mean, and the two diverge by enough to move the band visibly.
    const band = windowMean(trueRange(highs, lows, closes), period);
    const gauge = noVolume
      ? rsi(sourceValues(bars, src(s)), period)
      : moneyFlowIndex(bars.map((b) => (b.high + b.low + b.close) / 3), bars.map((b) => b.volume ?? 0), period);

    // Every series here holds one value per bar.
    for (let i = 0; i < n; i++) {
      // The recursion reads its own previous value through `nz`, so an
      // unresolved slot counts as zero rather than propagating a gap. That is
      // load-bearing: on the first resolved bar the falling branch clamps to
      // zero, and the level stays pinned there until the first rising leg.
      const prev = i > 0 && Number.isFinite(level[i - 1]) ? level[i - 1]! : 0;
      if (!Number.isFinite(band[i]) || !Number.isFinite(gauge[i])) continue;
      const offset = band[i]! * coeff;
      level[i] = gauge[i]! >= 50
        ? Math.max(bars[i]!.low - offset, prev)
        : Math.min(bars[i]!.high + offset, prev);
    }
    const lagged = shift(level, 2);
    // A cross needs both lines real on this bar and the one before.
    const crossUp = crossesAbove(level, lagged);
    const crossDown = crossesBelow(level, lagged);

    if (showSignals) {
      // The published script gates each signal on how long ago the *other* side
      // last fired, so a second buy inside the same leg is swallowed. The two
      // shifted counters are what make that comparison strict; before either
      // side has ever fired they are NaN, and every comparison against NaN is
      // false, which suppresses the very first signal exactly as the original.
      const shiftedUp = shiftFlags(crossUp, 1);
      const shiftedDown = shiftFlags(crossDown, 1);
      const sinceUp = barsSince(crossUp);
      const sinceDown = barsSince(crossDown);
      const sinceShiftedUp = barsSince(shiftedUp);
      const sinceShiftedDown = barsSince(shiftedDown);
      for (let i = 0; i < n; i++) {
        if (crossUp[i] && sinceShiftedUp[i]! > sinceDown[i]!) buy[i] = lagged[i]! * 0.9999;
        else if (crossDown[i] && sinceShiftedDown[i]! > sinceUp[i]!) sell[i] = lagged[i]! * 1.0001;
      }
    }

    return {
      alphatrend: nulls(level),
      lagged: nulls(lagged),
      buySignal: nulls(buy),
      sellSignal: nulls(sell),
    };
  },
};

// ── Range Analysis ───────────────────────────────────────────────────────────

export const RANGE_ANALYSIS: IndicatorDescriptor = {
  id: 'range-analysis',
  name: 'Range Analysis',
  category: 'Volatility',
  placement: 'pane',
  inputs: [
    // The published script leaves the average's plot call commented out, so it
    // ships off and the histogram alone is the default picture.
    { key: 'showAverage', type: 'boolean', label: 'Show Average Range', default: false },
    { key: 'avgLength', type: 'number', label: 'Average Length', default: 3, min: 1, max: 500, step: 1 },
    { key: 'color', type: 'color', label: 'Range', default: '#ff5252' },
    { key: 'avgColor', type: 'color', label: 'Average Range', default: '#2196f3' },
  ],
  plots: [
    { key: 'range', type: 'histogram', title: 'Range', colorKey: 'color', style: { lineWidth: 3, base: 0 } },
    { key: 'avgRange', type: 'line', title: 'Average Range', colorKey: 'avgColor', style: { lineWidth: 2 } },
  ],
  calc: (bars, s) => {
    const range = bars.map((b) => b.high - b.low);
    if (s.showAverage !== true) {
      return { range: nulls(range), avgRange: new Array<number | null>(bars.length).fill(null) };
    }
    return {
      range: nulls(range),
      avgRange: nulls(sma(range, int(s, 'avgLength', 3))),
    };
  },
};

export const STUDY_INDICATORS: readonly IndicatorDescriptor[] = [CPR, ALPHATREND, RANGE_ANALYSIS];
