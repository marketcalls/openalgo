import { describe, expect, it } from 'vitest';
import { generateBars, getSeriesTransform, registeredSeriesTransforms, type Bar, type SeriesTransformRun } from '../src/index';
import {
  registerTransformChartTypes, runTransform, HeikinAshiTransform, RenkoTransform, RangeBarsTransform,
  LineBreakTransform, PointFigureTransform, KagiTransform, type ISeriesTransform,
} from '../src/transform/index';

registerTransformChartTypes();

/** A seeded random walk that trades like a stock: one-minute bars from a fixed start. */
const walk = (count: number): Bar[] => generateBars(1_700_000_000, count, 60);

/**
 * The forming revisions a live feed sends for one bar, ending on the bar
 * itself: the open first, then the range widening while the close wanders,
 * the way ticks arrive. Deterministic, so a failure names one sequence.
 */
function revisions(bar: Bar, seed: number): Bar[] {
  let s = seed >>> 0 || 1;
  const next = (): number => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 0xffffffff; };
  const out: Bar[] = [];
  let high = bar.open, low = bar.open;
  for (let k = 0; k < 4; k++) {
    const close = bar.low + (bar.high - bar.low) * next();
    high = Math.max(high, close); low = Math.min(low, close);
    out.push({ time: bar.time, open: bar.open, high, low, close, volume: Math.round((bar.volume ?? 0) * (k + 1) / 5) });
  }
  out.push(bar);
  return out;
}

/** The source bar each element of a batch run formed on; a flushed element maps to the newest bar. */
function referenceIndex(make: () => ISeriesTransform, bars: readonly Bar[]): number[] {
  const t = make();
  const out: number[] = [];
  bars.forEach((bar, i) => { for (let k = t.push(bar).length; k > 0; k--) out.push(i); });
  for (let k = t.flush?.().length ?? 0; k > 0; k--) out.push(bars.length - 1);
  return out;
}

type Case = [type: string, options: Record<string, number | string>, make: () => ISeriesTransform];
const CASES: Case[] = [
  ['heikin-ashi', {}, () => new HeikinAshiTransform()],
  ['renko', { boxSize: 0.5 }, () => new RenkoTransform({ boxSize: 0.5 })],
  ['range-bars', { range: 1.2 }, () => new RangeBarsTransform({ range: 1.2 })],
  ['line-break', { lines: 3 }, () => new LineBreakTransform({ lines: 3 })],
  ['point-figure', { boxSize: 0.5, reversal: 3 }, () => new PointFigureTransform({ boxSize: 0.5, reversal: 3 })],
  ['point-figure', { mode: 'atr', atrPeriod: 10, reversal: 2, method: 'close' },
    () => new PointFigureTransform({ mode: 'atr', atrPeriod: 10, reversal: 2, method: 'close' })],
  ['point-figure', { mode: 'percent', percent: 0.4 }, () => new PointFigureTransform({ mode: 'percent', percent: 0.4 })],
  ['kagi', { reversal: 1 }, () => new KagiTransform({ reversal: 1 })],
];

describe('series transform registry', () => {
  it('registers the six in-chart transforms with their renderers on tier import', () => {
    expect(registeredSeriesTransforms()).toEqual(['heikin-ashi', 'renko', 'range-bars', 'line-break', 'point-figure', 'kagi']);
    expect(['heikin-ashi', 'renko', 'range-bars', 'line-break'].map(type => getSeriesTransform(type).renderer))
      .toEqual(['candlestick', 'candlestick', 'candlestick', 'candlestick']);
    expect(getSeriesTransform('point-figure').renderer).toBe('point-figure');
    expect(getSeriesTransform('kagi').renderer).toBe('kagi');
  });

  it('names a missing transform, and rejects options it does not declare or cannot use', () => {
    expect(() => getSeriesTransform('three-line')).toThrow(/unknown series transform "three-line"/);
    expect(() => getSeriesTransform('renko').create({ boxsize: 2 })).toThrow(/renko option "boxsize"/);
    expect(() => getSeriesTransform('renko').create({ boxSize: -1 })).toThrow(/boxSize/);
    expect(() => getSeriesTransform('line-break').create({ lines: 0 })).toThrow(/lines/);
    expect(() => getSeriesTransform('point-figure').create({ mode: 'volume' })).toThrow(/mode/);
    expect(() => getSeriesTransform('heikin-ashi').create({ boxSize: 1 })).toThrow(/heikin-ashi option "boxSize"/);
  });
});

describe('live transform runs', () => {
  it.each(CASES)('%s %j: incremental equals batch after every forming-bar revision', (type, options, make) => {
    const bars = walk(260);
    const run: SeriesTransformRun = getSeriesTransform(type).create(options);
    run.setData(bars.slice(0, 40));
    expect(run.elements()).toEqual(runTransform(make(), bars.slice(0, 40)));
    for (let i = 40; i < bars.length; i++) {
      for (const tick of revisions(bars[i], i)) {
        const before = run.elements().slice();
        const from = run.update(tick);
        const source = [...bars.slice(0, i), tick];
        expect(run.source()).toEqual(source);
        const batch = runTransform(make(), source);
        expect(run.elements()).toEqual(batch);
        // Everything ahead of `from` is untouched, which is what lets the chart
        // write the tail alone.
        expect(from).toBeGreaterThanOrEqual(0);
        expect(run.elements().slice(0, from)).toEqual(before.slice(0, from));
        const index = run.sourceIndex();
        if (type === 'heikin-ashi') expect(index).toBeNull();
        else expect(index).toEqual(referenceIndex(make, source));
      }
    }
  });

  // The alert documentation says one source bar can add several elements on
  // Renko alone; each other transform completes at most one element per bar.
  it('adds several elements for one new source bar on Renko only, gaps included', () => {
    // Every twenty-fifth bar gaps by a tenth, up or down, the move that completes most at once.
    let shift = 0;
    const bars = walk(600).map((bar, i) => {
      if (i % 25 === 0) shift += (i % 50 === 0 ? 1 : -1) * bar.close * 0.1;
      return { ...bar, open: bar.open + shift, high: bar.high + shift, low: bar.low + shift, close: bar.close + shift };
    });
    for (const [type, options] of CASES) {
      const run = getSeriesTransform(type).create(options);
      run.setData(bars.slice(0, 1));
      let most = 0;
      for (const bar of bars.slice(1)) {
        const before = run.elements().length;
        run.update(bar);
        most = Math.max(most, run.elements().length - before);
      }
      if (type === 'renko') expect(most, type).toBeGreaterThan(1);
      else expect(most, `${type} ${JSON.stringify(options)}`).toBeLessThanOrEqual(1);
    }
  });

  it('keeps every element strictly increasing in time, so each owns one logical index', () => {
    for (const [type, options] of CASES) {
      const run = getSeriesTransform(type).create(options);
      run.setData(walk(400));
      const times = run.elements().map(bar => bar.time);
      for (let i = 1; i < times.length; i++) expect(times[i]).toBeGreaterThan(times[i - 1]);
    }
  });

  it('pages older history in with the same sizes and matches a batch over the whole history', () => {
    const bars = walk(300);
    const run = getSeriesTransform('renko').create({});
    run.setData(bars.slice(150));
    const box = boxOf(run.elements());
    run.prepend(bars.slice(0, 150));
    expect(run.source()).toEqual(bars);
    // The size resolved at the load stands: paging history in must not resize every brick.
    expect(run.elements()).toEqual(runTransform(new RenkoTransform({ boxSize: box }), bars));
  });

  it('sizes an omitted box from the loaded history, once per load', () => {
    const bars = walk(300);
    const high = Math.max(...bars.map(bar => bar.high)), low = Math.min(...bars.map(bar => bar.low));
    const box = Number(((high - low) / 40).toPrecision(2));
    const run = getSeriesTransform('renko').create({});
    run.setData(bars);
    expect(run.elements()).toEqual(runTransform(new RenkoTransform({ boxSize: box }), bars));
    // Ticks never resize it, however far they move the range.
    const last = bars[bars.length - 1];
    run.update({ ...last, time: last.time + 60, high: last.high * 3, close: last.high * 3 });
    expect(boxOf(run.elements())).toBe(box);
    // A new load does.
    const other = bars.map(bar => ({ ...bar, open: bar.open * 10, high: bar.high * 10, low: bar.low * 10, close: bar.close * 10 }));
    run.setData(other);
    expect(boxOf(run.elements())).toBe(Number((box * 10).toPrecision(2)));
    // Range and Kagi take twice the box, as the reference host always did.
    const range = getSeriesTransform('range-bars').create({});
    range.setData(bars);
    expect(range.elements()).toEqual(runTransform(new RangeBarsTransform({ range: box * 2 }), bars));
    const kagi = getSeriesTransform('kagi').create({ reversal: 0 });
    kagi.setData(bars);
    expect(kagi.elements()).toEqual(runTransform(new KagiTransform({ reversal: box * 2 }), bars));
  });

  it('recomputes from history when a correction lands before the forming bar', () => {
    const bars = walk(120);
    const run = getSeriesTransform('line-break').create({});
    run.setData(bars);
    const fixed = { ...bars[60], close: bars[60].close + 5, high: bars[60].high + 5 };
    expect(run.update(fixed)).toBe(0);
    const expected = bars.slice();
    expected[60] = fixed;
    expect(run.source()).toEqual(expected);
    expect(run.elements()).toEqual(runTransform(new LineBreakTransform({ lines: 3 }), expected));
  });

  it('starts from ticks alone when no history was loaded', () => {
    const bars = walk(80);
    const run = getSeriesTransform('renko').create({ boxSize: 0.5 });
    run.setData([]);
    expect(run.elements()).toEqual([]);
    for (const bar of bars) run.update(bar);
    expect(run.elements()).toEqual(runTransform(new RenkoTransform({ boxSize: 0.5 }), bars));
  });
});

describe('Kagi flush', () => {
  // The last reversal is the fourth bar; the line then climbs to the end.
  const bars = [10, 13, 11, 14, 15, 16, 17, 18].map((close, i) => ({ time: 1000 + i * 60, open: close, high: close, low: close, close }));

  it('dates the vertex still forming at the newest bar rather than at time zero', () => {
    const out = runTransform(new KagiTransform({ reversal: 2 }), bars);
    expect(out[out.length - 1]).toMatchObject({ time: 1000 + 7 * 60, close: 18 });
  });

  it('dates it at the newest bar for a host that pushes and flushes itself, with no batch run to bump the time', () => {
    const kagi = new KagiTransform({ reversal: 2 });
    for (const bar of bars) kagi.push(bar);
    expect(kagi.flush()).toEqual([{ time: 1000 + 7 * 60, open: 18, high: 18, low: 18, close: 18, volume: 1 }]);
  });
});

function boxOf(bricks: readonly Bar[]): number {
  const sizes = new Set(bricks.map(bar => Number(Math.abs(bar.close - bar.open).toPrecision(6))));
  expect(sizes.size).toBe(1);
  return [...sizes][0];
}
