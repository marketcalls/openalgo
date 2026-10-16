import { describe, expect, it } from 'vitest';
import { computeFootprint, diagonalImbalances, stackedImbalances } from '../src/profile/footprint';
import { FootprintAggregator, type FootprintTick } from '../src/profile/footprint-aggregator';
import type { TickTimeframe } from '../src/feed/tick-aggregator';

const trade = { price: 100.12, qty: 0.5, side: 'ask' as const };

describe('footprint data integrity', () => {
  it('records actual OHLC, trade count and row size independently of rounded cells', () => {
    expect(computeFootprint(60, [trade, { price: 100.19, qty: 2, side: 'bid' }, { price: 99.91, qty: 1, side: 'ask' }], 0.1, 2))
      .toMatchObject({ time: 60, rowSize: 0.2, open: 100.12, high: 100.19, low: 99.91, close: 99.91, tradeCount: 3, delta: -0.5 });
  });

  it('keeps an empty footprint empty without invented OHLC', () => {
    expect(computeFootprint(60, [], 0.1)).toEqual({ time: 60, cells: [], delta: 0, minDelta: 0, maxDelta: 0, rowSize: 0.1, tradeCount: 0 });
    expect(new FootprintAggregator({ mode: 'ticks', count: 1 }, 0.1).current()).toBeNull();
  });

  it('detaches every cell in both update and current snapshots', () => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.1);
    const first = agg.onTick({ ...trade, time: 60 }).bar;
    const read = agg.current()!;
    agg.onTick({ ...trade, time: 61 });
    expect(first.cells[0].askVol).toBe(0.5);
    expect(read.cells[0].askVol).toBe(0.5);
    read.cells[0].bidVol = 900;
    first.cells[0].askVol = 900;
    expect(agg.current()!.cells[0]).toEqual({ price: 100.1, bidVol: 0, askVol: 1 });
  });

  it('updates real OHLC and resets metadata at interval boundaries', () => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.1, 2);
    agg.onTick({ ...trade, time: 60 });
    agg.onTick({ time: 61, price: 100.19, qty: 2, side: 'bid' });
    expect(agg.onTick({ time: 62, price: 99.91, qty: 1, side: 'ask' }).bar).toMatchObject({
      rowSize: 0.2, open: 100.12, high: 100.19, low: 99.91, close: 99.91, tradeCount: 3,
    });
    expect(agg.onTick({ ...trade, time: 120 }).bar).toMatchObject({
      time: 120, open: 100.12, high: 100.12, low: 100.12, close: 100.12, tradeCount: 1,
    });
  });

  it.each<TickTimeframe>([{ mode: 'ticks', count: 1 }, { mode: 'volume', perBar: 0.5 }])(
    'preserves same-time trades without duplicate bar keys in %j', (tf) => {
      const agg = new FootprintAggregator(tf, 0.1);
      agg.onTick({ ...trade, time: 60 });
      expect(agg.onTick({ ...trade, time: 60 })).toMatchObject({ isNew: false, bar: { time: 60, delta: 1, tradeCount: 2 } });
      expect(agg.onTick({ ...trade, time: 61 })).toMatchObject({ isNew: true, bar: { time: 61, delta: 0.5, tradeCount: 1 } });
    },
  );

  it.each([60, 59])('rejects out-of-order live time %s before changing the bar', (time) => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.1);
    agg.onTick({ ...trade, time: 61 });
    const before = agg.current();
    expect(() => agg.onTick({ ...trade, time })).toThrow(/order|timestamp/i);
    expect(agg.current()).toEqual(before);
  });

  it.each([0, -1, NaN, Infinity])('rejects invalid tick size %s', (tickSize) => {
    expect(() => computeFootprint(60, [], tickSize)).toThrow(/tickSize/i);
    expect(() => new FootprintAggregator({ mode: 'ticks', count: 1 }, tickSize)).toThrow(/tickSize/i);
  });

  it.each([0, -1, 1.5, NaN, Infinity])('rejects invalid row multiplier %s', (rowTicks) => {
    expect(() => computeFootprint(60, [], 0.1, rowTicks)).toThrow(/rowTicks/i);
    expect(() => new FootprintAggregator({ mode: 'ticks', count: 1 }, 0.1, rowTicks)).toThrow(/rowTicks/i);
  });

  it.each<TickTimeframe>([
    { mode: 'ticks', count: 0 }, { mode: 'ticks', count: 1.5 },
    { mode: 'interval', seconds: 0 }, { mode: 'interval', seconds: Infinity },
    { mode: 'interval', seconds: 60, anchorSec: NaN }, { mode: 'volume', perBar: -1 },
  ])('rejects invalid timeframe %j', (tf) => {
    expect(() => new FootprintAggregator(tf, 0.1)).toThrow(/count|seconds|anchorSec|perBar/i);
  });

  it.each([
    { price: NaN }, { qty: -1 }, { qty: Infinity }, { side: 'unknown' }, { time: NaN },
  ])('rejects malformed input %j before changing a live bar', (invalid) => {
    const agg = new FootprintAggregator({ mode: 'ticks', count: 1 }, 0.1);
    agg.onTick({ ...trade, time: 60 });
    const before = agg.current();
    const tick = { ...trade, time: 61, ...invalid } as typeof trade & { time: number };
    expect(() => agg.onTick(tick)).toThrow(/price|qty|side|time/i);
    expect(agg.current()).toEqual(before);
    expect(() => computeFootprint(tick.time, [tick], 0.1)).toThrow(/price|qty|side|time/i);
  });

  it('copies timeframe configuration so external mutation cannot corrupt future aggregation', () => {
    const tf = { mode: 'ticks' as const, count: 2 };
    const agg = new FootprintAggregator(tf, 0.1);
    tf.count = 0;
    agg.onTick({ ...trade, time: 60 });
    expect(agg.onTick({ ...trade, time: 61 }).isNew).toBe(false);
  });
});

describe('footprint diagonal and stacked imbalances', () => {
  it('compares fractional quantities without clamping the opposing volume to one', () => {
    expect(diagonalImbalances([
      { price: 2, bidVol: 0, askVol: 0.4 }, { price: 1, bidVol: 0.1, askVol: 0 },
    ], 3, 1)).toEqual([{ price: 2, side: 'buy' }]);
  });

  it('treats positive against zero as an imbalance and applies the dominant-volume threshold', () => {
    const cells = [{ price: 2, bidVol: 0, askVol: 0.1 }, { price: 1, bidVol: 0, askVol: 0 }];
    expect(diagonalImbalances(cells, 3, 1)).toEqual([{ price: 2, side: 'buy' }]);
    expect(diagonalImbalances(cells, 3, 1, 0.2)).toEqual([]);
    expect(diagonalImbalances([{ price: 2, bidVol: 0, askVol: 0 }, cells[1]], 3, 1)).toEqual([]);
  });

  it('compares a row beside an untraded row inside the bar with zero', () => {
    // Row 3 never traded: the ask at 4 and the bid at 2 each face zero across it.
    const cells = [{ price: 4, bidVol: 1, askVol: 100 }, { price: 2, bidVol: 1, askVol: 1 }, { price: 1, bidVol: 1, askVol: 1 }];
    const expected = [{ price: 4, side: 'buy' }, { price: 2, side: 'sell' }];
    expect(diagonalImbalances(cells, 3, 1)).toEqual(expected);
    expect(diagonalImbalances(cells, 3)).toEqual(expected);
  });

  it('uses explicit row size even when every observed gap spans missing levels', () => {
    expect(diagonalImbalances([{ price: 4, bidVol: 0, askVol: 100 }, { price: 2, bidVol: 1, askVol: 0 }], 3, 1))
      .toEqual([{ price: 4, side: 'buy' }, { price: 2, side: 'sell' }]);
    // Read as a grid of 2, the same rows are next to each other: the bid at 2 faces the ask of 100.
    expect(diagonalImbalances([{ price: 4, bidVol: 0, askVol: 100 }, { price: 2, bidVol: 1, askVol: 0 }], 3, 2))
      .toEqual([{ price: 4, side: 'buy' }]);
  });

  it('does not compare the rows beyond the bar high and low', () => {
    // The bid on the top row and the ask on the bottom row have no row to face.
    expect(diagonalImbalances([{ price: 2, bidVol: 5, askVol: 0 }, { price: 1, bidVol: 0, askVol: 5 }], 3, 1)).toEqual([]);
  });

  it('does not compare across a gap too wide to be untraded rows', () => {
    // 1999 rows apart: the row size is wrong for this bar, not 1999 rows untouched.
    expect(diagonalImbalances([{ price: 2000, bidVol: 1, askVol: 100 }, { price: 0, bidVol: 100, askVol: 1 }], 3, 1)).toEqual([]);
  });

  it('does not compare rows closer than the row size', () => {
    expect(diagonalImbalances([{ price: 1.5, bidVol: 0, askVol: 100 }, { price: 1, bidVol: 1, askVol: 0 }], 3, 1)).toEqual([]);
  });

  it('keeps both buy and sell flags on a row when forming a stack', () => {
    const cells = [
      { price: 5, bidVol: 0, askVol: 0 },
      { price: 4, bidVol: 30, askVol: 100 },
      { price: 3, bidVol: 1, askVol: 100 },
      { price: 2, bidVol: 1, askVol: 100 },
      { price: 1, bidVol: 1, askVol: 0 },
    ];
    expect(stackedImbalances(cells, 3, 3, 1)).toEqual([{ startPrice: 4, endPrice: 2, side: 'buy', count: 3 }]);
  });

  it('breaks stacks across gaps instead of treating separately adjacent runs as one', () => {
    // 4 faces the untraded row 3, so it is an imbalance, but the run stops there: 6 to 4, not 6 to 1.
    const cells = [6, 5, 4, 2, 1, 0].map((price) => ({ price, bidVol: 1, askVol: 100 }));
    expect(stackedImbalances(cells, 3, 3, 1)).toEqual([{ startPrice: 6, endPrice: 4, side: 'buy', count: 3 }]);
  });

  it('handles floating price grids and unsorted callers without mutating input', () => {
    const cells = [{ price: 100.1, bidVol: 0.1, askVol: 0 }, { price: 100.2, bidVol: 0, askVol: 0.4 }];
    expect(diagonalImbalances(cells, 3, 0.1)).toEqual([{ price: 100.2, side: 'buy' }]);
    expect(cells[0].price).toBe(100.1);
  });

  it('validates analytics configuration even for empty rows', () => {
    expect(() => diagonalImbalances([], 0)).toThrow(/ratio/i);
    expect(() => diagonalImbalances([], 3, 0)).toThrow(/rowSize/i);
    expect(() => diagonalImbalances([], 3, 1, -1)).toThrow(/threshold/i);
    expect(() => stackedImbalances([], 3, 0)).toThrow(/minStack/i);
  });
});


describe('footprint intrabar delta extremes', () => {
  const ticks: FootprintTick[] = [
    { time: 60, price: 100.12, qty: 5, side: 'bid' },
    { time: 61, price: 99.91, qty: 12, side: 'ask' },
    { time: 62, price: 100.19, qty: 10, side: 'bid' },
  ];

  it('measures the ordered trade path rather than final row deltas', () => {
    const forward = computeFootprint(60, ticks, 0.1);
    const reordered = computeFootprint(60, [ticks[1], ticks[0], ticks[2]], 0.1);
    expect(forward).toMatchObject({ delta: -3, minDelta: -5, maxDelta: 7 });
    expect(reordered).toMatchObject({ delta: -3, minDelta: -3, maxDelta: 12 });
    expect(forward.cells).toEqual(reordered.cells);
  });

  it.each([1, 20])('agrees between batch and stream independently of row grouping %s', (rowTicks) => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.1, rowTicks);
    const updates = ticks.map(tick => agg.onTick(tick).bar);
    expect(updates.map(({ delta, minDelta, maxDelta }) => ({ delta, minDelta, maxDelta }))).toEqual([
      { delta: -5, minDelta: -5, maxDelta: 0 },
      { delta: 7, minDelta: -5, maxDelta: 7 },
      { delta: -3, minDelta: -5, maxDelta: 7 },
    ]);
    expect(agg.current()).toEqual(computeFootprint(60, ticks, 0.1, rowTicks));
  });

  it.each<FootprintTick['side']>(['ask', 'bid'])('includes initial zero for a one-sided %s bar', (side) => {
    const tick = { ...ticks[0], qty: 0.5, side };
    const expected = side === 'ask' ? { minDelta: 0, maxDelta: 0.5 } : { minDelta: -0.5, maxDelta: 0 };
    expect(computeFootprint(60, [tick], 0.1)).toMatchObject(expected);
    expect(new FootprintAggregator({ mode: 'ticks', count: 1 }, 0.1).onTick(tick).bar).toMatchObject(expected);
  });

  it.each<TickTimeframe>([
    { mode: 'interval', seconds: 60 }, { mode: 'ticks', count: 3 }, { mode: 'volume', perBar: 27 },
  ])('resets extremes at the next bar boundary in %j', (tf) => {
    const agg = new FootprintAggregator(tf, 0.1);
    for (const tick of ticks) agg.onTick(tick);
    expect(agg.onTick({ ...ticks[0], time: 120, qty: 2, side: 'ask' })).toMatchObject({
      isNew: true, bar: { delta: 2, minDelta: 0, maxDelta: 2, tradeCount: 1 },
    });
  });

  it('retains the complete path while a count bar coalesces tied timestamps', () => {
    const agg = new FootprintAggregator({ mode: 'ticks', count: 1 }, 0.1);
    for (const tick of ticks) agg.onTick({ ...tick, time: 60 });
    expect(agg.current()).toMatchObject({ time: 60, delta: -3, minDelta: -5, maxDelta: 7 });
    expect(agg.onTick({ ...ticks[0], time: 61 })).toMatchObject({
      isNew: true, bar: { time: 61, delta: -5, minDelta: -5, maxDelta: 0 },
    });
  });

  it('keeps zero-size and zero-net ticks from inventing additional extremes', () => {
    const records: FootprintTick[] = [
      { ...ticks[0], qty: 0.25 }, { ...ticks[1], qty: 0.25 }, { ...ticks[2], qty: 0 },
    ];
    expect(computeFootprint(60, records, 0.1)).toMatchObject({ delta: 0, minDelta: -0.25, maxDelta: 0 });
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.1);
    for (const tick of records) agg.onTick(tick);
    expect(agg.current()).toMatchObject({ delta: 0, minDelta: -0.25, maxDelta: 0 });
  });

  it('detaches extreme metadata and rejects invalid ticks without changing the path', () => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.1);
    const first = agg.onTick(ticks[0]).bar;
    agg.onTick(ticks[1]);
    expect(first).toMatchObject({ minDelta: -5, maxDelta: 0 });
    const current = agg.current()!;
    current.minDelta = -999;
    current.maxDelta = 999;
    expect(() => agg.onTick({ ...ticks[2], qty: NaN })).toThrow(/qty/);
    expect(agg.current()).toMatchObject({ delta: 7, minDelta: -5, maxDelta: 7 });
  });
});
