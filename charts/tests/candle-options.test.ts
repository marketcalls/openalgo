/**
 * Candle option coverage (Settings > Symbol): the Body / Borders / Wick colour
 * pairs and their checkboxes, and "Color bars based on previous close". Every
 * assertion reads the recording context, so a flag that is declared but never
 * touches the canvas fails here.
 */
import { describe, it, expect } from 'vitest';
import { drawCandles, optimalBarWidth, type CandleDrawItem, type CandleStyle } from '../src/render/candles';
import type { Bar } from '../src/model/bar';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';
import { fakeDocument } from './helpers/fake-dom';
import { Chart } from '../src/core/chart';
import type { SeriesStyle } from '../src/render/series-style';
import type { SeriesType } from '../src/model/chart-type-registry';

const BS = 8;
const DPR = 1;
const BODY_W = optimalBarWidth(BS, DPR);
const WICK_W = 1; // Math.max(1, Math.floor(dpr))

// Six distinct colours, so a body painted in the wick colour (or an up bar in
// the down pair) is visible in the assertion rather than silently equal.
const UP = { body: '#11aa11', border: '#22bb22', wick: '#33cc33' };
const DOWN = { body: '#aa1111', border: '#bb2222', wick: '#cc3333' };

const STYLE: CandleStyle = {
  upColor: UP.body,
  downColor: DOWN.body,
  borderUpColor: UP.border,
  borderDownColor: DOWN.border,
  wickUpColor: UP.wick,
  wickDownColor: DOWN.wick,
  borderVisible: true,
  wickVisible: true,
};

const bar = (time: number, o: number, h: number, l: number, c: number): Bar =>
  ({ time, open: o, high: h, low: l, close: c, volume: 100 });

const items = (bars: readonly Bar[]): CandleDrawItem[] => bars.map((b, i) => ({ x: 10 + i * 10, bar: b }));
const toY = (v: number): number => 1000 - v;

function paint(data: readonly CandleDrawItem[], style: Partial<CandleStyle> = {}): RecordingContext {
  const { ctx, rec } = makeCtx();
  drawCandles(ctx, data, toY, BS, DPR, { ...STYLE, ...style });
  return rec;
}

// Wicks are WICK_W wide and bodies BODY_W, so width separates the two fills.
const wicks = (rec: RecordingContext): (string | undefined)[] =>
  rec.ops.filter((o) => o.type === 'fillRect' && o.args[2] === WICK_W).map((o) => o.fillStyle);
const bodies = (rec: RecordingContext): (string | undefined)[] =>
  rec.ops.filter((o) => o.type === 'fillRect' && o.args[2] !== WICK_W).map((o) => o.fillStyle);
const outlines = (rec: RecordingContext): (string | undefined)[] =>
  rec.ops.filter((o) => o.type === 'strokeRect').map((o) => o.strokeStyle);
const bodyWidths = (rec: RecordingContext): number[] =>
  rec.ops.filter((o) => o.type === 'fillRect' && o.args[2] !== WICK_W).map((o) => o.args[2]);
// Left edge of each filled body, which identifies the bar it belongs to.
const bodyXs = (rec: RecordingContext): number[] =>
  rec.ops.filter((o) => o.type === 'fillRect' && o.args[2] !== WICK_W).map((o) => o.args[0]);

describe('candle style flags reach the canvas', () => {
  // The width filter above only separates wick from body while they differ.
  it('draws bodies wider than wicks (guards the assertion helpers)', () => {
    expect(BODY_W).toBeGreaterThan(WICK_W);
  });

  const two = items([bar(0, 10, 14, 8, 12), bar(1, 12, 15, 9, 10)]); // up, then down

  it('paints body, border and wick from their own colour pair', () => {
    const rec = paint(two);
    expect(bodies(rec)).toEqual([UP.body, DOWN.body]);
    expect(outlines(rec)).toEqual([UP.border, DOWN.border]);
    expect(wicks(rec)).toEqual([UP.wick, DOWN.wick]);
  });

  it('borderVisible false drops the outline and keeps the body', () => {
    const rec = paint(two, { borderVisible: false });
    expect(outlines(rec)).toEqual([]);
    expect(bodies(rec)).toEqual([UP.body, DOWN.body]);
  });

  it('wickVisible false drops the wick and keeps the body', () => {
    const rec = paint(two, { wickVisible: false });
    expect(wicks(rec)).toEqual([]);
    expect(bodies(rec)).toEqual([UP.body, DOWN.body]);
  });

  it('hollow outlines the up body and still fills (and borders) the down body', () => {
    const rec = paint(two, { hollow: true });
    expect(bodies(rec)).toEqual([DOWN.body]); // the up body is outline only
    // Up outline is the hollow body, down outline is the ordinary border.
    expect(outlines(rec)).toEqual([UP.border, DOWN.border]);
  });

  it('bodyVisible false drops the fill and leaves the outline and wick', () => {
    const rec = paint(two, { bodyVisible: false });
    expect(bodies(rec)).toEqual([]);
    expect(outlines(rec)).toEqual([UP.border, DOWN.border]);
    expect(wicks(rec)).toEqual([UP.wick, DOWN.wick]);
  });

  it('bodyVisible defaults to on when the style does not mention it', () => {
    // Guards the `!== false` reading: undefined must mean painted, or every
    // caller that predates the option loses its candles.
    expect(bodies(paint(two, { bodyVisible: undefined }))).toEqual([UP.body, DOWN.body]);
  });

  it('bodyVisible false keeps the outline below the 3px width guard', () => {
    // The guard exists so a 1px inset outline cannot swallow a narrow FILLED
    // body. With no fill the outline is the candle, so it must survive.
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, two, toY, 2, DPR, { ...STYLE, bodyVisible: false });
    expect(optimalBarWidth(2, DPR)).toBeLessThan(3);
    expect(outlines(rec)).toEqual([UP.border, DOWN.border]);
  });

  it('body and borders both off leaves the wick, which is what was asked for', () => {
    const rec = paint(two, { bodyVisible: false, borderVisible: false });
    expect(bodies(rec)).toEqual([]);
    expect(outlines(rec)).toEqual([]);
    expect(wicks(rec)).toEqual([UP.wick, DOWN.wick]);
  });

  it('hollow with borders off falls back to the body colour instead of vanishing', () => {
    const rec = paint(two, { hollow: true, borderVisible: false });
    expect(outlines(rec)).toEqual([UP.body]); // up candle survives, down gets no border
    expect(bodies(rec)).toEqual([DOWN.body]);
  });

  it('widthScale narrows the body (volume candles)', () => {
    const rec = paint(two, { widthScale: (b) => (b.close >= b.open ? 1 : 0.5) });
    const [full, half] = bodyWidths(rec);
    expect(full).toBe(BODY_W);
    expect(half).toBeLessThan(BODY_W);
  });
});

describe('color bars based on previous close', () => {
  // b1 rises off its own open but closes below b0's close; b2 falls from its
  // own open but closes above b1's close. The two rules disagree on both.
  const data = items([
    bar(0, 98, 106, 94, 100),
    bar(1, 90, 98, 88, 95),
    bar(2, 105, 110, 100, 103),
  ]);

  it('picks the opposite colour to open/close on a bar where the rules disagree', () => {
    const byOpen = bodies(paint(data));
    const byPrev = bodies(paint(data, { colorByPreviousClose: true }));
    expect(byOpen.slice(1)).toEqual([UP.body, DOWN.body]);
    expect(byPrev.slice(1)).toEqual([DOWN.body, UP.body]);
  });

  it('switches body, border and wick together', () => {
    const rec = paint(data, { colorByPreviousClose: true });
    expect(bodies(rec).slice(1)).toEqual([DOWN.body, UP.body]);
    expect(outlines(rec).slice(1)).toEqual([DOWN.border, UP.border]);
    expect(wicks(rec).slice(1)).toEqual([DOWN.wick, UP.wick]);
  });

  it('reaches the hollow decision too, not just the colours', () => {
    // Only the down bar is filled in hollow mode, so its x says which bar the
    // rule called down: b2 (x 30) by open/close, b1 (x 20) by previous close.
    // Body left edge is cx - floor(BODY_W / 2).
    const off = Math.floor(BODY_W / 2);
    expect(bodyXs(paint(data, { hollow: true }))).toEqual([30 - off]);
    expect(bodyXs(paint(data, { hollow: true, colorByPreviousClose: true }))).toEqual([20 - off]);
  });

  it('falls back to open/close on the first drawn bar, which has no previous close', () => {
    const first = items([bar(0, 101, 104, 99, 100)]); // closes below its own open
    expect(bodies(paint(first, { colorByPreviousClose: true }))).toEqual([DOWN.body]);
  });

  it('uses a caller-supplied prevClose for the first drawn bar when there is one', () => {
    const first: CandleDrawItem[] = [{ x: 10, bar: bar(0, 101, 104, 99, 100), prevClose: 99 }];
    // 100 closes above the off-screen bar's 99, so the bar is up despite
    // closing below its own open.
    expect(bodies(paint(first, { colorByPreviousClose: true }))).toEqual([UP.body]);
    expect(wicks(paint(first, { colorByPreviousClose: true }))).toEqual([UP.wick]);
  });

  it('ignores a non-finite reference and colours that bar by open/close', () => {
    const gap: CandleDrawItem[] = [
      { x: 10, bar: { time: 0, open: NaN, high: NaN, low: NaN, close: NaN } },
      { x: 20, bar: bar(1, 90, 98, 88, 95) }, // up by its own open
    ];
    // Comparing against NaN is false, which would paint every bar after a gap
    // down; the second bar must fall back to its own open instead.
    expect(bodies(paint(gap, { colorByPreviousClose: true }))[1]).toBe(UP.body);
  });
});

/**
 * The renderer honouring a flag is only half the wiring: the flag starts life
 * on `SeriesStyle`, and the previous close of the bar left of the visible range
 * is something only the pane can look up. Both halves used to be missing, and
 * both are invisible to a test that calls `drawCandles` directly.
 */
describe('previous-close colouring reaches the chart', () => {
  /** A document whose canvases share one recorder, so a chart paint is readable. */
  function recordingDocument(): { document: Document; rec: RecordingContext } {
    const { ctx, rec } = makeCtx();
    const base = fakeDocument();
    const document = {
      createElement: (tag: string): unknown => {
        const el = base.createElement(tag) as unknown as Record<string, unknown>;
        if (tag === 'canvas') el.getContext = (): unknown => ctx;
        return el;
      },
    } as unknown as Document;
    return { document, rec };
  }

  // Every bar closes above its own open and below the bar before it, so the two
  // colouring rules disagree on every candle, the first drawn one included.
  const falling = Array.from({ length: 40 }, (_, i) => bar(i, 199 - 2 * i, 202 - 2 * i, 196 - 2 * i, 200 - 2 * i));

  /** Body colours of one painted frame, with the range the chart settled on. */
  function paintChart(style: Partial<SeriesStyle>, from: number, type: SeriesType = 'candlestick'): {
    bodies: (string | undefined)[];
    from: number;
  } {
    const { document, rec } = recordingDocument();
    const chart = new Chart(document.createElement('div') as unknown as HTMLElement, {
      document,
      pixelRatio: () => 1,
      shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    chart.addSeries(type, {
      style: { upColor: UP.body, downColor: DOWN.body, borderVisible: false, wickVisible: false, ...style },
    }).setData(falling);
    rec.ops.length = 0; // only the frame the range change paints
    chart.setVisibleLogicalRange({ from, to: falling.length - 1 });
    return {
      bodies: rec.ops
        .filter((o) => o.type === 'fillRect' && (o.fillStyle === UP.body || o.fillStyle === DOWN.body))
        .map((o) => o.fillStyle),
      from: chart.getVisibleLogicalRange().from,
    };
  }

  it('leaves the classic rule alone: every bar closed above its own open', () => {
    const { bodies } = paintChart({}, 20);
    expect(bodies.length).toBeGreaterThan(1);
    expect([...new Set(bodies)]).toEqual([UP.body]);
  });

  it('colours by the previous close when the series style asks for it', () => {
    const { bodies, from } = paintChart({ colorByPreviousClose: true }, 20);
    // The bar left of the range is what the leading candle is quoted against,
    // so nothing may be scrolled off for this to be the whole story.
    expect(from).toBeGreaterThan(0);
    expect([...new Set(bodies)]).toEqual([DOWN.body]);
  });

  it('colours the first bar of history by its own open, having nothing before it', () => {
    const { bodies } = paintChart({ colorByPreviousClose: true }, 0);
    expect(bodies[0]).toBe(UP.body);
    expect([...new Set(bodies.slice(1))]).toEqual([DOWN.body]);
  });

  /**
   * The option lives on `SeriesStyle`, which every series type shares, and an
   * OHLC bar is the type the reference control is named after. It used to be
   * copied into the candle style object and nowhere else, so a bar chart stored
   * the flag and painted as though it were off.
   */
  it.each(['bar', 'high-low'] as const)('honours the flag on a %s series too', (type) => {
    expect([...new Set(paintChart({}, 20, type).bodies)]).toEqual([UP.body]);

    const { bodies, from } = paintChart({ colorByPreviousClose: true }, 20, type);
    expect(from).toBeGreaterThan(0);
    expect([...new Set(bodies)]).toEqual([DOWN.body]);

    // And the first bar of history still has nothing to be quoted against.
    expect(paintChart({ colorByPreviousClose: true }, 0, type).bodies[0]).toBe(UP.body);
  });
});
