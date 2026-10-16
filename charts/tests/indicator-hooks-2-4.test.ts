/**
 * The 2.4.0 descriptor additions, each pinned where it is consumed: an alert
 * message computed per bar, a fill that follows its plots onto the price
 * pane, a candle plot coloured body, wick and border apart, the two new marker
 * glyphs and the two edge-pinned positions, a drawing that answers hover and
 * click, a table that fits its own type, and the two new input types the
 * widget form renders.
 */
import { describe, it, expect } from 'vitest';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar, SeriesDataItem } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import { drawCandles, DEFAULT_CANDLE_STYLE } from '../src/render/candles';
import { drawShape, SeriesMarkers } from '../src/primitives/markers';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import { ChartTable } from '../src/primitives/table';
import { controlsFromInputs } from '../src/widget/form';
import { registerInterval } from '../src/feed/intervals';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { makeCtx, type Op } from './helpers/fake-ctx';

const bar = (time: number, close: number): Bar => ({ time, open: close - 1, high: close + 2, low: close - 2, close });
const wave = (n: number): Bar[] => Array.from({ length: n }, (_, i) => bar(1000 + i * 60, 100 + i));

interface Rig {
  host: IndicatorHost;
  fills: number[];
  emitted: { event: string; payload: unknown }[];
  data: SeriesDataItem[][];
  styles: Record<string, unknown>[];
  legend: string[][];
}

function rig(source: Bar[]): Rig {
  const fills: number[] = [];
  const emitted: { event: string; payload: unknown }[] = [];
  const data: SeriesDataItem[][] = [];
  const styles: Record<string, unknown>[] = [];
  const legend: string[][] = [];
  const host: IndicatorHost = {
    addIndicatorLegend: () => ({ setOptions: () => {}, setValues: (v: { text: string }[]) => { legend.push(v.map((x) => x.text)); } }) as never,
    removeIndicatorLegend: () => {},
    legendRowsOn: () => 0,
    addIndicatorSeries: (_t, _pane, style): SeriesApi => {
      const slot = data.length;
      data.push([]);
      styles.push(style ?? {});
      return {
        setData: (items) => { data[slot] = items.slice(); }, prependData: () => {}, update: () => {}, getData: () => [],
        applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
        createMarkers: () => ({ setMarkers: () => {} }) as never,
      };
    },
    addIndicatorLevel: () => ({}) as never,
    removeIndicatorLevel: () => {},
    addIndicatorFill: (_f, paneIndex) => { fills.push(paneIndex); },
    removeIndicatorFill: () => {},
    removeIndicatorMarkers: () => {},
    addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
    removeIndicatorTable: () => {},
    sourceBars: () => source,
    nextPaneIndex: () => 2,
    setPaneRange: () => {},
    emit: (event, payload) => { emitted.push({ event, payload }); },
  };
  return { host, fills, emitted, data, styles, legend };
}

describe('alert message as a function', () => {
  it('is evaluated with the bar the alert fired on', () => {
    const bars = wave(3);
    const d: IndicatorDescriptor = {
      id: 'h-alert', name: 'A', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close) }),
      alerts: [{
        id: 'every', title: 'Bar',
        message: ({ bars: b, index }) => `close ${b[index].close} at ${b[index].time}`,
        when: () => true,
      }],
    };
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, d);
    // A history load announces nothing; a tail-only change does.
    expect(r.emitted.filter((e) => e.event === 'indicator:alert')).toHaveLength(0);
    bars.push(bar(1000 + 3 * 60, 200));
    inst.recompute();
    const fired = r.emitted.filter((e) => e.event === 'indicator:alert');
    expect(fired).toHaveLength(1);
    expect((fired[0].payload as { message: string }).message).toBe('close 200 at 1180');
  });
});

describe('fill overlay', () => {
  const d = (overlay: boolean | undefined): IndicatorDescriptor => ({
    id: 'h-fill', name: 'F', placement: 'pane', inputs: [],
    plots: [
      { key: 'a', type: 'line', title: 'a', overlay: true },
      { key: 'b', type: 'line', title: 'b', overlay: true },
    ],
    fills: [{ between: ['a', 'b'], overlay }],
    calc: (b) => ({ a: b.map((x) => x.high), b: b.map((x) => x.low) }),
  });

  it('lands on the price pane when asked, and in the study pane otherwise', () => {
    const r1 = rig(wave(3));
    new IndicatorInstance(r1.host, d(true));
    expect(r1.fills).toEqual([0]);
    const r2 = rig(wave(3));
    new IndicatorInstance(r2.host, d(undefined));
    expect(r2.fills).toEqual([2]);
  });
});

describe('colorBy split into body, wick and border', () => {
  it('reaches the candle plot as three bar colours and a value plot as its body only', () => {
    const d: IndicatorDescriptor = {
      id: 'h-split', name: 'S', placement: 'pane', inputs: [],
      plots: [
        { key: 'c', type: 'candlestick', title: 'c', ohlc: { open: 'o', high: 'h', low: 'l', close: 'x' },
          colorParts: () => ({ body: '#111111', wick: '#222222', border: '#333333' }) },
        { key: 'x', type: 'line', title: 'x', colorParts: () => ({ body: '#444444', wick: '#555555' }) },
        { key: 'o', type: 'line', title: 'o', colorBy: () => '#666666' },
      ],
      calc: (b) => ({
        o: b.map((x) => x.open), h: b.map((x) => x.high), l: b.map((x) => x.low), x: b.map((x) => x.close),
      }),
    };
    const r = rig(wave(2));
    new IndicatorInstance(r.host, d);
    const candle = r.data[0][0] as Bar;
    expect(candle.color).toBe('#111111');
    expect(candle.wickColor).toBe('#222222');
    expect(candle.borderColor).toBe('#333333');
    const line = r.data[1][0] as { color?: string; wickColor?: string };
    expect(line.color).toBe('#444444');
    expect(line.wickColor).toBeUndefined();
    expect((r.data[2][0] as { color?: string }).color).toBe('#666666');
  });
});

describe('candle renderer per-bar wick and border colour', () => {
  const priceToY = (p: number): number => 100 - p;
  const rects = (ops: Op[]): Op[] => ops.filter((o) => o.type === 'fillRect');

  it('paints the wick in its own colour and the body in the bar colour', () => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, [{ x: 10, bar: { time: 1, open: 10, high: 12, low: 8, close: 11, color: '#111111', wickColor: '#222222' } }],
      priceToY, 10, 1, DEFAULT_CANDLE_STYLE);
    const r = rects(rec.ops);
    expect(r[0].fillStyle).toBe('#222222');
    expect(r[1].fillStyle).toBe('#111111');
    const ring = rec.ops.find((o) => o.type === 'strokeRect');
    expect(ring?.strokeStyle).toBe('#111111');
  });

  it('takes a per-bar border colour over the bar colour', () => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, [{ x: 10, bar: { time: 1, open: 10, high: 12, low: 8, close: 11, color: '#111111', borderColor: '#333333' } }],
      priceToY, 10, 1, DEFAULT_CANDLE_STYLE);
    expect(rec.ops.find((o) => o.type === 'strokeRect')?.strokeStyle).toBe('#333333');
  });

  it('still draws the body at the wick tier when the wick is a different colour', () => {
    // 1.5 px spacing: a 1 px body under a 1 px wick, the tier the body is skipped at.
    const plain = makeCtx();
    drawCandles(plain.ctx, [{ x: 10, bar: { time: 1, open: 10, high: 12, low: 8, close: 11, color: '#111111' } }],
      priceToY, 1.5, 1, DEFAULT_CANDLE_STYLE);
    expect(rects(plain.rec.ops)).toHaveLength(1);
    const split = makeCtx();
    drawCandles(split.ctx, [{ x: 10, bar: { time: 1, open: 10, high: 12, low: 8, close: 11, color: '#111111', wickColor: '#222222' } }],
      priceToY, 1.5, 1, DEFAULT_CANDLE_STYLE);
    expect(rects(split.rec.ops)).toHaveLength(2);
  });
});

describe('marker glyphs and edge positions', () => {
  it('draws a cross as two bars and an xcross as two stroked diagonals', () => {
    const cross = makeCtx();
    drawShape(cross.ctx, 'cross', 50, 50, 12, '#f00');
    expect(cross.rec.count('fillRect')).toBe(2);
    const x = makeCtx();
    drawShape(x.ctx, 'xcross', 50, 50, 12, '#f00');
    expect(x.rec.count('moveTo')).toBe(2);
    expect(x.rec.count('lineTo')).toBe(2);
    expect(x.rec.count('stroke')).toBe(1);
  });

  function makeRc(): { rc: PrimitiveRenderContext; seriesId: number } {
    const dl = new DataLayer();
    const seriesId = dl.createSeries();
    dl.setSeriesData(seriesId, [bar(100, 50), bar(200, 52), bar(300, 48)]);
    const priceScale = new PriceScale();
    priceScale.setHeight(400);
    priceScale.setPriceRange({ min: 40, max: 60 });
    const timeScale = new TimeScale({ barSpacing: 20, rightOffset: 0 });
    timeScale.setWidth(600);
    timeScale.setBaseIndex(dl.baseIndex);
    return {
      rc: { timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme },
      seriesId,
    };
  }

  it('pins paneTop and paneBottom markers to the plot edges, clear of the scale', () => {
    const { rc, seriesId } = makeRc();
    const m = new SeriesMarkers(seriesId);
    m.setMarkers([
      { time: 200, position: 'paneTop', shape: 'circle', size: 'medium', color: '#fff' },
      { time: 200, position: 'paneBottom', shape: 'circle', size: 'medium', color: '#fff' },
    ]);
    const { ctx, rec } = makeCtx();
    m.draw(ctx, rc);
    const arcs = rec.ops.filter((o) => o.type === 'arc');
    expect(arcs).toHaveLength(2);
    // medium is 12 px: centre 6 px in plus a 4 px inset, the second one stacked below it.
    expect(arcs[0].args[1]).toBe(10);
    expect(arcs[1].args[1]).toBe(400 - 10 - 16);
  });
});

describe('drawing tooltips and hit ids', () => {
  const rcOf = (hoverId: string | null): PrimitiveRenderContext => ({
    timeScale: { indexToX: (i: number) => i * 10 },
    priceScale: { priceToY: (p: number) => 500 - p },
    dataLayer: { timeToIndexFloat: (t: number) => (t - 1000) / 60 },
    plotWidth: 400, plotHeight: 300, priceAxisWidth: 60, dpr: 1, theme: darkTheme, hoverId,
  } as unknown as PrimitiveRenderContext);
  const at = (i: number, price: number) => ({ time: 1000 + i * 60, price });
  const texts = (ops: Op[]): (string | undefined)[] => ops.filter((o) => o.type === 'fillText').map((o) => o.text);

  it('answers a hit on a label or box that carries an id or a tooltip, and nothing else', () => {
    const d = new IndicatorDrawings();
    d.setItems([
      { kind: 'label', at: at(6, 250), text: 'Z', id: 'zone-1', tooltip: 'Zone 1\nsize 12' },
      { kind: 'box', from: at(1, 260), to: at(3, 240), tooltip: 'demand' },
      { kind: 'line', from: at(0, 200), to: at(4, 200) },
      { kind: 'label', at: at(8, 250), text: 'mute' },
    ]);
    d.draw(makeCtx().ctx, rcOf(null));
    // The box has no id, so its tooltip text is what a click reports.
    expect(d.hitTest(20, 250)?.externalId).toBe('demand');
    expect(d.hitTest(60, 250)?.externalId).toBe('zone-1');
    // A line, and a label with nothing to say, are ink only.
    expect(d.hitTest(20, 300)).toBeNull();
    expect(d.hitTest(80, 250)).toBeNull();
  });

  it('draws the tooltip only while the chart reports the pointer on it', () => {
    const d = new IndicatorDrawings();
    d.setItems([{ kind: 'label', at: at(2, 250), text: 'Z', id: 'zone-1', tooltip: 'Zone 1\nsize 12' }]);
    const idle = makeCtx();
    d.draw(idle.ctx, rcOf(null));
    expect(texts(idle.rec.ops)).toEqual(['Z']);
    const hover = makeCtx();
    d.draw(hover.ctx, rcOf('zone-1'));
    expect(texts(hover.rec.ops)).toEqual(['Z', 'Zone 1', 'size 12']);
  });
});

describe('table fontSize auto', () => {
  function rc(): PrimitiveRenderContext {
    const priceScale = new PriceScale();
    priceScale.setHeight(400);
    priceScale.setPriceRange({ min: 0, max: 100 });
    const timeScale = new TimeScale();
    timeScale.setWidth(600);
    return { timeScale, priceScale, dataLayer: new DataLayer(), plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme };
  }
  const sizeOf = (op: Op): number => Number(/(\d+)px/.exec(op.font ?? '')?.[1]);

  it('fits each cell to its row and column, so only the long cell shrinks', () => {
    const t = new ChartTable({ fontSize: 'auto', cellWidth: [40, 200], cellHeight: 20 });
    t.setRows([[{ text: '123456789012' }, { text: 'ab' }]]);
    const { ctx, rec } = makeCtx();
    t.draw(ctx, rc());
    const cells = rec.ops.filter((o) => o.type === 'fillText');
    expect(sizeOf(cells[0])).toBe(6);
    expect(sizeOf(cells[1])).toBe(12);
  });

  it('leaves a numeric size exactly as it was', () => {
    const t = new ChartTable({ fontSize: 11, cellWidth: [40, 200], cellHeight: 20 });
    t.setRows([[{ text: '123456789012' }, { text: 'ab' }]]);
    const { ctx, rec } = makeCtx();
    t.draw(ctx, rc());
    expect(rec.ops.filter((o) => o.type === 'fillText').map(sizeOf)).toEqual([11, 11]);
  });
});

describe('interval and time inputs in the widget form', () => {
  it('renders an interval as a select over the registered codes with the chart as the first entry', () => {
    const off = registerInterval({ code: '15m', bucketing: { mode: 'interval', seconds: 900 } });
    try {
      const [tf, at] = controlsFromInputs([
        { key: 'tf', type: 'interval', label: 'Timeframe', default: '' },
        { key: 'at', type: 'time', label: 'Anchor', default: '2026-09-14 09:15' },
      ]);
      expect(tf.kind).toBe('select');
      expect(tf.options?.[0]).toEqual({ label: 'Chart', value: '' });
      expect(tf.options?.some((o) => o.value === '15m')).toBe(true);
      expect(at.kind).toBe('text');
    } finally {
      off();
    }
  });
});
