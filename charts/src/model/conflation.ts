/**
 * OHLC-preserving conflation (ARCHITECTURE.md §4.4): what a zoomed-out series
 * pass draws instead of one mark per bar.
 *
 * Once bars are narrower than the stick a candle is drawn with, several of them
 * land in the same device-pixel column, and drawing each one paints the same
 * pixels over and over: 200,000 bars on a 1,000 px plot put two hundred marks
 * in every column where one would do. The level of detail at the end of this
 * file merges what shares a column into one OHLC-preserving stick (open =
 * first, close = last, high = max, low = min, volume = sum; never a lossy
 * average), so a frame costs the plot's width rather than the history's
 * length. It is on by default (`conflate`) and inert above its threshold: a
 * chart zoomed in far enough that every bar has a column of its own paints
 * exactly what it always did.
 *
 * The group helpers (`conflationGroupSize`, `conflateBars`, `conflateItems`,
 * `mergeBars`) merge fixed-size groups, for a host that downsamples bars
 * itself; the pane merges by column.
 */
import type { Bar } from './bar';

/**
 * How many source bars to merge per drawn bar. Returns 1 (no conflation) while
 * each bar is at least `minPx` wide; otherwise ceil(minPx / barWidthPx) scaled
 * by `factor` (higher = more aggressive smoothing).
 */
export function conflationGroupSize(barSpacing: number, dpr: number, minPx = 0.5, factor = 1): number {
  const widthPx = barSpacing * dpr;
  if (widthPx <= 0) return 1;
  const threshold = minPx * Math.max(1, factor);
  if (widthPx >= threshold) return 1;
  return Math.max(1, Math.ceil(threshold / widthPx));
}

/** Merge a single group of bars into one OHLC-preserving bar (uses the first bar's time). */
export function mergeBars(group: readonly Bar[]): Bar {
  // A group holds one bar at least: the conflation helpers never make an empty
  // one, and an empty one has no time to take, so it throws as it always has.
  const first = group[0]!;
  let high = first.high;
  let low = first.low;
  let volume = first.volume ?? 0;
  let hasVolume = first.volume !== undefined;
  // Open interest is a level, not a flow: the merged bar's is the last one in
  // the group, never the sum. Summing it would read as plausible and be wrong
  // by a factor of the group size.
  let oi = first.oi;
  for (let i = 1; i < group.length; i++) {
    const b = group[i]!;
    if (b.high > high) high = b.high;
    if (b.low < low) low = b.low;
    if (b.volume !== undefined) { volume += b.volume; hasVolume = true; }
    if (b.oi !== undefined) oi = b.oi;
  }
  const merged: Bar = {
    time: first.time,
    open: first.open,
    high,
    low,
    close: group[group.length - 1]!.close,
  };
  if (hasVolume) merged.volume = volume;
  if (oi !== undefined) merged.oi = oi;
  return merged;
}

/** Conflate a bar series into groups of `groupSize` (identity when groupSize ≤ 1). */
export function conflateBars(bars: readonly Bar[], groupSize: number): Bar[] {
  if (groupSize <= 1) return bars.slice();
  const out: Bar[] = [];
  for (let i = 0; i < bars.length; i += groupSize) {
    out.push(mergeBars(bars.slice(i, i + groupSize)));
  }
  return out;
}

/** Conflate already-projected draw items: merge bars and place x at the group centre. */
export function conflateItems<T extends { x: number; bar: Bar }>(items: readonly T[], groupSize: number): { x: number; bar: Bar }[] {
  if (groupSize <= 1) return items.map((it) => ({ x: it.x, bar: it.bar }));
  const out: { x: number; bar: Bar }[] = [];
  for (let i = 0; i < items.length; i += groupSize) {
    const group = items.slice(i, i + groupSize);
    const x = group.reduce((s, it) => s + it.x, 0) / group.length;
    out.push({ x, bar: mergeBars(group.map((it) => it.bar)) });
  }
  return out;
}

// ── Level of detail by column ───────────────────────────────────────────────

/**
 * How the level of detail treats a series type while bars share columns, or
 * null for a type it leaves alone.
 *
 * `ohlc`: the types that draw each bar's range as a stick (candles, OHLC and
 * high-low bars). Everything in a column merges into one stick that keeps the
 * column's open, high, low and close, so the range drawn is the range traded.
 *
 * The types that draw a line through one value per bar keep real bars instead:
 * a merged bar would keep only the last close and lose every peak before it,
 * and a line joined across the whitespace a merge drops would bridge a gap.
 * They also keep their own colours that way.
 *
 * `line`: lines, steps, areas and baselines keep the first, the lowest, the
 * highest and the last bar of each unbroken run in a column. A line through
 * those four covers the pixels the line through every bar covers, and enters
 * and leaves the column where it did. A gap survives as one whitespace bar.
 *
 * `band`: the HLC area is a line through the closes over a band from the highs
 * to the lows, so it keeps what `line` keeps and the bars with the run's
 * highest high and lowest low as well, so its close line, both edges of its
 * band and its gaps reach the pixels they reach with every bar drawn.
 *
 * `column`: columns and histograms keep a column's lowest and highest bar.
 * Each is drawn from its base, so those two cover every pixel the rest would.
 *
 * Anything else, a host's renderer or the transform tier's, may read fields or
 * neighbours a merge cannot know about, and is drawn in full.
 */
export type LodKind = 'ohlc' | 'line' | 'band' | 'column';

const LOD_KINDS: ReadonlyMap<string, LodKind> = new Map<string, LodKind>([
  ['candlestick', 'ohlc'], ['hollow-candle', 'ohlc'], ['volume-candle', 'ohlc'],
  ['bar', 'ohlc'], ['high-low', 'ohlc'], ['hlc-area', 'band'],
  ['line', 'line'], ['line-markers', 'line'], ['step', 'line'], ['area', 'line'], ['baseline', 'line'],
  ['column', 'column'], ['histogram', 'column'],
]);

export function lodKind(type: string): LodKind | null {
  return LOD_KINDS.get(type) ?? null;
}

/**
 * How wide one mark of `kind` is at this zoom, in device px. A candle's stick
 * and an OHLC bar's range are a wick wide, `floor(dpr)` (one pixel below a
 * ratio of two). A column or histogram bar is one pixel once bars are under a
 * CSS px, and a line or a band's edge has no width to speak of, so all are one.
 */
function stickWidth(kind: LodKind, dpr: number): number {
  return kind === 'ohlc' ? Math.max(1, Math.floor(dpr)) : 1;
}

/**
 * Width in device px of one level-of-detail column: one mark of `kind`, times
 * `factor`. A mark then fills its column exactly and the next one starts where
 * it ends, so nothing is painted twice and no pixel is left out.
 */
export function lodColumnWidth(dpr: number, factor = 1, kind: LodKind = 'ohlc'): number {
  const f = Number.isFinite(factor) && factor > 1 ? factor : 1;
  return Math.max(1, Math.round(stickWidth(kind, dpr) * f));
}

/**
 * Whether two bars can share a column: the bar spacing is under one column.
 * The pane asks it once per frame with a candle's column, so every series
 * crosses together: at the default factor under about one CSS px (exactly one
 * at a whole ratio). At or above it every bar keeps a column of its own and
 * the frame is drawn bar for bar, as it always was.
 */
export function lodActive(barSpacing: number, dpr: number, columnWidth: number): boolean {
  return barSpacing > 0 && barSpacing * dpr < columnWidth;
}

/**
 * The streaming form of the level of detail: fed the visible bars left to
 * right, it hands each column's result to `emit` as soon as the next column
 * starts. Nothing is collected first, so a frame of 200,000 bars holds one
 * column's state rather than 200,000 items, and the merged bars are reused
 * from frame to frame rather than allocated per column. What `emit` receives
 * is valid until the next `begin`.
 */
interface LodColumns {
  /** Start one series' pass for a frame, in columns `lodColumnWidth(dpr, factor, kind)` wide. */
  begin(kind: LodKind, dpr: number, factor: number): void;
  /** Feed the next visible bar, centred at media-px `x`. */
  push(x: number, bar: Bar): void;
  /** Close the last column. */
  end(): void;
}

/** A merged stick: every optional field of a bar present, undefined when unset. */
interface MergedBar extends Omit<Bar, 'volume' | 'oi' | 'color' | 'wickColor' | 'borderColor'> {
  volume: number | undefined; oi: number | undefined;
  color: string | undefined; wickColor: string | undefined; borderColor: string | undefined;
}

/**
 * Build a `LodColumns`. A closure rather than a class: its state is some thirty
 * numbers and references, and as locals they cost the bundle a letter each.
 */
export function createLodColumns(emit: (x: number, bar: Bar) => void): LodColumns {
  let kind: LodKind = 'ohlc', dpr = 1, column = 1, stick = 1, current = NaN;
  /** Merged bars, reused across frames; `used` of them hold this frame's sticks. */
  const merged: MergedBar[] = [];
  let used = 0;
  // The open OHLC stick.
  let any = false, time = 0, open = NaN, high = NaN, low = NaN, close = NaN, volume = 0, hasVolume = false;
  let oi: number | undefined, color: string | undefined, wickColor: string | undefined, borderColor: string | undefined;
  // The open run of values: its first, lowest, highest and last bars with their x.
  let first: Bar | null = null, firstX = 0, last: Bar | null = null, lastX = 0;
  let lowBar: Bar | null = null, lowX = 0, lowAt = 0, highBar: Bar | null = null, highX = 0, highAt = 0, seq = 0;
  // A band's run also keeps its highest high and lowest low, and where its first and last came.
  let topBar: Bar | null = null, topX = 0, topAt = 0, bottomBar: Bar | null = null, bottomX = 0, bottomAt = 0;
  let firstAt = 0, lastAt = 0;
  /** A band run's kept bars in arrival order, reused from column to column. */
  const keptAt: number[] = [], keptX: number[] = [], keptBar: Bar[] = [];
  let kept = 0;
  /** A gap has been emitted and no value has followed it yet. */
  let inGap = false;

  /** Put a bar among the band run's kept ones by arrival, once however many extremes it holds. */
  const keep = (at: number, x: number, bar: Bar): void => {
    // The run's `kept` entries lead each list, so every read here is in range.
    let i = kept;
    while (i > 0 && keptAt[i - 1]! > at) i--;
    if (i > 0 && keptAt[i - 1] === at) return;
    for (let j = kept; j > i; j--) { keptAt[j] = keptAt[j - 1]!; keptX[j] = keptX[j - 1]!; keptBar[j] = keptBar[j - 1]!; }
    keptAt[i] = at; keptX[i] = x; keptBar[i] = bar;
    kept++;
  };

  const flushOhlc = (): void => {
    if (!any) return;
    any = false;
    let bar = merged[used];
    if (bar === undefined) {
      // Every optional field present from the start, so writing one later
      // never changes the object's shape.
      bar = { time: 0, open: 0, high: 0, low: 0, close: 0, volume: undefined, oi: undefined, color: undefined, wickColor: undefined, borderColor: undefined };
      merged.push(bar);
    }
    used++;
    bar.time = time;
    bar.open = open;
    bar.high = high;
    bar.low = low;
    bar.close = close;
    bar.volume = hasVolume ? volume : undefined;
    bar.oi = oi;
    bar.color = color;
    bar.wickColor = wickColor;
    bar.borderColor = borderColor;
    // The stick sits on its column, centred when a factor widens the column
    // past one stick, so consecutive sticks tile.
    const left = current * column + ((column - stick) >> 1);
    emit((left + (stick >> 1)) / dpr, bar as Bar); // a bar whose unset fields read as absent
  };

  /**
   * Emit the open run in drawing order, each bar once: its first, lowest,
   * highest and last for a line, those and its highest high and lowest low for
   * a band, its lowest and highest for columns.
   */
  const flushRun = (): void => {
    if (first === null) return;
    const runFirst = first;
    first = null;
    if (kind === 'band') {
      kept = 0;
      keep(firstAt, firstX, runFirst);
      keep(lowAt, lowX, lowBar as Bar);
      keep(highAt, highX, highBar as Bar);
      keep(topAt, topX, topBar as Bar);
      keep(bottomAt, bottomX, bottomBar as Bar);
      keep(lastAt, lastX, last as Bar);
      for (let i = 0; i < kept; i++) emit(keptX[i]!, keptBar[i]!);
      return;
    }
    const lowFirst = lowAt <= highAt;
    const a = (lowFirst ? lowBar : highBar) as Bar, ax = lowFirst ? lowX : highX;
    const b = (lowFirst ? highBar : lowBar) as Bar, bx = lowFirst ? highX : lowX;
    if (kind === 'column') {
      emit(ax, a);
      if (b !== a) emit(bx, b);
      return;
    }
    emit(firstX, runFirst);
    if (a !== runFirst) emit(ax, a);
    if (b !== runFirst && b !== a) emit(bx, b);
    if (last !== runFirst && last !== a && last !== b) emit(lastX, last as Bar);
  };

  const flush = (): void => { if (kind === 'ohlc') flushOhlc(); else flushRun(); };

  const pushOhlc = (bar: Bar): void => {
    // A whitespace bar has no price to merge; it only occupies its slot.
    if (!Number.isFinite(bar.close)) return;
    const h = bar.high, l = bar.low;
    if (!any) {
      any = true;
      time = bar.time;
      open = bar.open;
      high = h;
      low = l;
      volume = 0;
      hasVolume = false;
      oi = undefined;
    } else {
      // A non-finite field is skipped rather than allowed to poison the stick:
      // NaN compares false both ways, so a plain max would keep it for good.
      if (h === h && !(high >= h)) high = h;
      if (l === l && !(low <= l)) low = l;
    }
    close = bar.close;
    if (bar.volume !== undefined) { volume += bar.volume; hasVolume = true; }
    // Open interest is a level: the column's is its last reading, never a sum.
    if (bar.oi !== undefined) oi = bar.oi;
    // The stick shows the column's close, so it wears the colours of the bar
    // that closed it: a study that colours bars by trend keeps its colours.
    color = bar.color;
    wickColor = bar.wickColor;
    borderColor = bar.borderColor;
  };

  const pushValue = (x: number, bar: Bar): void => {
    const v = bar.close;
    if (!Number.isFinite(v)) {
      // Nothing joins one column bar to the next, so a gap between them is
      // nothing to keep.
      if (kind === 'column') return;
      // A gap breaks a line, so it has to survive, but one stands for the
      // whole run: a stretch of whitespace draws nothing either way.
      flushRun();
      if (!inGap) { inGap = true; emit(x, bar); }
      return;
    }
    inGap = false;
    const at = seq++;
    if (first === null) {
      first = bar; firstX = x; firstAt = at;
      lowBar = bar; lowX = x; lowAt = at;
      highBar = bar; highX = x; highAt = at;
      topBar = bar; topX = x; topAt = at;
      bottomBar = bar; bottomX = x; bottomAt = at;
    } else {
      // Strict comparisons: the earliest of equal extremes stands, so a flat
      // run keeps its first bar and adds nothing.
      if (v < (lowBar as Bar).close) { lowBar = bar; lowX = x; lowAt = at; }
      if (v > (highBar as Bar).close) { highBar = bar; highX = x; highAt = at; }
      if (kind === 'band') {
        // A missing high or low is passed over, and one missing on the bar
        // kept so far gives way to the first that has it.
        const h = bar.high, l = bar.low;
        if (h === h && !((topBar as Bar).high >= h)) { topBar = bar; topX = x; topAt = at; }
        if (l === l && !((bottomBar as Bar).low <= l)) { bottomBar = bar; bottomX = x; bottomAt = at; }
      }
    }
    last = bar;
    lastX = x;
    lastAt = at;
  };

  return {
    begin(k: LodKind, ratio: number, factor: number): void {
      kind = k;
      dpr = ratio;
      column = lodColumnWidth(ratio, factor, k);
      stick = stickWidth(k, ratio);
      current = NaN;
      used = 0;
      any = false;
      first = null;
      inGap = false;
      seq = 0;
    },
    push(x: number, bar: Bar): void {
      // The column holding the middle pixel of the bar's stick: the renderers
      // round the centre to a device pixel and start the stick half a stick to
      // its left. A stick as wide as a column straddles two, and the one with
      // its middle holds most of it; read from the left edge instead, a
      // three-pixel stick went to the column holding one of its pixels and was
      // drawn two pixels from its bar.
      const c = Math.floor((Math.round(x * dpr) - (stick >> 1) + ((stick - 1) >> 1)) / column);
      if (c !== current) {
        flush();
        current = c;
      }
      if (kind === 'ohlc') pushOhlc(bar);
      else pushValue(x, bar);
    },
    end(): void {
      flush();
      current = NaN;
    },
  };
}
