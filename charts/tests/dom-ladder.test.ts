import { darkTheme } from '../src/theme';
import { describe, it, expect } from 'vitest';
import { DomLadder, DEFAULT_DOM_LADDER_OPTIONS, ladderCapability, buildRows, visibleRows, type LadderRow } from '../src/trade/dom-ladder';
import { TickSchedule } from '../src/feed/tick-schedule';
import { FakeBroker } from '../src/trade/fake-broker';
import type { MarketDepth } from '../src/feed/types';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { makeCtx } from './helpers/fake-ctx';

const depth = (levels: number): MarketDepth => FakeBroker.makeDepth(100, levels, 0.05);

function rc(): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 95, max: 105 });
  const timeScale = new TimeScale();
  timeScale.setWidth(600);
  return { timeScale, priceScale, dataLayer: new DataLayer(), plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme };
}

describe('ladder capability (graceful degradation)', () => {
  it('classifies depth size into tiers', () => {
    expect(ladderCapability({ bids: [], asks: [], ltp: 100 })).toBe('none');
    expect(ladderCapability(depth(5))).toBe('compact');
    expect(ladderCapability(depth(20))).toBe('deep');
    expect(ladderCapability(depth(200))).toBe('deep');
  });
});

describe('buildRows aggregation', () => {
  it('merges bid/ask into price rows sorted high to low', () => {
    const rows = buildRows(depth(5), 0.05, 1);
    expect(rows.length).toBe(10); // 5 bids + 5 asks, distinct prices
    for (let i = 1; i < rows.length; i++) expect(rows[i].price).toBeLessThan(rows[i - 1].price);
  });

  it('buckets every N ticks when grouping deep books', () => {
    const grouped = buildRows(depth(20), 0.05, 5); // 0.25 buckets
    const ungrouped = buildRows(depth(20), 0.05, 1);
    expect(grouped.length).toBeLessThan(ungrouped.length);
    // total qty is preserved across aggregation
    const sum = (rows: { bidQty: number; askQty: number }[]) =>
      rows.reduce((a, r) => a + r.bidQty + r.askQty, 0);
    expect(sum(grouped)).toBe(sum(ungrouped));
  });
});

describe('virtualization', () => {
  it('caps rendered rows to maxRows for a deep book', () => {
    const rows = buildRows(depth(200), 0.05, 1);
    const priceToY = (p: number): number => 400 * (1 - (p - 0) / 200); // wide range: many on screen
    const vis = visibleRows(rows, priceToY, 400, 14, 60);
    expect(vis.length).toBeLessThanOrEqual(60);
  });

  it('culls rows whose price is off-screen', () => {
    // 200 levels × 0.05 = ±10 (90 to 110); visible range [95,105]: outer levels cull
    const rows = buildRows(depth(200), 0.05, 1);
    const priceScale = rc().priceScale; // [95,105]
    const vis = visibleRows(rows, (p) => priceScale.priceToY(p), 400, 14, 1000);
    expect(vis.length).toBeLessThan(rows.length);
    for (const r of vis) {
      const y = priceScale.priceToY(r.price);
      expect(y).toBeGreaterThanOrEqual(-14);
      expect(y).toBeLessThanOrEqual(414);
    }
  });
});

describe('DomLadder primitive', () => {
  it('renders bars for a populated book', () => {
    const ladder = new DomLadder({ tickSize: 0.05 });
    ladder.setDepth(depth(20));
    const { ctx, rec } = makeCtx();
    ladder.draw(ctx, rc());
    expect(rec.count('fillRect')).toBeGreaterThan(0);
    expect(ladder.tier()).toBe('deep');
  });

  it('degrades gracefully with no depth (draws nothing)', () => {
    const ladder = new DomLadder();
    const { ctx, rec } = makeCtx();
    ladder.draw(ctx, rc()); // never setDepth
    expect(rec.ops.length).toBe(0);
    expect(ladder.tier()).toBe('none');
  });

  it('hit-tests a price level inside the strip with side', () => {
    const r = rc();
    const ladder = new DomLadder({ tickSize: 0.05, width: 96 });
    ladder.setDepth(depth(5));
    const { ctx } = makeCtx();
    ladder.draw(ctx, r); // populates row hit positions
    const askPrice = 100.05;
    const y = r.priceScale.priceToY(askPrice);
    const hit = ladder.hitTest(r.plotWidth - 10, y, r);
    expect(hit?.externalId.startsWith('ladder-')).toBe(true);
  });
});

// Synthetic rules, not any venue's: 0.01 below 100 and 0.05 from 100.
const BANDED = new TickSchedule([{ tick: 0.01 }, { from: 100, tick: 0.05 }]);
const level = (price: number, qty: number) => ({ price, qty });
/** A book that straddles the boundary: cent bids below 100, nickel asks from it. */
const straddle = (): MarketDepth => ({
  ltp: 99.99,
  bids: [99.99, 99.98, 99.97, 99.96, 99.95].map((price, i) => level(price, 10 + i)),
  asks: [100, 100.05, 100.1, 100.15, 100.2].map((price, i) => level(price, 20 + i)),
});
/** A deep one: 50 cent bids from 99.50 and 50 nickel asks from 100. */
const deepStraddle = (): MarketDepth => ({
  ltp: 99.99,
  bids: Array.from({ length: 50 }, (_, i) => level(+(99.99 - i * 0.01).toFixed(2), 1 + i)),
  asks: Array.from({ length: 50 }, (_, i) => level(+(100 + i * 0.05).toFixed(2), 100 + i)),
});
const total = (rows: readonly LadderRow[]): number => rows.reduce((sum, row) => sum + row.bidQty + row.askQty, 0);
const onGrid = (price: number, tick: number): boolean => Math.abs(price / tick - Math.round(price / tick)) < 1e-9;
/** The ladder's bucketing before schedules, kept to prove the constant path unchanged. */
function constantRows(book: MarketDepth, tickSize: number, groupBy = 1): LadderRow[] {
  const step = tickSize * Math.max(1, groupBy);
  const bucket = (p: number): number => Math.round(Math.round(p / step) * step * 1e8) / 1e8;
  const map = new Map<number, LadderRow>();
  const add = (price: number, qty: number, side: 'bid' | 'ask'): void => {
    const key = bucket(price);
    let row = map.get(key);
    if (row === undefined) { row = { price: key, bidQty: 0, askQty: 0 }; map.set(key, row); }
    if (side === 'bid') row.bidQty += qty; else row.askQty += qty;
  };
  for (const b of book.bids) add(b.price, b.qty, 'bid');
  for (const a of book.asks) add(a.price, a.qty, 'ask');
  return Array.from(map.values()).sort((x, y) => y.price - x.price);
}

describe('buildRows with a tick schedule', () => {
  it('keeps each level on the price its own band allows across the boundary', () => {
    expect(buildRows(straddle(), BANDED).map(row => row.price))
      .toEqual([100.2, 100.15, 100.1, 100.05, 100, 99.99, 99.98, 99.97, 99.96, 99.95]);
    // One constant step cannot serve both bands: the upper tick folds the cent
    // levels below 100 into rows the book does not have.
    expect(buildRows(straddle(), 0.05).map(row => row.price)).toEqual([100.2, 100.15, 100.1, 100.05, 100, 99.95]);
  });

  it('moves an off-grid level to the nearest price its band allows', () => {
    const odd: MarketDepth = { ltp: 100, bids: [level(99.994, 3)], asks: [level(100.03, 4), level(100.05, 5)] };
    expect(buildRows(odd, BANDED)).toEqual([{ price: 100.05, bidQty: 0, askQty: 9 }, { price: 99.99, bidQty: 3, askQty: 0 }]);
  });

  it('groups ticks of the band each level is in, preserving every quantity', () => {
    const book = deepStraddle();
    const rows = buildRows(book, BANDED, 5);
    expect(total(rows)).toBe(total(buildRows(book, BANDED)));
    // Five cents below 100, five nickels from 100.
    for (const row of rows) expect(onGrid(row.price, row.price < 100 ? 0.05 : 0.25)).toBe(true);
    expect(rows.filter(row => row.price < 100).length).toBe(10);
    // 101.15 through 101.35: the five nickels nearest 101.25.
    expect(rows.find(row => row.price === 101.25)).toEqual({ price: 101.25, bidQty: 0, askQty: 123 + 124 + 125 + 126 + 127 });
  });

  it('never lets a group in one band label a row with a price the next band forbids', () => {
    // Six cents is 0.06: 99.99 is nearest 100.02, which the 0.05 band above
    // 100 cannot trade at, so the group stops at the boundary.
    const book: MarketDepth = { ltp: 99.99, bids: [level(99.99, 7)], asks: [level(100.05, 8)] };
    expect(buildRows(book, BANDED, 6)).toEqual([{ price: 100, bidQty: 7, askQty: 8 }]);
    const above = new TickSchedule([{ tick: 0.05 }, { from: 100.1, tick: 0.1 }]);
    // Downward too: 100.2 on a 0.5 group is nearest 100, below where its band starts.
    expect(buildRows({ ltp: 100.2, bids: [], asks: [level(100.2, 2)] }, above, 5)).toEqual([{ price: 100.1, bidQty: 0, askQty: 2 }]);
  });

  it('counts whole ticks when a schedule groups rows', () => {
    // A fractional group would label rows between the prices a band allows, so
    // the schedule path rounds groupBy down where the constant path multiplies.
    const book = deepStraddle();
    expect(buildRows(book, BANDED, 2.5)).toEqual(buildRows(book, BANDED, 2));
    for (const groupBy of [0, 0.5, 1.9]) expect(buildRows(book, BANDED, groupBy)).toEqual(buildRows(book, BANDED, 1));
    for (const row of buildRows(book, BANDED, 2.5)) expect(onGrid(row.price, row.price < 100 ? 0.02 : 0.1)).toBe(true);
    expect(buildRows(book, 0.05, 2.5).some(row => !onGrid(row.price, 0.05))).toBe(true);
  });

  it('keeps the constant tick path exactly as it was', () => {
    for (const groupBy of [1, 5, 2.5, 0]) {
      for (const book of [depth(200), straddle(), deepStraddle()]) {
        expect(buildRows(book, 0.05, groupBy)).toEqual(constantRows(book, 0.05, groupBy));
      }
    }
    expect(Object.keys(DEFAULT_DOM_LADDER_OPTIONS)).toEqual(['tickSize', 'width', 'groupBy', 'maxRows', 'rowHeight']);
  });

  it('coerces a tick size that is not an object exactly as before schedules', () => {
    // A plain-JS host may hand over a numeric string. Only an object takes the
    // schedule path, so every other value meets the old arithmetic unchanged.
    const loose = ['0.05', ' 0.05 ', undefined, null, true] as unknown as number[];
    for (const tick of loose) {
      for (const groupBy of [1, 5, 2.5]) {
        for (const book of [straddle(), deepStraddle()]) {
          expect(buildRows(book, tick, groupBy)).toEqual(constantRows(book, tick, groupBy));
        }
      }
    }
    expect(buildRows(deepStraddle(), '0.05' as unknown as number, 5)).toEqual(buildRows(deepStraddle(), 0.05, 5));
  });

  it('refuses a band list in place of a schedule', () => {
    const bands = [{ tick: 0.01 }, { from: 100, tick: 0.05 }] as unknown as TickSchedule;
    expect(() => buildRows(straddle(), bands)).toThrow(/new TickSchedule\(bands\)/);
    expect(() => new DomLadder({ tickSchedule: bands })).toThrow(TypeError);
  });
});

describe('DomLadder with a tick schedule', () => {
  function ladderContext(): PrimitiveRenderContext {
    const context = rc();
    context.priceScale.setPriceRange({ min: 99.9, max: 100.3 });
    return context;
  }

  function hitAt(ladder: DomLadder, price: number, context = ladderContext()): string | undefined {
    ladder.setDepth(straddle());
    ladder.draw(makeCtx().ctx, context);
    return ladder.hitTest(context.plotWidth - 10, context.priceScale.priceToY(price), context)?.externalId;
  }

  it('draws and hit-tests the rows the schedule allows', () => {
    const banded = new DomLadder({ tickSize: 0.05, tickSchedule: BANDED, rowHeight: 8 });
    expect(hitAt(banded, 99.97)).toBe('ladder-bid:99.97');
    expect(hitAt(banded, 100.15)).toBe('ladder-ask:100.15');
    // On a constant 0.05 step the cent levels fold into 99.95 and 100, so
    // there is no row at 99.97 to click. Null is no schedule, as on chart.trading.
    for (const constant of [new DomLadder({ tickSize: 0.05, rowHeight: 8 }), new DomLadder({ tickSize: 0.05, tickSchedule: null, rowHeight: 8 })]) {
      expect(hitAt(constant, 99.97)).toBeUndefined();
      expect(hitAt(constant, 99.95)).toBe('ladder-bid:99.95');
    }
  });

  it('draws the rows of a tick size given as a numeric string, as before schedules', () => {
    const ladder = new DomLadder({ tickSize: '0.05' as unknown as number, rowHeight: 8 });
    expect(hitAt(ladder, 99.95)).toBe('ladder-bid:99.95');
    expect(hitAt(ladder, 100.15)).toBe('ladder-ask:100.15');
  });
});
