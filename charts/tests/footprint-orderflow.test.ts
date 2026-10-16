import { describe, expect, it } from 'vitest';
import { computeFootprint } from '../src/profile/footprint';
import { FootprintAggregator } from '../src/profile/footprint-aggregator';
import { createTradeClassifier } from '../src/profile/footprint-classify';
import { footprintSignals } from '../src/profile/footprint-signals';
import { Footprint, type FootprintOptions } from '../src/profile/footprint-primitive';
import { FOOTPRINT_THEMES } from '../src/profile/footprint-themes';
import { TRADING_HOURS } from '../src/profile/market-profile';
import type { FootprintBar } from '../src/profile/profile-model';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { makeCtx } from './helpers/fake-ctx';

type Row = [price: number, bid: number, ask: number];
function bar(time: number, rows: Row[], ohlc: { open: number; high: number; low: number; close: number }, extra: Partial<FootprintBar> = {}): FootprintBar {
  const cells = rows.map(([price, bidVol, askVol]) => ({ price, bidVol, askVol })).sort((a, b) => b.price - a.price);
  return { time, cells, delta: cells.reduce((sum, c) => sum + c.askVol - c.bidVol, 0), rowSize: 1, ...ohlc, ...extra };
}
const flat = (price: number) => ({ open: price, high: price, low: price, close: price });

function context(times: number[], spacing = 120): PrimitiveRenderContext {
  const dataLayer = new DataLayer();
  const id = dataLayer.createSeries();
  dataLayer.setSeriesData(id, times.map(time => ({ time, open: 100, high: 104, low: 96, close: 100 })));
  const timeScale = new TimeScale({ barSpacing: spacing, maxBarSpacing: 250, rightOffset: 1 });
  timeScale.setWidth(600);
  timeScale.setBaseIndex(times.length - 1);
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 90, max: 110 });
  return { dataLayer, timeScale, priceScale, dpr: 1, plotWidth: 600, plotHeight: 400, priceAxisWidth: 60, theme: darkTheme };
}

describe('footprint row alignment', () => {
  // Row centres on a 2-point grid with a 0.05 tick: the odd whole numbers are exact ties.
  const prices = [22469, 22467, 22465, 22471, 22453, 22470.95];
  const expected = [22472, 22470, 22468, 22464, 22452];

  it('sends a tick exactly between two row centres to the even row', () => {
    const fp = computeFootprint(0, prices.map(price => ({ price, qty: 65, side: 'ask' as const })), 0.05, 40);
    expect(fp.cells.map(c => c.price)).toEqual(expected);
    expect(fp.cells.find(c => c.price === 22468)!.askVol).toBe(130);
  });

  it('streams onto the same rows as the batch builder', () => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.05, 40);
    let last: FootprintBar | null = null;
    for (const price of prices) last = agg.onTick({ time: 5, price, qty: 65, side: 'bid' }).bar;
    expect(last!.cells.map(c => c.price)).toEqual(expected);
  });

  it('opens the next interval bar with a tick stamped exactly on the boundary', () => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 1);
    agg.onTick({ time: 59.999, price: 100, qty: 1, side: 'ask' });
    const update = agg.onTick({ time: 60, price: 100, qty: 1, side: 'ask' });
    expect(update.isNew).toBe(true);
    expect(update.bar.time).toBe(60);
  });
});

describe('footprint trade size filter', () => {
  const trades = [
    { price: 100, qty: 10, side: 'bid' as const },
    { price: 101, qty: 100, side: 'ask' as const },
    { price: 102, qty: 5, side: 'ask' as const },
  ];

  it('counts only large prints but keeps every row and the full range', () => {
    const fp = computeFootprint(0, trades, 1, 1, { minTradeSize: 50 });
    expect(fp.cells).toEqual([{ price: 102, bidVol: 0, askVol: 0 }, { price: 101, bidVol: 0, askVol: 100 }, { price: 100, bidVol: 0, askVol: 0 }]);
    expect([fp.delta, fp.tradeCount, fp.open, fp.high, fp.low, fp.close]).toEqual([100, 1, 100, 102, 100, 102]);
    expect(fp.auction).toEqual({ highBid: 0, highAsk: 5, lowBid: 10, lowAsk: 0 });
  });

  it('closes tick-count bars on every print, filtered or not', () => {
    const agg = new FootprintAggregator({ mode: 'ticks', count: 2 }, 1, 1, { minTradeSize: 50 });
    trades.forEach((t, i) => agg.onTick({ ...t, time: i + 1 }));
    expect(agg.current()!.time).toBe(3);
  });

  it('rejects a negative size', () => {
    expect(() => computeFootprint(0, trades, 1, 1, { minTradeSize: -1 })).toThrow(RangeError);
    expect(() => new FootprintAggregator({ mode: 'interval', seconds: 60 }, 1, 1, { minTradeSize: Number.NaN })).toThrow(RangeError);
  });
});

describe('createTradeClassifier', () => {
  it('applies the tick rule, carrying the side through unchanged prices', () => {
    const side = createTradeClassifier();
    expect([100, 101, 101, 100, 100, 102].map(price => side({ price, qty: 1 }))).toEqual(['ask', 'ask', 'ask', 'bid', 'bid', 'ask']);
  });

  it('uses the quote first and falls back to the tick rule inside the spread or without a valid quote', () => {
    const side = createTradeClassifier('quote');
    expect(side({ price: 100, qty: 1, bid: 99.5, ask: 100 })).toBe('ask');
    expect(side({ price: 99.5, qty: 1, bid: 99.5, ask: 100 })).toBe('bid');
    expect(side({ price: 99.75, qty: 1, bid: 99.5, ask: 100 })).toBe('ask');
    expect(side({ price: 99.6, qty: 1, bid: 100, ask: 99.5 })).toBe('bid');
    expect(side({ price: 99.6, qty: 1 })).toBe('bid');
  });

  it('rejects an unknown mode', () => {
    expect(() => createTradeClassifier('mid' as never)).toThrow(TypeError);
  });
});

describe('footprintSignals', () => {
  it('marks consecutive bars sharing a point of control and starts a node zone after the run', () => {
    const bars = [100, 160, 220].map(t => bar(t, [[101, 1, 1], [100, 9, 9], [99, 1, 1]], flat(100)));
    bars.push(bar(280, [[106, 1, 1], [105, 9, 9]], flat(105)));
    const s = footprintSignals(bars, { stackedImbalances: 0, absorptionMultiple: 0 });
    expect(s.bars.map(b => b.node)).toEqual([true, true, true, false]);
    expect(s.zones).toEqual([{ kind: 'node', time: 220, low: 99.5, high: 100.5, endTime: null, activeTime: 280, touchTime: null }]);
  });

  it('ends a zone by its rule and never on the forming bar close', () => {
    const origin = bar(0, [[102, 0, 30], [101, 0, 30], [100, 0, 30], [99, 0, 0]], { open: 100, high: 102, low: 99, close: 102 });
    const wick = bar(60, [[103, 5, 5]], { open: 104, high: 104, low: 102, close: 104 });
    const inside = bar(120, [[101, 5, 5]], { open: 104, high: 104, low: 101, close: 101 });
    const opts = { multipleNodeBars: 0, formingLastBar: false };
    const zoneEnd = (zoneEnd: 'closeInside' | 'traverse' | 'touch', bars: FootprintBar[], forming = false) =>
      footprintSignals(bars, { ...opts, zoneEnd, formingLastBar: forming }).zones.find(z => z.kind === 'stackedBuy')!.endTime;
    expect(zoneEnd('touch', [origin, wick, inside])).toBe(60);
    expect(zoneEnd('closeInside', [origin, wick, inside])).toBe(120);
    expect(zoneEnd('traverse', [origin, wick, inside])).toBeNull();
    expect(zoneEnd('closeInside', [origin, wick, inside], true)).toBeNull();
  });

  it('activates a zone once whole bars trade beyond it', () => {
    const origin = bar(0, [[102, 0, 30], [101, 0, 30], [100, 0, 30], [99, 0, 0]], { open: 100, high: 102, low: 99, close: 102 });
    const above = [60, 120].map(t => bar(t, [[105, 1, 1]], flat(105)));
    const zone = (activeAfter: number) => footprintSignals([origin, ...above], { multipleNodeBars: 0, zoneActiveAfter: activeAfter }).zones[0]!;
    expect(zone(1).activeTime).toBe(60);
    expect(zone(2).activeTime).toBe(120);
    expect(zone(3).activeTime).toBeNull();
  });

  it('finds a big bid near the low of a selling bar and absorption near an extreme', () => {
    const quiet = [0, 60, 120].map(t => bar(t, [[101, 2, 2], [100, 2, 2]], flat(100)));
    const big = bar(180, [[103, 4, 2], [102, 4, 2], [101, 4, 2], [100, 40, 2]], { open: 103, high: 103, low: 100, close: 100 });
    const absorb = bar(240, [[104, 30, 30], [103, 2, 2], [102, 2, 2], [101, 2, 2], [100, 2, 2], [99, 2, 2], [98, 2, 2], [97, 2, 2]], flat(100));
    const s = footprintSignals([...quiet, big, absorb], { multipleNodeBars: 0, stackedImbalances: 0 });
    expect(s.bars[3]!.bigBid).toBe(100);
    expect(s.bars[3]!.bigAsk).toBeNull();
    expect(s.bars[4]!.absorption).toEqual([{ low: 104, high: 104 }]);
    expect(s.zones.map(z => z.kind)).toEqual(['absorption']);
  });

  it('flags an aggressive buying flip at a swing low and a price/delta divergence', () => {
    const down = [0, 60].map((t, i) => bar(t, [[100 - i, 30, 10]], { open: 101 - i, high: 101 - i, low: 99 - i, close: 99 - i }));
    const flip = bar(120, [[98, 10, 90]], { open: 98, high: 99, low: 97, close: 98.5 });
    const divergent = bar(180, [[99, 50, 10]], { open: 98, high: 99, low: 98, close: 99 });
    const s = footprintSignals([...down, flip, divergent], { multipleNodeBars: 0, stackedImbalances: 0 });
    expect(s.bars.map(b => b.flip)).toEqual([0, 0, 1, 0]);
    expect(s.bars.map(b => b.divergence)).toEqual([false, false, false, true]);
  });

  it('draws an unfinished auction from an extreme traded on both sides until price trades beyond it', () => {
    const first = bar(0, [[101, 1, 1], [100, 1, 1]], { open: 100, high: 101, low: 100, close: 101 },
      { auction: { highBid: 3, highAsk: 4, lowBid: 5, lowAsk: 0 } });
    const retest = bar(60, [[101, 1, 1]], { open: 101, high: 101, low: 100.5, close: 101 });
    const beyond = bar(120, [[102, 1, 1]], { open: 101, high: 101.5, low: 101, close: 101.5 });
    const all = footprintSignals([first, retest, beyond], { formingLastBar: false });
    expect(all.auctions).toEqual([{ time: 0, side: 'high', price: 101, endTime: 120 }]);
    expect(footprintSignals([first], { formingLastBar: true }).auctions).toEqual([]);
  });

  it('validates its options', () => {
    expect(() => footprintSignals([], { multipleNodeBars: 1 })).toThrow(RangeError);
    expect(() => footprintSignals([], { zoneEnd: 'never' as never })).toThrow(TypeError);
    expect(() => footprintSignals([], { signalLookback: 0 })).toThrow(RangeError);
  });
});

describe('Footprint session statistics', () => {
  const open = Date.UTC(2026, 8, 9, 3, 45) / 1000; // 09:15 in Kolkata
  const day = (start: number, n: number, step: number) => Array.from({ length: n }, (_, i) =>
    bar(start + i * step, [[100, 10, 30]], flat(100)));

  it('letters bars by period from the session open and restarts cumulative values each session', () => {
    const bars = [...day(open, 3, 1200), ...day(open + 86400, 1, 300)];
    const fp = new Footprint({ sessionWindow: TRADING_HOURS['india'], cvdReset: 'session', tableRows: ['session', 'cvd', 'cumVolume', 'cvdRatio'] });
    fp.setBars(bars);
    expect(fp.stats().map(s => s.session)).toEqual(['A', 'A', 'B', 'A']);
    expect(fp.stats().map(s => s.cvd)).toEqual([20, 40, 60, 20]);
    expect(fp.stats().map(s => s.cumVolume)).toEqual([40, 80, 120, 40]);
    expect(fp.stats()[2]!.cvdRatio).toBeCloseTo(0.5);
  });

  it('keeps one running total without a session reset', () => {
    const fp = new Footprint({ cvdOffset: 5 });
    fp.setBars([...day(open, 2, 1200), ...day(open + 86400, 1, 300)]);
    expect(fp.stats().map(s => s.cvd)).toEqual([25, 45, 65]);
  });
});

describe('Footprint order flow drawing', () => {
  const draw = (fp: Footprint, times: number[]) => {
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, context(times));
    return rec.ops;
  };
  const pair = [
    bar(0, [[102, 0, 30], [101, 0, 30], [100, 0, 30], [99, 3, 10]], { open: 99, high: 102, low: 99, close: 102 }),
    bar(60, [[101, 40, 5], [100, 5, 5]], { open: 101, high: 101, low: 100, close: 100 }),
  ];

  it('fills only imbalanced cells in imbalance mode and outlines the candle body', () => {
    const fp = new Footprint({ displayMode: 'imbalance', buyColor: '#00ff00', sellColor: '#ff0000', showPoc: false, stackedImbalances: 0, showCandle: false });
    fp.setBars([pair[0]!]);
    const ops = draw(fp, [0]);
    const fills = ops.filter(op => op.type === 'fill').map(op => op.fillStyle);
    // Two imbalances face an empty row and one is ten times its opposite: all three at full strength.
    expect(fills.filter(f => f === 'rgb(0,255,0)')).toHaveLength(3);
    expect(ops.some(op => op.type === 'strokeRect' && op.strokeStyle === '#00ff00')).toBe(true);
  });

  it('labels each single-value mode in its own form', () => {
    const labels = (displayMode: 'deltaPct' | 'volumeDelta', compactNumbers = true) => {
      const fp = new Footprint({ displayMode, compactNumbers, showPoc: false, stackedImbalances: 0 });
      fp.setBars([bar(0, [[100, 250, 1250]], flat(100))]);
      return draw(fp, [0]).filter(op => op.type === 'fillText').map(op => op.text);
    };
    expect(labels('deltaPct')).toContain('67%');
    expect(labels('volumeDelta')).toContain('1.5K x 1K');
    expect(labels('volumeDelta', false)).toContain('1,500 x 1,000');
  });

  it('shades against the busiest row on screen when the intensity scope is visible', () => {
    const shades = (intensityScope: 'bar' | 'visible') => {
      const fp = new Footprint({ displayMode: 'volume', intensityScope, showPoc: false, stackedImbalances: 0, showCandle: false });
      fp.setBars([bar(0, [[100, 5, 5]], flat(100)), bar(60, [[100, 50, 50]], flat(100))]);
      return draw(fp, [0, 60]).filter(op => op.type === 'fill').map(op => op.fillStyle);
    };
    expect(new Set(shades('bar')).size).toBe(1);
    expect(new Set(shades('visible')).size).toBe(2);
  });

  it('draws zones, unfinished auctions, delta labels, divergence and the visible profile when asked', () => {
    const bars = [
      { ...pair[0]!, auction: { highBid: 2, highAsk: 3, lowBid: 0, lowAsk: 0 } },
      { ...pair[1]!, open: 100, close: 101 },
      bar(120, [[95, 1, 1]], flat(95)),
    ];
    const fp = new Footprint({ showZones: true, showUnfinishedAuctions: true, showDeltaLabels: true, markDivergence: true,
      divergenceColor: '#abcdef', showVisibleProfile: true, lastPriceColor: '#123456', showPoc: false });
    fp.setBars(bars);
    const ops = draw(fp, [0, 60, 120]);
    expect(fp.signals().zones.some(z => z.kind === 'stackedBuy')).toBe(true);
    expect(ops.some(op => op.type === 'setLineDash' && op.args.length === 4)).toBe(true);
    expect(ops.some(op => op.type === 'fillText' && op.text === '+97')).toBe(true);
    expect(ops.some(op => op.type === 'strokeRect' && op.strokeStyle === '#abcdef')).toBe(true);
    expect(ops.some(op => op.type === 'fillRect' && op.fillStyle === 'rgba(18,52,86,0.45)')).toBe(true);
    expect(ops.some(op => op.type === 'fillText' && op.text === '75')).toBe(true);
  });

  it('leaves the default drawing free of every new layer', () => {
    const fp = new Footprint();
    fp.setBars([{ ...pair[0]!, auction: { highBid: 2, highAsk: 3, lowBid: 0, lowAsk: 0 } }, pair[1]!]);
    const ops = draw(fp, [0, 60]);
    expect(ops.some(op => op.type === 'setLineDash')).toBe(false);
    expect(ops.some(op => op.type === 'fillText' && op.text === '+97')).toBe(false);
  });

  it('draws untraded rows inside a bar as 0 x 0 without changing imbalances or signals', () => {
    // Trades at 103 and 100 only: rows 102 and 101 went untraded.
    const gapped = bar(0, [[103, 0, 30], [100, 10, 0]], { open: 100, high: 103, low: 100, close: 103 });
    const zeros = (showEmptyRows: boolean) => {
      const fp = new Footprint({ showEmptyRows, showPoc: false, stackedImbalances: 0, showCandle: false });
      fp.setBars([gapped]);
      return { texts: draw(fp, [0]).filter(op => op.type === 'fillText' && op.text === '0').length, signals: JSON.stringify(fp.signals()) };
    };
    const filled = zeros(true), sparse = zeros(false);
    // Two traded rows each show one zero side; the two empty rows add two zeros each.
    expect(sparse.texts).toBe(2);
    expect(filled.texts).toBe(6);
    expect(filled.signals).toBe(sparse.signals);
    expect(new Footprint().options().showEmptyRows).toBe(true);
  });

  it('rejects invalid signal options through setOptions', () => {
    const fp = new Footprint();
    expect(() => fp.setOptions({ multipleNodeBars: 1 })).toThrow(RangeError);
    expect(() => fp.setOptions({ tpoMinutes: 0 })).toThrow(RangeError);
  });
});

describe('footprint zone lookback and alerts', () => {
  const origin = bar(0, [[102, 0, 30], [101, 0, 30], [100, 0, 30], [99, 0, 0]], { open: 100, high: 102, low: 99, close: 102 });
  const above = bar(60, [[105, 1, 1]], flat(105));
  const touch = bar(120, [[102, 1, 1]], { open: 104, high: 104, low: 102, close: 104 });
  const later = bar(180, [[102, 1, 1]], { open: 104, high: 104, low: 102, close: 104 });
  const opts = { multipleNodeBars: 0, absorptionMultiple: 0, zoneEnd: 'traverse' as const, formingLastBar: false };

  it('starts zones only in the newest bars the lookback names', () => {
    const kinds = (zoneLookback: number) => footprintSignals([origin, above, touch, later], { ...opts, zoneLookback }).zones.length;
    expect(kinds(0)).toBe(1);
    expect(kinds(4)).toBe(1);
    expect(kinds(3)).toBe(0);
  });

  it('records the first bar that comes back to a zone after it became active', () => {
    expect(footprintSignals([origin, above, touch, later], opts).zones[0]!.touchTime).toBe(120);
    // Coming back before the zone is active is not a touch.
    expect(footprintSignals([origin, touch], opts).zones[0]!.touchTime).toBeNull();
  });

  it('reports a live touch once, and none from the bars it first loads', () => {
    const fp = new Footprint({ ...opts, showZones: true });
    const seen: number[] = [];
    fp.onZoneAlert(alert => { seen.push(alert.time); expect(alert.zone.kind).toBe('stackedBuy'); });
    fp.setBars([origin, above]);
    expect(seen).toEqual([]);
    fp.setBars([origin, above, touch]);
    expect(seen).toEqual([120]);
    fp.setBars([origin, above, touch, later]);
    expect(seen).toEqual([120]);

    const loaded = new Footprint({ ...opts, showZones: true });
    const none: number[] = [];
    loaded.onZoneAlert(alert => none.push(alert.time));
    loaded.setBars([origin, above, touch]);
    expect(none).toEqual([]);
  });

  it('reports a touch in the bar that was forming, even when the next bar arrives in the same call', () => {
    const fp = new Footprint({ ...opts, showZones: true });
    const seen: number[] = [];
    fp.onZoneAlert(alert => seen.push(alert.time));
    fp.setBars([origin, above]);
    // The touch at 120 and the next bar at 180 land together, as a batched host would send them.
    fp.setBars([origin, above, touch, later]);
    expect(seen).toEqual([120]);
  });

  it('starts a new history when the bars are cleared or start again from an older bar', () => {
    const fp = new Footprint({ ...opts, showZones: true });
    const seen: number[] = [];
    fp.onZoneAlert(alert => seen.push(alert.time));
    fp.setBars([origin, above]);
    fp.setBars([]);
    fp.setBars([origin, above, touch]);
    expect(seen).toEqual([]);
    const shift = (b: FootprintBar, by: number) => ({ ...b, time: b.time - by });
    const older = new Footprint({ ...opts, showZones: true });
    older.onZoneAlert(alert => seen.push(alert.time));
    older.setBars([origin, above, touch, later].map(b => shift(b, -1000)));
    older.setBars([origin, above, touch]);
    expect(seen).toEqual([]);
  });

  it('alerts only on the zones it extends, and stops when unsubscribed', () => {
    const count = (patch: Partial<FootprintOptions>, unsubscribe = false) => {
      const fp = new Footprint({ ...opts, showZones: true, ...patch });
      let n = 0;
      const off = fp.onZoneAlert(() => { n++; });
      fp.setBars([origin, above]);
      if (unsubscribe) off();
      fp.setBars([origin, above, touch]);
      return n;
    };
    expect(count({})).toBe(1);
    expect(count({ zoneKinds: ['node', 'absorption'] })).toBe(0);
    expect(count({ showZones: false })).toBe(0);
    expect(count({}, true)).toBe(0);
  });

  it('draws only the zone kinds it extends', () => {
    const zoneFills = (zoneKinds: FootprintOptions['zoneKinds']) => {
      const fp = new Footprint({ ...opts, showZones: true, zoneKinds, imbalanceBuyColor: '#0000ff', showCandle: false, showPoc: false });
      fp.setBars([origin, above, touch]);
      const { ctx, rec } = makeCtx();
      fp.draw(ctx, context([0, 60, 120]));
      return rec.ops.filter(op => op.type === 'fillRect' && op.fillStyle === 'rgba(0,0,255,0.22)').length;
    };
    expect(zoneFills(['stacked'])).toBe(1);
    expect(zoneFills(['node'])).toBe(0);
  });

  it('validates the zone kinds and the lookback', () => {
    expect(() => new Footprint({ zoneKinds: ['stacked', 'stacked'] })).toThrow(RangeError);
    expect(() => new Footprint({ zoneKinds: ['wall' as never] })).toThrow(RangeError);
    expect(() => new Footprint({ zoneLookback: -1 })).toThrow(RangeError);
  });
});

describe('footprint delta-shaded volume and colours', () => {
  const draw = (fp: Footprint, times: number[]) => {
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, context(times));
    return rec.ops;
  };
  const rgb = (fill: unknown) => (String(fill).match(/\d+/g) ?? []).map(Number);

  it('prints the row volume on a cell coloured by its delta', () => {
    const cell = (bid: number, ask: number) => {
      const fp = new Footprint({ displayMode: 'deltaShadedVolume', buyColor: '#00ff00', sellColor: '#ff0000', showPoc: false, stackedImbalances: 0, showCandle: false });
      fp.setBars([bar(0, [[100, bid, ask]], flat(100))]);
      const ops = draw(fp, [0]);
      return { text: ops.filter(op => op.type === 'fillText').map(op => op.text), fill: rgb(ops.find(op => op.type === 'fill')!.fillStyle) };
    };
    const up = cell(250, 1250), down = cell(1250, 250);
    expect(up.text).toContain('1.5K');
    expect(down.text).toContain('1.5K');
    expect(up.fill[1]!).toBeGreaterThan(up.fill[0]!);
    expect(down.fill[0]!).toBeGreaterThan(down.fill[1]!);
    // Shaded by delta, not volume: the quieter row with the larger delta is the stronger green.
    const fp = new Footprint({ displayMode: 'deltaShadedVolume', buyColor: '#00ff00', showPoc: false, stackedImbalances: 0, showCandle: false });
    fp.setBars([bar(0, [[101, 0, 1000], [100, 1000, 1100]], flat(100))]);
    const [strong, weak] = draw(fp, [0]).filter(op => op.type === 'fill').map(op => rgb(op.fillStyle)[1]!);
    expect(strong!).toBeGreaterThan(weak!);
  });

  it('takes the volume colour in the volume mode', () => {
    const fp = new Footprint({ displayMode: 'volume', volumeColor: '#0000ff', showPoc: false, stackedImbalances: 0, showCandle: false });
    fp.setBars([bar(0, [[100, 250, 1250]], flat(100))]);
    const [r, g, b] = rgb(draw(fp, [0]).find(op => op.type === 'fill')!.fillStyle);
    expect(b!).toBeGreaterThan(r!);
    expect(b!).toBeGreaterThan(g!);
  });

  it('fills imbalances in their own colours, at full strength across an untraded row', () => {
    const fp = new Footprint({ displayMode: 'imbalance', imbalanceBuyColor: '#0000ff', imbalanceSellColor: '#ffff00', showPoc: false, stackedImbalances: 0, showCandle: false });
    // Row 100 never traded: the ask at 101 faces zero across it.
    fp.setBars([bar(0, [[101, 1, 5], [99, 1, 1]], { open: 99, high: 101, low: 99, close: 101 })]);
    const fills = draw(fp, [0]).filter(op => op.type === 'fill').map(op => op.fillStyle);
    expect(fills).toContain('rgb(0,0,255)');
    // The bid at 99 faces the empty row too.
    expect(fills).toContain('rgb(255,255,0)');
  });

  it('colours the candle, the visible profile, the table background and the session letters', () => {
    const fp = new Footprint({
      candleUpColor: '#00ffff', profileAskColor: '#ff00ff', profileBidColor: '#ffaa00', tableBackground: '#102030', sessionColor: '#ffff00',
      showVisibleProfile: true, tableRows: ['session', 'volume'], showPoc: false, stackedImbalances: 0, cellWidth: 100,
    });
    fp.setBars([bar(0, [[101, 2, 6], [100, 3, 3]], { open: 100, high: 101, low: 100, close: 101 })]);
    const ops = draw(fp, [0]);
    const fills = ops.filter(op => op.type === 'fillRect' || op.type === 'fill').map(op => String(op.fillStyle));
    expect(fills).toContain('#00ffff');
    expect(fills).toContain('rgba(255,0,255,0.8)');
    expect(fills).toContain('rgba(255,170,0,0.8)');
    expect(fills).toContain('#102030');
    const letter = ops.find(op => op.type === 'fillText' && op.text === fp.stats()[0]!.session);
    expect(letter?.fillStyle).toBe('#ffff00');
  });
});

describe('FOOTPRINT_THEMES', () => {
  it('sets every colour option a theme carries, as valid colours, on frozen objects', () => {
    for (const [name, colors] of Object.entries(FOOTPRINT_THEMES)) {
      const values = Object.values(colors);
      expect(values, name).toHaveLength(20);
      for (const value of values) expect(value, name).toMatch(/^#[0-9A-F]{6}$/);
      expect(Object.isFrozen(colors), name).toBe(true);
      // A theme is an options patch the footprint accepts as it is.
      expect(() => new Footprint({ ...colors })).not.toThrow();
    }
    expect(FOOTPRINT_THEMES.ocean.imbalanceBuyColor).toBe('#00ACC1');
    expect(FOOTPRINT_THEMES.daylight.tableBackground).toBe('#ECEFF1');
  });
});
