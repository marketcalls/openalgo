import { darkTheme } from '../src/theme';
import { describe, it, expect } from 'vitest';
import { computeVolumeProfile } from '../src/profile/volume-profile';
import { computeTpo } from '../src/profile/tpo';
import {
  computeFootprint, diagonalImbalances, cumulativeDelta, stackedImbalances, type ClassifiedTrade,
} from '../src/profile/footprint';
import { HorizontalProfile } from '../src/profile/profile-primitive';
import { Footprint, compactVol } from '../src/profile/footprint-primitive';
import { FootprintAggregator } from '../src/profile/footprint-aggregator';
import { priceBuckets } from '../src/profile/profile-model';
import type { Bar } from '../src/model/bar';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';

const bar = (time: number, o: number, h: number, l: number, c: number, v: number): Bar => ({ time, open: o, high: h, low: l, close: c, volume: v });

describe('priceBuckets', () => {
  it('spans inclusive low to high on the tick grid', () => {
    expect(priceBuckets(100, 100.2, 0.05)).toEqual([100, 100.05, 100.1, 100.15, 100.2]);
  });

  // A negative step walked the loop away from its end, growing the array
  // until memory ran out; zero and NaN already returned no buckets.
  it('returns no buckets for a step that is not a positive finite number', () => {
    for (const step of [-1, -0.05, 0, NaN, Infinity, -Infinity]) expect(priceBuckets(100, 105, step)).toEqual([]);
  });

  // A walk from low to high by step never ended when the step no longer moved
  // a price that large, or a price ran past the largest number.
  it('returns no buckets for a range the numbers cannot step through, instead of walking forever', () => {
    expect(priceBuckets(1e17, 1e17 + 1000, 1)).toEqual([]);
    expect(priceBuckets(-1e17 - 1000, -1e17, 1)).toEqual([]);
    expect(priceBuckets(100, Infinity, 0.05)).toEqual([]);
    expect(priceBuckets(1.7e308, Number.MAX_VALUE, 1e307)).toEqual([]);
    expect(priceBuckets(NaN, 105, 0.05)).toEqual([]);
    // A reversed range has no buckets, as before.
    expect(priceBuckets(105, 100, 0.05)).toEqual([]);
  });

  it('leaves the two positional profiles empty on such a tick size instead of hanging', () => {
    const bars = [bar(0, 100, 101, 99, 100.5, 1000), bar(60, 100.5, 102, 100, 101.5, 800)];
    expect(computeVolumeProfile(bars, -0.5)).toEqual({ buckets: [], poc: 0, vah: 0, val: 0, totalVolume: 0 });
    expect(computeTpo(bars, 1, -0.5)).toEqual({ buckets: [], poc: 0, vah: 0, val: 0, ib: { high: 0, low: 0 } });
  });
});

describe('Volume Profile', () => {
  it('finds POC at the most-traded price and a 70% value area', () => {
    // bar that concentrates huge volume in a tight band around 100
    const bars = [
      bar(1, 100, 100.1, 99.9, 100, 100),
      bar(2, 100, 100.05, 99.95, 100, 5000), // dominant volume near 100
      bar(3, 101, 102, 100, 101, 100),
    ];
    const vp = computeVolumeProfile(bars, 0.05, 0.7);
    expect(vp.poc).toBeGreaterThanOrEqual(99.95);
    expect(vp.poc).toBeLessThanOrEqual(100.05);
    expect(vp.vah).toBeGreaterThanOrEqual(vp.val);
    // value area holds ~70% of volume
    const vaVol = vp.buckets.filter((b) => b.price <= vp.vah && b.price >= vp.val).reduce((s, b) => s + b.volume, 0);
    expect(vaVol).toBeGreaterThanOrEqual(vp.totalVolume * 0.7 - 1e-6);
  });

  // What the documentation says of an unclamped fraction, case by case.
  it('takes every row above 1, stops at all the volume at 1, and has the POC alone without volume', () => {
    const bars = [bar(0, 100, 100, 100, 100, 10), bar(60, 99, 101, 99, 100, 0)];
    expect(computeVolumeProfile(bars, 1, 70)).toMatchObject({ poc: 100, vah: 101, val: 99 });
    expect(computeVolumeProfile(bars, 1, 1)).toMatchObject({ poc: 100, vah: 100, val: 100 });
    expect(computeVolumeProfile([bar(0, 99, 101, 99, 100, 0)], 1, 70)).toMatchObject({ poc: 101, vah: 101, val: 101, totalVolume: 0 });
  });

  it('handles empty input', () => {
    const vp = computeVolumeProfile([], 0.05);
    expect(vp.buckets).toHaveLength(0);
    expect(vp.totalVolume).toBe(0);
  });
});

describe('TPO / Market Profile', () => {
  it('counts periods at price, derives POC/VA and the initial balance', () => {
    const bars = [
      bar(1, 100, 101, 99, 100, 0), bar(2, 100, 101, 99, 100, 0), // period 0
      bar(3, 100, 100.5, 99.5, 100, 0), bar(4, 100, 100.5, 99.5, 100, 0), // period 1
      bar(5, 103, 104, 102, 103, 0), bar(6, 103, 104, 102, 103, 0), // period 2
    ];
    const tpo = computeTpo(bars, 2, 0.5, 0.7, 2); // 2 bars/period, IB = first 2 periods
    expect(tpo.buckets.length).toBeGreaterThan(0);
    // prices around 100 are touched by 2 periods, so a higher count than the 103 band
    expect(tpo.poc).toBeGreaterThanOrEqual(99.5);
    expect(tpo.poc).toBeLessThanOrEqual(101);
    // IB spans the first two periods' combined range (99 .. 101)
    expect(tpo.ib.high).toBeCloseTo(101);
    expect(tpo.ib.low).toBeCloseTo(99);
  });
});

describe('Footprint & order flow', () => {
  const trades: ClassifiedTrade[] = [
    { price: 100.0, qty: 30, side: 'ask' },
    { price: 100.0, qty: 10, side: 'bid' },
    { price: 100.05, qty: 50, side: 'ask' },
    { price: 99.95, qty: 40, side: 'bid' },
  ];

  it('aggregates bid/ask per price and computes net delta', () => {
    const fp = computeFootprint(1, trades, 0.05);
    const at100 = fp.cells.find((c) => Math.abs(c.price - 100) < 1e-9)!;
    expect(at100.askVol).toBe(30);
    expect(at100.bidVol).toBe(10);
    // delta = Σ(ask − bid) = (30-10) + (50-0) + (0-40) = 20 + 50 - 40 = 30
    expect(fp.delta).toBe(30);
  });

  it('detects diagonal imbalances by ratio', () => {
    // strong ask at 100.05 vs bid at 100.0: buy imbalance
    const fp = computeFootprint(1, trades, 0.05);
    const imb = diagonalImbalances(fp.cells, 3);
    expect(imb.some((i) => i.side === 'buy')).toBe(true);
  });

  it('cumulative delta accumulates across bars', () => {
    const bars = [
      computeFootprint(1, [{ price: 100, qty: 10, side: 'ask' }], 0.05), // +10
      computeFootprint(2, [{ price: 100, qty: 4, side: 'bid' }], 0.05),  // -4
      computeFootprint(3, [{ price: 100, qty: 6, side: 'ask' }], 0.05),  // +6
    ];
    expect(cumulativeDelta(bars)).toEqual([10, 6, 12]);
  });

  it('finds stacked imbalances of minimum length', () => {
    const cells = [
      { price: 100.15, bidVol: 1, askVol: 90 },
      { price: 100.10, bidVol: 1, askVol: 90 },
      { price: 100.05, bidVol: 1, askVol: 90 },
      { price: 100.00, bidVol: 1, askVol: 1 },
    ];
    const stacks = stackedImbalances(cells, 3, 3);
    expect(stacks.length).toBeGreaterThanOrEqual(1);
    expect(stacks[0].side).toBe('buy');
    expect(stacks[0].count).toBeGreaterThanOrEqual(3);
  });
});

describe('profile primitives render', () => {
  function rc(): PrimitiveRenderContext {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, [bar(1, 100, 101, 99, 100, 10), bar(2, 100, 101, 99, 100, 10)]);
    const priceScale = new PriceScale();
    priceScale.setHeight(400);
    // Readable footprint rows need enough real price/column space. The renderer
    // no longer enlarges tiny rows or narrow columns into their neighbours.
    priceScale.setPriceRange({ min: 99.8, max: 100.3 });
    const timeScale = new TimeScale({ barSpacing: 80 });
    timeScale.setWidth(600);
    timeScale.setBaseIndex(dl.baseIndex);
    return { timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme };
  }

  it('HorizontalProfile draws bars + POC/VA lines', () => {
    const hp = new HorizontalProfile({
      buckets: [{ price: 100, value: 50 }, { price: 100.5, value: 20 }, { price: 101, value: 5 }],
      poc: 100, vah: 100.5, val: 100, width: 120, side: 'right', barColor: '#345', vaColor: '#456',
    });
    const { ctx, rec } = makeCtx();
    hp.draw(ctx, rc());
    expect(rec.count('fillRect')).toBeGreaterThan(0);
    expect(rec.count('stroke')).toBe(3); // POC + VAH + VAL
  });

  it('Footprint draws cells aligned to chart bars', () => {
    const r = rc();
    const fp = new Footprint();
    fp.setBars([computeFootprint(1, [{ price: 100, qty: 5, side: 'ask' }, { price: 100, qty: 2, side: 'bid' }], 0.05)]);
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, r);
    expect(rec.count('fillText')).toBeGreaterThan(0);
  });

  it('Footprint fills diagonal imbalances saturated rather than outlining them', () => {
    const r = rc();
    // ask 30 at 100.05 dominates bid 2 one tick below -> a buy imbalance.
    const bars = [computeFootprint(1, [
      { price: 100.05, qty: 30, side: 'ask' },
      { price: 100.0, qty: 2, side: 'bid' },
    ], 0.05)];
    const plain = new Footprint({ tickSize: 0.05, imbalanceRatio: 1e9, statsRows: [] });
    plain.setBars(bars);
    const a = makeCtx();
    plain.draw(a.ctx, r);

    const hot = new Footprint({ tickSize: 0.05, imbalanceRatio: 3, statsRows: [] });
    hot.setBars(bars);
    const b = makeCtx();
    hot.draw(b.ctx, r);

    // Same geometry either way: an outline would have added strokeRect calls.
    expect(b.rec.count('strokeRect')).toBe(0);
    expect(b.rec.count('roundRect')).toBe(a.rec.count('roundRect'));
    // ...but the imbalanced cell is painted a different (saturated) colour.
    const fills = (r2: RecordingContext): (string | undefined)[] =>
      r2.ops.filter((o) => o.type === 'fill').map((o) => o.fillStyle);
    expect(fills(b.rec)).not.toEqual(fills(a.rec));
  });

  it('Footprint grades cell colour by share of the bar peak', () => {
    const r = rc();
    const fp = new Footprint({ tickSize: 0.05, imbalanceRatio: 1e9, statsRows: [] });
    fp.setBars([computeFootprint(1, [
      { price: 100.0, qty: 1, side: 'ask' },
      { price: 100.05, qty: 100, side: 'ask' },
    ], 0.05)]);
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, r);
    const fills = rec.ops.filter((o) => o.type === 'fill').map((o) => o.fillStyle);
    // A quiet row and a peak row must not share a colour.
    expect(new Set(fills).size).toBeGreaterThan(1);
  });

  it('Footprint computes per-bar stats with a running CVD', () => {
    const fp = new Footprint();
    fp.setBars([
      computeFootprint(1, [{ price: 100, qty: 10, side: 'ask' }], 0.05),  // +10
      computeFootprint(2, [{ price: 100, qty: 4, side: 'bid' }], 0.05),   // -4
      computeFootprint(3, [{ price: 100, qty: 6, side: 'ask' }], 0.05),   // +6
    ]);
    const s = fp.stats();
    expect(s.map((x) => x.delta)).toEqual([10, -4, 6]);
    expect(s.map((x) => x.cvd)).toEqual([10, 6, 12]);   // running, not per-bar
    expect(s[0].volume).toBe(10);
    expect(s[0].deltaPct).toBeCloseTo(100, 6);
    expect(s[1].deltaPct).toBeCloseTo(-100, 6);
  });

  it('Footprint draws one stats row per configured metric', () => {
    const r = rc();
    const bars = [computeFootprint(1, [{ price: 100, qty: 5, side: 'ask' }], 0.05)];
    const none = new Footprint({ tickSize: 0.05, statsRows: [] });
    none.setBars(bars);
    const a = makeCtx();
    none.draw(a.ctx, r);

    const four = new Footprint({ tickSize: 0.05, statsRows: ['volume', 'delta', 'deltaPct', 'cvd'] });
    four.setBars(bars);
    const b = makeCtx();
    four.draw(b.ctx, r);
    // Each configured row now has a fixed label as well as its bar value.
    expect(b.rec.count('fillText')).toBe(a.rec.count('fillText') + 8);
  });

  it('Footprint is restylable at runtime instead of needing a rebuild', () => {
    const r = rc();
    const fp = new Footprint({ tickSize: 0.05, statsRows: [] });
    fp.setBars([computeFootprint(1, [{ price: 100, qty: 5, side: 'ask' }], 0.05)]);
    const a = makeCtx();
    fp.draw(a.ctx, r);
    fp.setOptions({ buyColor: '#00ff00' });
    const b = makeCtx();
    fp.draw(b.ctx, r);
    expect(fp.options().buyColor).toBe('#00ff00');
    const fills = (r2: RecordingContext): string =>
      r2.ops.filter((o) => o.type === 'fill').map((o) => o.fillStyle).join('|');
    expect(fills(b.rec)).not.toBe(fills(a.rec));
  });

  it('Footprint drops cell numbers when rows are too short to read', () => {
    const bars = [computeFootprint(1, [
      { price: 100, qty: 5, side: 'ask' }, { price: 100.05, qty: 5, side: 'bid' },
    ], 0.05)];
    const roomy = new Footprint({ tickSize: 0.05, statsRows: [], minTextHeight: 1 });
    roomy.setBars(bars);
    const a = makeCtx();
    roomy.draw(a.ctx, rc());

    const cramped = new Footprint({ tickSize: 0.05, statsRows: [], minTextHeight: 10000 });
    cramped.setBars(bars);
    const b = makeCtx();
    cramped.draw(b.ctx, rc());
    expect(a.rec.count('fillText')).toBeGreaterThan(0);
    expect(b.rec.count('fillText')).toBe(0);   // heatmap only
    expect(b.rec.count('roundRect')).toBeGreaterThan(0);
  });

  it('Footprint drives autoscale so the top and bottom rows are not clipped', () => {
    const fp = new Footprint();
    fp.setBars([computeFootprint(1, [
      { price: 100, qty: 1, side: 'ask' }, { price: 101, qty: 1, side: 'bid' },
    ], 0.5)]);
    expect(fp.autoscaleInfo()).toEqual({ min: 99.75, max: 101.25 });
  });

  it('Footprint hit-tests a column and reports its stats', () => {
    const r = rc();
    const fp = new Footprint({ tickSize: 0.05 });
    fp.setBars([computeFootprint(1, [{ price: 100, qty: 7, side: 'ask' }], 0.05)]);
    const { ctx } = makeCtx();
    fp.draw(ctx, r);                       // hit-testing needs the drawn geometry
    const x = r.timeScale.indexToX(0);
    const hit = fp.hitTest(x, r.priceScale.priceToY(100));
    expect(hit?.externalId).toBe('footprint:1');
    const hover = fp.hoverAt(x, r.priceScale.priceToY(100), r);
    expect(hover?.stats.volume).toBe(7);
    expect(hover?.cell?.askVol).toBe(7);
    expect(fp.hitTest(-500, 50)).toBeNull();
  });

  it('Footprint hoverAt reuses the last draw context when none is passed', () => {
    // Hosts should not have to fabricate a PrimitiveRenderContext to show a tooltip.
    const r = rc();
    const fp = new Footprint({ tickSize: 0.05 });
    fp.setBars([computeFootprint(1, [{ price: 100, qty: 7, side: 'ask' }], 0.05)]);
    const x = r.timeScale.indexToX(0);
    expect(fp.hoverAt(x, r.priceScale.priceToY(100))).toBeNull();  // nothing drawn yet
    const { ctx } = makeCtx();
    fp.draw(ctx, r);
    const hover = fp.hoverAt(x, r.priceScale.priceToY(100));
    expect(hover?.stats.volume).toBe(7);
    expect(hover?.cell?.askVol).toBe(7);
  });

  it('rowTicks widens footprint bricks without changing the tick size', () => {
    // Nifty-style: 0.1 tick, 2-point bricks -> rowTicks 20.
    const trades: ClassifiedTrade[] = [];
    for (let i = 0; i < 60; i++) {
      trades.push({ price: 24000 + i * 0.1, qty: 1, side: i % 2 === 0 ? 'ask' : 'bid' });
    }
    const fine = computeFootprint(1, trades, 0.1);
    const coarse = computeFootprint(1, trades, 0.1, 20);
    expect(fine.cells.length).toBeGreaterThan(50);
    expect(coarse.cells.length).toBeLessThan(6);
    // Rows really are 2 points apart, and no volume was lost in the regrouping.
    expect(Math.abs((coarse.cells[0].price - coarse.cells[1].price) - 2)).toBeLessThan(1e-6);
    const sum = (b: typeof fine) => b.cells.reduce((n, c) => n + c.bidVol + c.askVol, 0);
    expect(sum(coarse)).toBe(sum(fine));
  });

  it('FootprintAggregator buckets ticks onto the rowTicks grid', () => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.1, 20);
    let bar = agg.onTick({ time: 0, price: 24000.1, qty: 5, side: 'ask' }).bar;
    bar = agg.onTick({ time: 1, price: 24000.7, qty: 7, side: 'ask' }).bar;
    // Both prints round onto the same 2-point brick.
    expect(bar.cells).toHaveLength(1);
    expect(bar.cells[0].price).toBe(24000);
    expect(bar.cells[0].askVol).toBe(12);
    // A print a full brick away opens a new row.
    bar = agg.onTick({ time: 2, price: 24002.4, qty: 3, side: 'bid' }).bar;
    expect(bar.cells).toHaveLength(2);
  });

  it('compactVol formats to three significant figures', () => {
    expect(compactVol(4_530_000)).toBe('4.53M');
    expect(compactVol(13_000_000)).toBe('13M');
    expect(compactVol(30_200_000)).toBe('30.2M');
    expect(compactVol(47_100)).toBe('47.1K');
    expect(compactVol(128_000)).toBe('128K');
    expect(compactVol(3_000)).toBe('3K');
    expect(compactVol(-943_000)).toBe('-943K');
    expect(compactVol(512)).toBe('512');
  });
});
