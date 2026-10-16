/**
 * The 1.8.1 indicator surface: the calculation context and its bar state, the
 * pane shading layer, recolouring of the price candles, four-column bar plots,
 * and the declarative alerts.
 *
 * The rig proves what the instance asks its host for; the chart section at the
 * bottom proves `chart.ts` actually does it, which is where a hook that is
 * declared and threaded but consumed by nobody would hide.
 */
import { describe, it, expect } from 'vitest';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import {
  registerIndicator,
  type IndicatorCalcContext,
  type IndicatorAlertPayload,
  type IndicatorDescriptor,
} from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import type { SeriesDataItem } from '../src/model/bar';
import type { LegendValue } from '../src/primitives/pane-legend';
import type { IPrimitive } from '../src/primitives/primitive';
import { IndicatorBackground } from '../src/primitives/indicator-background';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

/** One publication of the price-bar colour overlay, as the host saw it. */
interface Published {
  colors: readonly (string | null)[] | null;
  owner: string;
}

interface Rig {
  host: IndicatorHost;
  primitives: IPrimitive[];
  published: Published[];
  events: { event: string; payload: unknown }[];
  /** Last `setData` payload per plot title, so a plot's points are assertable. */
  drawn: Map<string, readonly SeriesDataItem[]>;
  legend: LegendValue[];
  /** Mutable chart clock, for the bar-state tests. */
  clock: { now: number };
}

function rig(source: Bar[], extra: Partial<IndicatorHost> = {}): Rig {
  const primitives: IPrimitive[] = [];
  const published: Published[] = [];
  const events: { event: string; payload: unknown }[] = [];
  const drawn = new Map<string, readonly SeriesDataItem[]>();
  const clock = { now: 0 };
  const out: Rig = {
    host: {
      addIndicatorLegend: () => ({
        setOptions: () => {},
        setValues: (v: LegendValue[]) => { out.legend = v; },
      }) as never,
      removeIndicatorLegend: () => {},
      legendRowsOn: () => 0,
      addIndicatorSeries: (_t, _pane, style): SeriesApi => {
        const title = String(style?.title ?? '');
        return {
          setData: (d: readonly SeriesDataItem[]) => { drawn.set(title, d); },
          prependData: () => {}, update: () => {}, getData: () => [],
          applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
          createMarkers: () => ({ setMarkers: () => {} }) as never,
        };
      },
      addIndicatorLevel: () => ({}) as never,
      removeIndicatorLevel: () => {},
      addIndicatorFill: () => {},
      removeIndicatorFill: () => {},
      removeIndicatorMarkers: () => {},
      addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
      removeIndicatorTable: () => {},
      addIndicatorPrimitive: (p) => { primitives.push(p); },
      removeIndicatorPrimitive: (p) => { primitives.splice(primitives.indexOf(p), 1); },
      sourceBars: () => source,
      nextPaneIndex: () => 2,
      now: () => clock.now,
      setBarColors: (colors, owner) => { published.push({ colors, owner }); },
      emit: (event, payload) => { events.push({ event, payload }); },
      setPaneRange: () => {},
      ...extra,
    },
    primitives, published, events, drawn, clock, legend: [],
  };
  return out;
}

const bar = (time: number, close: number): Bar => ({ time, open: close, high: close, low: close, close });
const wave = (n: number, base = 100): Bar[] =>
  Array.from({ length: n }, (_, i) => bar(1000 + i * 60, base + i));

/** Plots the close and records the context it was handed. */
function contextProbe(id: string): { d: IndicatorDescriptor; seen: () => IndicatorCalcContext } {
  let last: IndicatorCalcContext | undefined;
  return {
    seen: () => last as IndicatorCalcContext,
    d: {
      id, name: 'Ctx', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b, _s, _store, ctx) => { last = ctx; return { v: b.map((x) => x.close) }; },
    },
  };
}

describe('the calculation context', () => {
  it('reaches calc with the chart calendar, the clock and no instrument', () => {
    const p = contextProbe('w2-ctx');
    const r = rig(wave(5));
    r.clock.now = 4242;
    new IndicatorInstance(r.host, p.d);
    const ctx = p.seen();
    expect(ctx.timezone).toBe('Asia/Kolkata');
    expect(ctx.now()).toBe(4242);
    // The core is handed bars and never an instrument, so it names none.
    expect(ctx.symbol).toBeUndefined();
    expect(ctx.interval).toBeUndefined();
    expect(ctx.barState.lastIndex).toBe(4);
  });

  it('carries the instrument and zone a wrapping host does know', () => {
    const p = contextProbe('w2-ctx-host');
    const r = rig(wave(5), {
      symbol: () => 'INFY',
      interval: () => '5m',
      timezone: () => 'America/New_York',
    });
    new IndicatorInstance(r.host, p.d);
    expect(p.seen().symbol).toBe('INFY');
    expect(p.seen().interval).toBe('5m');
    expect(p.seen().timezone).toBe('America/New_York');
  });

  it('calls a history load neither new nor realtime', () => {
    const p = contextProbe('w2-ctx-load');
    new IndicatorInstance(rig(wave(5)).host, p.d);
    expect(p.seen().barState.isNew).toBe(false);
    expect(p.seen().barState.isRealtime).toBe(false);
  });

  it('marks an appended bar new and a replaced one not', () => {
    const p = contextProbe('w2-ctx-new');
    const bars = wave(5);
    const inst = new IndicatorInstance(rig(bars).host, p.d);
    bars.push(bar(1300, 200));
    inst.recompute();
    expect(p.seen().barState.isNew).toBe(true);
    bars[5] = bar(1300, 201); // the same forming bar, moved by a tick
    inst.recompute();
    expect(p.seen().barState.isNew).toBe(false);
    // Two bars in one pass: a burst of ticks between frames, or one source bar
    // that completed two bricks. The newest bar is new all the same.
    bars.push(bar(1360, 202), bar(1420, 203));
    inst.recompute();
    expect(p.seen().barState).toMatchObject({ isNew: true, isRealtime: true, lastIndex: 7 });
  });

  it('keeps a tail to one appended bar and takes a full calc for two', () => {
    const froms: number[] = [];
    const d: IndicatorDescriptor = {
      id: 'w2-ctx-tail-burst', name: 'T', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      calcTail: (b, _s, from) => { froms.push(from); return { v: b.slice(from).map((x) => x.close) }; },
    };
    const bars = wave(5);
    const inst = new IndicatorInstance(rig(bars).host, d);
    bars.push(bar(1300, 200));
    inst.recompute();
    bars.push(bar(1360, 201), bar(1420, 202));
    inst.recompute();
    expect(froms).toEqual([4]);
    expect(inst.values().v).toEqual(bars.map((x) => x.close));
  });

  it('stays realtime once a tick has landed, including across a symbol change', () => {
    const p = contextProbe('w2-ctx-live');
    const bars = wave(5);
    const inst = new IndicatorInstance(rig(bars).host, p.d);
    bars.push(bar(1300, 200));
    inst.recompute();
    expect(p.seen().barState.isRealtime).toBe(true);
    // Sticky by design: a feed that has ticked once is a live feed, and the
    // history load a symbol change performs does not make it a replay.
    bars.length = 0;
    for (let i = 0; i < 8; i++) bars.push(bar(9000 + i * 60, 500 + i));
    inst.recompute();
    expect(p.seen().barState.isRealtime).toBe(true);
  });

  it('confirms the last bar only once its own span has elapsed on the chart clock', () => {
    const p = contextProbe('w2-ctx-confirm');
    const bars = wave(5); // one minute apart, last bar stamped 1240
    const r = rig(bars);
    r.clock.now = 1299;
    const inst = new IndicatorInstance(r.host, p.d);
    expect(p.seen().barState.isConfirmed).toBe(false);
    r.clock.now = 1300;
    inst.recompute();
    expect(p.seen().barState.isConfirmed).toBe(true);
  });

  it('confirms a chart with no readable span, and reports an empty one', () => {
    const p = contextProbe('w2-ctx-empty');
    const one = rig([bar(1000, 100)]);
    one.clock.now = 0;
    new IndicatorInstance(one.host, p.d);
    // A single bar leaves no gap to measure, so there is nothing to wait for.
    expect(p.seen().barState.isConfirmed).toBe(true);
    new IndicatorInstance(rig([]).host, p.d);
    expect(p.seen().barState.lastIndex).toBe(-1);
    expect(p.seen().barState.isConfirmed).toBe(true);
  });

  it('hands the tail path the same context as a full calc', () => {
    let tailCtx: IndicatorCalcContext | undefined;
    const d: IndicatorDescriptor = {
      id: 'w2-ctx-tail', name: 'T', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      calcTail: (b, _s, from, _prev, _store, ctx) => {
        tailCtx = ctx;
        return { v: b.slice(from).map((x) => x.close) };
      },
    };
    const bars = wave(5);
    const r = rig(bars);
    r.clock.now = 9999; // well past the last bar's span
    const inst = new IndicatorInstance(r.host, d);
    bars.push(bar(1300, 200));
    inst.recompute();
    expect(tailCtx?.barState).toEqual({ isNew: true, isConfirmed: true, isRealtime: true, lastIndex: 5 });
  });
});

describe('pane shading', () => {
  const shade = (id: string, colors: () => readonly (string | null)[]): IndicatorDescriptor => ({
    id, name: 'Shade', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'v' }],
    calc: (b) => ({ v: b.map((x) => x.close) }),
    background: () => colors(),
  });

  it('attaches the layer only once a descriptor actually shades', () => {
    let colors: readonly (string | null)[] = [];
    const r = rig(wave(4));
    const inst = new IndicatorInstance(r.host, shade('w2-bg', () => colors));
    expect(r.primitives).toHaveLength(0);
    colors = ['#101', '#101', null, '#202'];
    inst.recompute();
    expect(r.primitives).toHaveLength(1);
    expect(r.primitives[0]).toBeInstanceOf(IndicatorBackground);
    inst.remove();
    expect(r.primitives).toHaveLength(0);
  });

  it('keeps the layer through a pass that shades nothing', () => {
    // A regime study that leaves every bar null still owns the layer: the next
    // bar may put it back, and detaching per frame would churn a primitive.
    let colors: readonly (string | null)[] = ['#101', '#101'];
    const r = rig(wave(2));
    const inst = new IndicatorInstance(r.host, shade('w2-bg-null', () => colors));
    expect(r.primitives).toHaveLength(1);
    colors = [null, null];
    inst.recompute();
    expect(r.primitives).toHaveLength(1);
  });

  it('hands background the bars, the values and the settings', () => {
    const bars = wave(3);
    let seen: Record<string, unknown> = {};
    const d: IndicatorDescriptor = {
      id: 'w2-bg-ctx', name: 'BG', placement: 'pane',
      inputs: [{ key: 'length', type: 'number', label: 'Length', default: 9 }],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      background: (ctx) => {
        seen = { bars: ctx.bars, values: ctx.values.v, length: ctx.settings.length };
        return ctx.bars.map(() => '#101');
      },
    };
    new IndicatorInstance(rig(bars).host, d);
    expect(seen.bars).toEqual(bars);
    expect(seen.values).toEqual(bars.map((b) => b.close));
    expect(seen.length).toBe(9);
  });
});

describe('price-bar colours', () => {
  const paint = (id: string): IndicatorDescriptor => ({
    id, name: 'Paint', placement: 'onchart', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'v' }],
    calc: (b) => ({ v: b.map((x) => x.close) }),
    barColors: ({ bars }) => bars.map((b, i) => (i % 2 === 0 ? '#ff0000' : b.close > 1e9 ? '#0f0' : null)),
  });

  it('publishes the colours under its own instance id', () => {
    const r = rig(wave(4));
    const inst = new IndicatorInstance(r.host, paint('w2-paint'));
    expect(r.published).toHaveLength(1);
    expect(r.published[0].owner).toBe(inst.id);
    expect(r.published[0].colors).toEqual(['#ff0000', null, '#ff0000', null]);
  });

  it('withdraws them while hidden and republishes when shown again', () => {
    const r = rig(wave(2));
    const inst = new IndicatorInstance(r.host, paint('w2-paint-hide'));
    inst.setVisible(false);
    expect(r.published[r.published.length - 1].colors).toBeNull();
    inst.setVisible(true);
    expect(r.published[r.published.length - 1].colors).toEqual(['#ff0000', null]);
  });

  it('withdraws them on remove', () => {
    const r = rig(wave(2));
    const inst = new IndicatorInstance(r.host, paint('w2-paint-remove'));
    inst.remove();
    const last = r.published[r.published.length - 1];
    expect(last).toEqual({ colors: null, owner: inst.id });
  });

  it('publishes nothing for a descriptor that does not colour the bars', () => {
    const r = rig(wave(2));
    const inst = new IndicatorInstance(r.host, {
      id: 'w2-nopaint', name: 'N', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
    });
    inst.setVisible(false);
    inst.remove();
    expect(r.published).toHaveLength(0);
  });
});

describe('bar-shaped plots', () => {
  const ha = (id: string, calc: IndicatorDescriptor['calc']): IndicatorDescriptor => ({
    id, name: 'HA', placement: 'onchart', inputs: [],
    plots: [{
      key: 'ha', type: 'candlestick', title: 'HA',
      ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' },
      colorBy: ({ index }) => (index === 1 ? '#0f0' : undefined),
    }],
    calc,
  });

  const full: IndicatorDescriptor['calc'] = (b) => ({
    o: b.map((x) => x.open + 1),
    h: b.map((x) => x.high + 2),
    l: b.map((x) => x.low - 1),
    c: b.map((x) => x.close),
  });

  it('draws the four named columns as bars', () => {
    const bars = wave(3);
    const r = rig(bars);
    new IndicatorInstance(r.host, ha('w2-ohlc', full));
    expect(r.drawn.get('HA')).toEqual([
      { time: 1000, open: 101, high: 102, low: 99, close: 100 },
      { time: 1060, open: 102, high: 103, low: 100, close: 101, color: '#0f0' },
      { time: 1120, open: 103, high: 104, low: 101, close: 102 },
    ]);
  });

  it('reads the legend off the close column, which the plot key does not name', () => {
    const r = rig(wave(3));
    new IndicatorInstance(r.host, ha('w2-ohlc-legend', full));
    expect(r.legend.map((v) => v.text)).toEqual(['102.00']);
  });

  it('throws out of the constructor when a named column is missing', () => {
    const partial: IndicatorDescriptor['calc'] = (b) => ({
      o: b.map((x) => x.open), h: b.map((x) => x.high), l: b.map((x) => x.low),
    });
    expect(() => new IndicatorInstance(rig(wave(3)).host, ha('w2-ohlc-missing', partial)))
      .toThrow(/ohlc column "c"/);
  });

  it('throws when a named column is not bar-aligned', () => {
    const short: IndicatorDescriptor['calc'] = (b) => ({
      o: b.map((x) => x.open), h: b.map((x) => x.high), l: b.map((x) => x.low), c: [1],
    });
    expect(() => new IndicatorInstance(rig(wave(3)).host, ha('w2-ohlc-short', short)))
      .toThrow(/must be 3 values/);
  });

  it('still hands over bars when a settings override redraws it as a line', () => {
    // Line, area and histogram all read `close`, so an override degrades to the
    // close column instead of emptying the plot.
    const r = rig(wave(2));
    new IndicatorInstance(r.host, ha('w2-ohlc-line', full), { 'ha:type': 'line' });
    expect((r.drawn.get('HA') as Bar[]).map((b) => b.close)).toEqual([100, 101]);
  });
});

describe('alerts', () => {
  /** Fires on any bar closing above 150, which no bar of `wave` does. */
  const crossing = (id: string): IndicatorDescriptor => ({
    id, name: 'Cross', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'v' }],
    calc: (b) => ({ v: b.map((x) => x.close) }),
    alerts: [{
      id: 'cross-up', title: 'Crossed up', message: 'Closed above 150',
      when: ({ bars, index }) => bars[index].close > 150,
    }],
  });

  const alerts = (r: Rig): IndicatorAlertPayload[] =>
    r.events.filter((e) => e.event === 'indicator:alert').map((e) => e.payload as IndicatorAlertPayload);

  it('announces nothing for the history already on the chart', () => {
    const bars = wave(5, 200); // every bar qualifies
    const r = rig(bars);
    new IndicatorInstance(r.host, crossing('w2-alert-load'));
    expect(alerts(r)).toHaveLength(0);
  });

  it('fires once for a bar a live tick appended', () => {
    const bars = wave(5);
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, crossing('w2-alert-tick'));
    bars.push(bar(1300, 200));
    inst.recompute();
    expect(alerts(r)).toEqual([{
      indicatorId: 'w2-alert-tick',
      instanceId: inst.id,
      alertId: 'cross-up',
      title: 'Crossed up',
      message: 'Closed above 150',
      time: 1300,
      index: 5,
    }]);
  });

  it('fires for each bar one pass appended, in order', () => {
    const bars = wave(5);
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, crossing('w2-alert-burst'));
    bars.push(bar(1300, 200), bar(1360, 210));
    inst.recompute();
    expect(alerts(r).map((a) => [a.time, a.index])).toEqual([[1300, 5], [1360, 6]]);
  });

  it('stays silent when a pass pages history in and appends', () => {
    const bars = wave(5);
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, crossing('w2-alert-burst-history'));
    bars.unshift(bar(940, 300));
    bars.push(bar(1300, 200), bar(1360, 210));
    inst.recompute();
    expect(alerts(r)).toHaveLength(0);
  });

  it('does not fire again while the same forming bar moves', () => {
    const bars = wave(5);
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, crossing('w2-alert-forming'));
    bars.push(bar(1300, 200));
    inst.recompute();
    for (const close of [201, 202, 203]) {
      bars[5] = bar(1300, close);
      inst.recompute();
    }
    expect(alerts(r)).toHaveLength(1);
  });

  it('does not replay the chart when a settings change forces a full recompute', () => {
    const bars = wave(5, 200);
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, crossing('w2-alert-settings'));
    bars.push(bar(1300, 400));
    inst.recompute();
    expect(alerts(r)).toHaveLength(1);
    inst.setSettings({ anything: 1 });
    expect(alerts(r)).toHaveLength(1);
  });

  it('does not replay the chart when a page of history lands at the left edge', () => {
    const bars = wave(5, 200);
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, crossing('w2-alert-history'));
    bars.unshift(bar(940, 300));
    inst.recompute();
    expect(alerts(r)).toHaveLength(0);
  });

  it('defaults the notification text to the title', () => {
    const bars = wave(2);
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, {
      ...crossing('w2-alert-default'),
      alerts: [{ id: 'up', title: 'Up', when: ({ index }) => index === 2 }],
    });
    bars.push(bar(1120, 1));
    inst.recompute();
    expect(alerts(r)[0].message).toBe('Up');
  });
});

/**
 * The host side of the same seams, on a real Chart: the colour overlay reaching
 * the price series, the shading layer reaching the pane, and an alert reaching
 * the chart's own event bus.
 */
describe('on a real chart', () => {
  const makeChart = (data: Bar[]): Chart => {
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      pixelRatio: () => 1,
      shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(data);
    return chart;
  };

  const colorsOf = (chart: Chart): (string | undefined)[] =>
    (chart.primarySeries()?.getData() ?? []).map((b) => b.color);

  const painter = (id: string, color: string): void => {
    registerIndicator({
      id, name: id, placement: 'onchart', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      barColors: ({ bars }) => bars.map((_, i) => (i % 2 === 0 ? color : null)),
    });
  };

  it('paints the candles and gives every bar its own colour back on remove', () => {
    const src = wave(4);
    src[3] = { ...src[3], color: '#ffffff' }; // a bar the host had already coloured
    painter('w2-chart-paint', '#ff0000');
    const chart = makeChart(src);
    const inst = chart.addIndicator('w2-chart-paint');
    expect(colorsOf(chart)).toEqual(['#ff0000', undefined, '#ff0000', '#ffffff']);
    // The data layer holds the caller's own bars, so the overlay must clone
    // rather than write through to the host's array.
    expect(src.map((b) => b.color)).toEqual([undefined, undefined, undefined, '#ffffff']);
    inst.remove();
    expect(colorsOf(chart)).toEqual([undefined, undefined, undefined, '#ffffff']);
  });

  it('takes a fresh snapshot of the candles when the history is replaced', () => {
    // The snapshot is by index, so a symbol change means index i is a different
    // bar and what it remembers about i is worthless.
    painter('w2-chart-resnap', '#ff0000');
    const chart = makeChart(wave(6));
    const inst = chart.addIndicator('w2-chart-resnap');
    // Same bar count, entirely different instrument, so only the anchor time
    // says the snapshot is stale.
    const fresh = Array.from({ length: 6 }, (_, i) => bar(9000 + i * 60, 500 + i));
    fresh[1] = { ...fresh[1], color: '#ffffff' };
    chart.primarySeries()?.setData(fresh);
    expect(colorsOf(chart)).toEqual(['#ff0000', '#ffffff', '#ff0000', undefined, '#ff0000', undefined]);
    inst.remove();
    expect(colorsOf(chart)).toEqual([undefined, '#ffffff', undefined, undefined, undefined, undefined]);
  });

  it('leaves the winning overlay alone when a losing publisher is removed', () => {
    painter('w2-chart-red', '#ff0000');
    painter('w2-chart-blue', '#0000ff');
    const chart = makeChart(wave(4));
    const red = chart.addIndicator('w2-chart-red');
    chart.addIndicator('w2-chart-blue'); // added last, so it publishes last
    expect(colorsOf(chart)[0]).toBe('#0000ff');
    red.remove();
    expect(colorsOf(chart)[0]).toBe('#0000ff');
  });

  it('attaches the shading layer to the indicator own pane', () => {
    registerIndicator({
      id: 'w2-chart-bg', name: 'BG', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      background: ({ bars }) => bars.map(() => 'rgba(255,0,0,0.1)'),
    });
    const chart = makeChart(wave(6));
    const inst = chart.addIndicator('w2-chart-bg');
    const layers = chart.panes()[inst.paneIndex].primitives().filter((p) => p instanceof IndicatorBackground);
    expect(layers).toHaveLength(1);
    expect(chart.panes()[0].primitives().some((p) => p instanceof IndicatorBackground)).toBe(false);
    inst.remove();
    expect(chart.panes()).toHaveLength(1);
    expect(chart.panes().some(pane => pane.primitives().some(p => p instanceof IndicatorBackground))).toBe(false);
  });

  it('routes an alert onto the chart own event bus', () => {
    registerIndicator({
      id: 'w2-chart-alert', name: 'A', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      alerts: [{ id: 'high', title: 'New high', when: ({ bars, index }) => bars[index].close > 150 }],
    });
    const chart = makeChart(wave(6));
    chart.addIndicator('w2-chart-alert');
    const seen: IndicatorAlertPayload[] = [];
    chart.on('indicator:alert', (p) => seen.push(p as IndicatorAlertPayload));
    chart.primarySeries()?.update(bar(1000 + 6 * 60, 200));
    expect(seen.map((p) => [p.alertId, p.time, p.index])).toEqual([['high', 1360, 6]]);
  });

  it('routes an event a Tier-2 lifecycle emits onto the same bus', () => {
    registerIndicator({
      id: 'w2-chart-emit', name: 'E', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      attach: (ctx) => { ctx.emit?.('oi:loaded', { rows: 7 }); },
    });
    const chart = makeChart(wave(4));
    const seen: unknown[] = [];
    chart.on('oi:loaded', (p) => seen.push(p));
    chart.addIndicator('w2-chart-emit');
    expect(seen).toEqual([{ rows: 7 }]);
  });
});

describe('the calculation context: tickSize', () => {
  it('passes a host tick through', () => {
    const p = contextProbe('w2-tick-yes');
    new IndicatorInstance(rig(wave(5), { tickSize: () => 0.05 }).host, p.d);
    expect(p.seen().tickSize).toBe(0.05);
  });

  it('drops the price scale sentinel rather than calling it a tick', () => {
    // 0 means "infer precision from the visible range". An indicator sizing a
    // range in ticks has to tell that apart from a genuine one paisa.
    const p = contextProbe('w2-tick-zero');
    new IndicatorInstance(rig(wave(5), { tickSize: () => 0 }).host, p.d);
    expect(p.seen().tickSize).toBeUndefined();
  });

  it('reports nothing for a host that predates the member', () => {
    const p = contextProbe('w2-tick-absent');
    new IndicatorInstance(rig(wave(5)).host, p.d);
    expect(p.seen().tickSize).toBeUndefined();
  });

  it('the chart reports its own price scale minMove', () => {
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      pixelRatio: () => 1,
      shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(wave(30));

    const p = contextProbe('w2-tick-chart');
    registerIndicator(p.d);
    const inst = chart.addIndicator('w2-tick-chart');
    expect(p.seen().tickSize).toBeUndefined();

    chart.setPriceScaleOptions({ minMove: 0.05 });
    inst.setSettings({ nudge: 1 });
    expect(p.seen().tickSize).toBe(0.05);
  });
});
