/**
 * The 1.7.0 indicator spine: data-derived levels recomputed after calc, the
 * no-churn guard on a constant level list, overlay plot routing, the lazily
 * attached drawings layer, the attach lifecycle seams, and the calcTail guard.
 */
import { describe, it, expect } from 'vitest';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import type { IPrimitive } from '../src/primitives/primitive';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import { PriceLine } from '../src/primitives/price-line';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

/** What the host is actually handed for one level, style included. */
type LevelSpec = Parameters<IndicatorHost['addIndicatorLevel']>[0];

interface Rig {
  host: IndicatorHost;
  panesUsed: number[];
  levels: LevelSpec[];
  levelPrices: number[];
  levelAdds: number;
  primitives: IPrimitive[];
}

function rig(source: Bar[]): Rig {
  const panesUsed: number[] = [];
  const levels: LevelSpec[] = [];
  const primitives: IPrimitive[] = [];
  let levelAdds = 0;
  const host: IndicatorHost = {
    addIndicatorLegend: () => ({ setOptions: () => {}, setValues: () => {} }) as never,
    removeIndicatorLegend: () => {},
    legendRowsOn: () => 0,
    addIndicatorSeries: (_t, paneIndex): SeriesApi => {
      panesUsed.push(paneIndex);
      return {
        setData: () => {}, prependData: () => {}, update: () => {}, getData: () => [],
        applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
        createMarkers: () => ({ setMarkers: () => {} }) as never,
      };
    },
    addIndicatorLevel: (l) => { levelAdds += 1; levels.push({ ...l }); return {} as never; },
    removeIndicatorLevel: () => { levels.pop(); },
    addIndicatorFill: () => {},
    removeIndicatorFill: () => {},
    removeIndicatorMarkers: () => {},
    addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
    removeIndicatorTable: () => {},
    addIndicatorPrimitive: (p) => { primitives.push(p); },
    removeIndicatorPrimitive: (p) => { primitives.splice(primitives.indexOf(p), 1); },
    sourceBars: () => source,
    nextPaneIndex: () => 2,
    setPaneRange: () => {},
  };
  return {
    host, panesUsed, levels, primitives,
    get levelPrices() { return levels.map((l) => l.price); },
    get levelAdds() { return levelAdds; },
  };
}

const bar = (time: number, close: number): Bar => ({ time, open: close, high: close, low: close, close });
const wave = (n: number, base = 100): Bar[] =>
  Array.from({ length: n }, (_, i) => bar(1000 + i * 60, base + i));

describe('spine 1.7.0', () => {
  it('recomputes a data-derived level after calc', () => {
    const bars = wave(10);
    const d: IndicatorDescriptor = {
      id: 's-lv', name: 'L', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      // Previous-day-high shaped: derived from the bars, not from a setting.
      levels: (ctx) => {
        const b = ctx.bars ?? [];
        return b.length === 0 ? [] : [{ price: Math.max(...b.map((x) => x.high)) }];
      },
    };
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, d);
    expect(r.levelPrices).toEqual([109]);
    bars.push(bar(1000 + 10 * 60, 400));
    inst.recompute();
    expect(r.levelPrices).toEqual([400]);
  });

  it('keeps a constant level list from churning its price line every tick', () => {
    const bars = wave(10);
    const d: IndicatorDescriptor = {
      id: 's-const', name: 'C', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      levels: () => [{ price: 50, color: '#888', title: 'Zero' }],
    };
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, d);
    expect(r.levelAdds).toBe(1);
    for (let i = 0; i < 5; i++) { bars.push(bar(1600 + i * 60, 1)); inst.recompute(); }
    expect(r.levelAdds).toBe(1);
  });

  it('still reads a level straight off the settings bag (the built-ins)', () => {
    const d: IndicatorDescriptor = {
      id: 's-old', name: 'O', placement: 'pane',
      inputs: [{ key: 'overbought', type: 'number', label: 'OB', default: 70 }],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      levels: (s) => [{ price: Number(s.overbought), dashed: true }],
    };
    const r = rig(wave(5));
    const inst = new IndicatorInstance(r.host, d);
    expect(r.levelPrices).toEqual([70]);
    inst.setSettings({ overbought: 80 });
    expect(r.levelPrices).toEqual([80]);
  });

  it('hands levels the bars, the computed values and the settings bag', () => {
    const bars = wave(6);
    let seen: Record<string, unknown> = {};
    const d: IndicatorDescriptor = {
      id: 's-lvctx', name: 'X', placement: 'pane',
      inputs: [{ key: 'length', type: 'number', label: 'Length', default: 3 }],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      levels: (ctx) => {
        seen = { bars: ctx.bars, values: ctx.values?.v, nested: ctx.settings?.length, flat: ctx.length };
        return [];
      },
    };
    new IndicatorInstance(rig(bars).host, d);
    expect(seen.bars).toEqual(bars);
    // The values are the ones `calc` just produced, not the previous frame's.
    expect(seen.values).toEqual(bars.map((b) => b.close));
    expect(seen.nested).toBe(3);
    expect(seen.flat).toBe(3); // the flat key the built-ins read
  });

  it('carries a level width and style, and leaves a bare level dashed', () => {
    const d: IndicatorDescriptor = {
      id: 's-lvsty', name: 'S', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      levels: () => [
        { price: 70, lineWidth: 2, lineStyle: 'dotted', title: 'OB' },
        { price: 50 },
        { price: 30, dashed: false },
      ],
    };
    const r = rig(wave(5));
    new IndicatorInstance(r.host, d);
    expect(r.levels.map((l) => [l.lineWidth, l.lineStyle, l.dashed])).toEqual([
      [2, 'dotted', false],
      [1, 'dashed', true],
      [1, 'solid', false],
    ]);
    expect(r.levels.map((l) => l.label)).toEqual(['OB', '', '']);
  });

  it('rebuilds a level whose style alone changed', () => {
    const d: IndicatorDescriptor = {
      id: 's-lvres', name: 'R', placement: 'pane',
      inputs: [{ key: 'width', type: 'number', label: 'Width', default: 1 }],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      // Same price every time: only the width moves, which is precisely what a
      // signature built from the price alone would miss.
      levels: (ctx) => [{ price: 70, lineWidth: Number(ctx.width) }],
    };
    const r = rig(wave(5));
    const inst = new IndicatorInstance(r.host, d);
    inst.setSettings({ width: 4 });
    expect(r.levelAdds).toBe(2);
    expect(r.levels.map((l) => l.lineWidth)).toEqual([4]);
  });

  it('hands draws the bars, the computed values and the settings', () => {
    const bars = wave(4);
    let seen: Record<string, unknown> = {};
    const d: IndicatorDescriptor = {
      id: 's-drctx', name: 'DC', placement: 'pane',
      inputs: [{ key: 'length', type: 'number', label: 'Length', default: 7 }],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      draws: (ctx) => {
        seen = { bars: ctx.bars, values: ctx.values.v, length: ctx.settings.length };
        return [];
      },
    };
    new IndicatorInstance(rig(bars).host, d);
    expect(seen.bars).toEqual(bars);
    expect(seen.values).toEqual(bars.map((b) => b.close));
    expect(seen.length).toBe(7);
  });

  it('routes an overlay plot onto the price pane and the rest onto its own', () => {
    const d: IndicatorDescriptor = {
      id: 's-ov', name: 'V', placement: 'pane', inputs: [],
      plots: [
        { key: 'a', type: 'line', title: 'a' },
        { key: 'b', type: 'line', title: 'b', overlay: true },
      ],
      calc: (bars) => ({ a: bars.map(() => 1), b: bars.map(() => 2) }),
    };
    const r = rig(wave(5));
    const inst = new IndicatorInstance(r.host, d);
    expect(inst.paneIndex).toBe(2);
    expect(r.panesUsed).toEqual([2, 0]);
    // Switching a plot's chart type rebuilds its series, which is a second
    // place the pane has to be decided and the one easiest to leave behind.
    inst.setSettings({ 'b:type': 'histogram' });
    expect(r.panesUsed).toEqual([2, 0, 0]);
  });

  it('attaches a drawing layer only once a descriptor actually draws', () => {
    const bars = wave(5);
    let on = false;
    const d: IndicatorDescriptor = {
      id: 's-dr', name: 'D', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      draws: () => on
        ? [{ kind: 'line' as const, from: { time: 1000, price: 1 }, to: { time: 1240, price: 2 } }]
        : [],
    };
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, d);
    expect(r.primitives).toHaveLength(0);
    on = true;
    inst.recompute();
    expect(r.primitives).toHaveLength(1);
    inst.remove();
    expect(r.primitives).toHaveLength(0);
  });

  it('hands the attach lifecycle the pane, the clock, the zone and a primitive seam', () => {
    const marker = { zOrder: () => 'normal' as const, draw: () => {} };
    let seen: Record<string, unknown> = {};
    const d: IndicatorDescriptor = {
      id: 's-at', name: 'A', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      attach: (ctx) => {
        seen = {
          pane: ctx.paneIndex?.(),
          zone: ctx.timezone?.(),
          now: ctx.now?.(),
          symbol: ctx.symbol?.(),
          interval: ctx.interval?.(),
        };
        ctx.addPrimitive?.(marker);
        return () => ctx.removePrimitive?.(marker);
      },
    };
    const r = rig(wave(5));
    const inst = new IndicatorInstance(r.host, d);
    expect(seen.pane).toBe(2);
    expect(seen.zone).toBe('Asia/Kolkata');
    expect(typeof seen.now).toBe('number');
    expect(seen.symbol).toBeUndefined();
    expect(seen.interval).toBeUndefined();
    expect(r.primitives).toContain(marker);
    inst.remove();
    expect(r.primitives).not.toContain(marker);
  });
});

/** Plots the close, with a tail path that only ever recomputes the tail. */
const tailDescriptor: IndicatorDescriptor = {
  id: 'spine-tail', name: 'Tail', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'v' }],
  calc: (b) => ({ v: b.map((x) => x.close) }),
  calcTail: (b, _s, from) => ({ v: b.slice(from).map((x) => x.close) }),
};

describe('calcTail is gated on the bar times, not the count', () => {
  it('falls back to a full calc when the symbol changes under a matching count', () => {
    const bars: Bar[] = [];
    for (let i = 0; i < 20; i++) bars.push(bar(1000 + i * 60, 100 + i));
    const inst = new IndicatorInstance(rig(bars).host, tailDescriptor);
    expect(inst.values().v[0]).toBe(100);
    // Same count, entirely different instrument and history.
    bars.length = 0;
    for (let i = 0; i < 20; i++) bars.push(bar(9000 + i * 60, 500 + i));
    inst.recompute();
    expect(inst.values().v).toEqual(bars.map((b) => b.close));
  });

  it('falls back to a full calc when one older bar is paged in at the left', () => {
    const bars: Bar[] = [];
    for (let i = 0; i < 20; i++) bars.push(bar(1000 + i * 60, 100 + i));
    const inst = new IndicatorInstance(rig(bars).host, tailDescriptor);
    bars.unshift(bar(940, 99));
    inst.recompute();
    expect(inst.values().v).toEqual(bars.map((b) => b.close));
  });

  it('still takes the tail path for a replaced last bar and for an append', () => {
    const bars: Bar[] = [];
    for (let i = 0; i < 20; i++) bars.push(bar(1000 + i * 60, 100 + i));
    let tails = 0;
    const counted: IndicatorDescriptor = {
      ...tailDescriptor,
      calcTail: (b, _s, from) => { tails += 1; return { v: b.slice(from).map((x) => x.close) }; },
    };
    const inst = new IndicatorInstance(rig(bars).host, counted);
    bars[19] = bar(1000 + 19 * 60, 999); // replaced forming bar
    inst.recompute();
    expect(tails).toBe(1);
    expect(inst.values().v[19]).toBe(999);
    bars.push(bar(1000 + 20 * 60, 777)); // appended bar
    inst.recompute();
    expect(tails).toBe(2);
    expect(inst.values().v).toEqual(bars.map((b) => b.close));
  });
});

/**
 * The host side of the same seams, on a real Chart. A rig can only prove the
 * instance asked for something; these prove `chart.ts` does it, which is where
 * an option that is declared and threaded but consumed by nobody would hide.
 */
describe('on a real chart', () => {
  const makeChart = (clock?: () => number): Chart => {
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      pixelRatio: () => 1,
      shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      axisChrome: clock === undefined ? undefined : { clock },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(wave(30));
    return chart;
  };

  it('carries a level width and style through to its price line', () => {
    registerIndicator({
      id: 'spine-level-style', name: 'Level Style', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      levels: () => [{ price: 110, color: '#0ff', title: 'Zero', lineWidth: 3, lineStyle: 'dotted' }],
    });
    const chart = makeChart();
    const inst = chart.addIndicator('spine-level-style');
    const lines = chart.panes()[inst.paneIndex].primitives().filter((p) => p instanceof PriceLine);
    expect(lines).toHaveLength(1);
    const opts = (lines[0] as PriceLine).options();
    expect([opts.lineWidth, opts.lineStyle, opts.color]).toEqual([3, 'dotted', '#0ff']);
  });

  it('attaches the drawings layer to the indicator own pane', () => {
    registerIndicator({
      id: 'spine-draws-pane', name: 'Draws', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      draws: (ctx) => ctx.bars.length === 0 ? [] : [{
        kind: 'box',
        from: { time: ctx.bars[0].time, price: 100 },
        to: { time: ctx.bars[ctx.bars.length - 1].time, price: 120 },
      }],
    });
    const chart = makeChart();
    const inst = chart.addIndicator('spine-draws-pane');
    const layers = chart.panes()[inst.paneIndex].primitives().filter((p) => p instanceof IndicatorDrawings);
    expect(layers).toHaveLength(1);
    expect(chart.panes()[0].primitives().some((p) => p instanceof IndicatorDrawings)).toBe(false);
    inst.remove();
    expect(chart.panes()).toHaveLength(1);
    expect(chart.panes().some(pane => pane.primitives().some(p => p instanceof IndicatorDrawings))).toBe(false);
  });

  it('hands attach the chart own wall clock, not a fresh Date.now', () => {
    let seen = 0;
    registerIndicator({
      id: 'spine-clock', name: 'Clock', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      attach: (ctx) => { seen = ctx.now?.() ?? 0; },
    });
    makeChart(() => 1234567).addIndicator('spine-clock');
    expect(seen).toBe(1234567);
  });
});
