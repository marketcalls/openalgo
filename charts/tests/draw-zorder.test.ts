/**
 * Z-order: the two layers per pane, the paint order inside each, the handles
 * that must stay visible whatever band a drawing is in, and the controller
 * calls that move a drawing through the stack.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import { DrawingController, DrawingLayer, sortByZIndex } from '../src/draw/index';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Bar } from '../src/model/bar';
import type { DataLayer } from '../src/model/data-layer';
import type { IPrimitive } from '../src/primitives/primitive';
import type { Drawing } from '../src/draw/types';

const W = 800;
const H = 600;

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * 60, open: c, high: c + 2, low: c - 2, close: c, volume: 10 };
  });

function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div') as unknown as HTMLElement, {
    document: fakeDocument(),
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
    pixelRatio: () => 1, shortcuts: false,
  });
  chart.applySize(W, H);
  chart.addSeries('candlestick').setData(bars(120));
  return chart;
}

/** Identity mapping: time is x, price is y. */
const rc = {
  timeScale: { indexToX: (i: number) => i },
  priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
  dataLayer: { timeToIndexFloat: (t: number) => t },
  plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
} as never;

/** A host that keeps the primitives it is handed, so the layers are inspectable. */
function capturingHost(): DrawingChartHost & { layers: { layer: DrawingLayer; pane: number }[] } {
  const layers: { layer: DrawingLayer; pane: number }[] = [];
  return {
    layers,
    on: () => () => {},
    emit: () => {},
    addPrimitive: (p: IPrimitive, pane = 0) => { layers.push({ layer: p as DrawingLayer, pane }); },
    removePrimitive: (p: IPrimitive) => {
      const i = layers.findIndex((l) => l.layer === p);
      if (i >= 0) layers.splice(i, 1);
    },
    dataLayer: { baseIndex: 2, indexToTime: (i: number) => 1700000000 + i * 300 } as unknown as DataLayer,
    getVisibleLogicalRange: () => null,
    drawingState: () => null,
    setDrawingState: () => {},
  };
}

const lineAt = (id: string, color: string, zIndex = 0, extra: Partial<Drawing> = {}): Drawing => ({
  id, tool: 'trend-line', paneIndex: 0, zIndex, style: { color },
  points: [{ time: 100, price: 100 }, { time: 300, price: 300 }],
  ...extra,
});

/** The stroke colours a layer painted, in order. */
const strokes = (layer: DrawingLayer): string[] => {
  const { ctx, rec } = makeCtx();
  layer.draw(ctx, rc);
  return rec.ops.filter((o) => o.type === 'stroke').map((o) => o.strokeStyle ?? '');
};

const arcs = (layer: DrawingLayer): number => {
  const { ctx, rec } = makeCtx();
  layer.draw(ctx, rc);
  return rec.count('arc');
};

describe('two layers per pane', () => {
  it('adds a bottom and a top layer for each pane a drawing lands on', () => {
    const host = capturingHost();
    const draw = new DrawingController(host);
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }] });
    expect(host.layers.map((l) => `${l.pane}:${l.layer.zOrder()}`)).toEqual(['0:bottom', '0:top']);
    draw.add({ tool: 'trend-line', paneIndex: 2, style: {}, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }] });
    expect(host.layers.map((l) => `${l.pane}:${l.layer.zOrder()}`)).toEqual(['0:bottom', '0:top', '2:bottom', '2:top']);
    draw.destroy();
    expect(host.layers).toEqual([]);
  });

  it('homes a negative z-order under the series and re-homes it when it crosses zero', () => {
    const host = capturingHost();
    const draw = new DrawingController(host);
    const d = draw.add({
      tool: 'trend-line', paneIndex: 0, zIndex: -1, style: { color: '#c0ffee' },
      points: [{ time: 100, price: 100 }, { time: 300, price: 300 }],
    });
    const bottom = host.layers[0].layer;
    const top = host.layers[1].layer;
    expect(strokes(bottom)).toContain('#c0ffee');
    expect(strokes(top)).not.toContain('#c0ffee');

    draw.setZIndex(d.id, 0);
    expect(strokes(bottom)).not.toContain('#c0ffee');
    expect(strokes(top)).toContain('#c0ffee');

    draw.sendBehindSeries(d.id);
    expect(strokes(bottom)).toContain('#c0ffee');
    expect(strokes(top)).not.toContain('#c0ffee');
  });

  it('paints in z-order, then array order', () => {
    const layer = new DrawingLayer('top');
    layer.setDrawings([
      lineAt('a', '#a', 2), lineAt('b', '#b', 0), lineAt('c', '#c', 1), lineAt('d', '#d', 0),
    ]);
    const order = strokes(layer);
    const at = (c: string) => order.indexOf(c);
    expect(at('#b')).toBeLessThan(at('#d'));   // equal z: array order
    expect(at('#d')).toBeLessThan(at('#c'));
    expect(at('#c')).toBeLessThan(at('#a'));
    expect(sortByZIndex([lineAt('x', '#x', 1), lineAt('y', '#y', -1)]).map((d) => d.id)).toEqual(['y', 'x']);
  });

  it('treats a missing z-order as zero rather than failing the sort', () => {
    const broken = { ...lineAt('n', '#n'), zIndex: Number.NaN };
    expect(sortByZIndex([lineAt('p', '#p', 1), broken, lineAt('m', '#m', -1)]).map((d) => d.id)).toEqual(['m', 'n', 'p']);
  });
});

describe('handles across the pair', () => {
  it('paints the handles of a selected under-series drawing on the top layer', () => {
    const bottom = new DrawingLayer('bottom');
    const top = new DrawingLayer('top');
    top.setBelow(bottom);
    bottom.setDrawings([lineAt('under', '#u', -1)]);
    top.setDrawings([lineAt('over', '#o', 0)]);
    bottom.setSelected(['under']);
    top.setSelected(['under']);
    expect(arcs(top)).toBe(2);       // the two anchors
    expect(arcs(bottom)).toBe(0);    // never under the candles
  });

  it('paints handles for every selected drawing', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([lineAt('a', '#a'), lineAt('b', '#b'), lineAt('c', '#c')]);
    top.setSelected(['a', 'c']);
    expect(arcs(top)).toBe(4);
  });

  it('a standalone layer still paints its own handles', () => {
    const layer = new DrawingLayer('bottom');
    layer.setDrawings([lineAt('a', '#a', -1)]);
    layer.setSelected(['a']);
    expect(arcs(layer)).toBe(2);
  });

  it('draws no handles for a locked or hidden selection', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([lineAt('a', '#a', 0, { locked: true }), lineAt('b', '#b', 0, { visible: false })]);
    top.setSelected(['a', 'b']);
    expect(arcs(top)).toBe(0);
  });
});

describe('hit-testing across the pair', () => {
  const filledBox = (id: string, zIndex: number): Drawing => ({
    id, tool: 'rectangle', paneIndex: 0, zIndex, style: { fill: true },
    points: [{ time: 100, price: 100 }, { time: 300, price: 300 }],
  });

  it('the adopted bottom layer answers nothing; the top answers for both', () => {
    const bottom = new DrawingLayer('bottom');
    const top = new DrawingLayer('top');
    top.setBelow(bottom);
    bottom.setDrawings([filledBox('under', -1)]);
    expect(bottom.hitTest(200, 200, rc)).toBeNull();
    expect(top.hitTest(200, 200, rc)?.externalId).toBe('draw:under');
    // Released, it answers for itself again.
    top.setBelow(null);
    expect(bottom.hitTest(200, 200, rc)?.externalId).toBe('draw:under');
    expect(top.hitTest(200, 200, rc)).toBeNull();
  });

  it('a body on the top layer beats a closer body under the series', () => {
    const bottom = new DrawingLayer('bottom');
    const top = new DrawingLayer('top');
    top.setBelow(bottom);
    bottom.setDrawings([filledBox('under', -1)]);        // distance 0 anywhere inside
    top.setDrawings([lineAt('over', '#o')]);            // the diagonal of that box
    expect(top.hitTest(200, 204, rc)?.externalId).toBe('draw:over');   // 3 px off the line
    expect(top.hitTest(120, 280, rc)?.externalId).toBe('draw:under');  // far from the line
  });

  it('a handle of a selected under-series drawing beats every body', () => {
    const bottom = new DrawingLayer('bottom');
    const top = new DrawingLayer('top');
    top.setBelow(bottom);
    bottom.setDrawings([lineAt('under', '#u', -1)]);
    top.setDrawings([filledBox('over', 0)]);
    bottom.setSelected(['under']);
    top.setSelected(['under']);
    expect(top.hitTest(100, 100, rc)?.externalId).toBe('draw:under#0');
    expect(top.hitTest(300, 300, rc)?.externalId).toBe('draw:under#1');
  });

  it('within a layer the shape painted last wins, whatever the list order', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([lineAt('high', '#h', 5), lineAt('low', '#l', 0)]);
    expect(top.hitTest(200, 200, rc)?.externalId).toBe('draw:high');
  });
});

describe('controller z-order calls', () => {
  const three = (draw: DrawingController): [Drawing, Drawing, Drawing] => [
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }] }),
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }] }),
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }] }),
  ];
  const order = (draw: DrawingController) => draw.drawings().map((d) => `${d.id}@${d.zIndex}`);

  it('bringToFront moves to the end of the list at the highest z of its band', () => {
    const draw = new DrawingController(makeChart());
    const [a, b, c] = three(draw);
    draw.setZIndex(c.id, 4);
    draw.bringToFront(a.id);
    expect(order(draw)).toEqual([`${b.id}@0`, `${c.id}@4`, `${a.id}@4`]);
    // Ties break by list order, so it is now painted after c.
    const stack = sortByZIndex(draw.drawings()).map((d) => d.id);
    expect(stack[stack.length - 1]).toBe(a.id);
  });

  it('sendToBack moves to the start of the list at the lowest z of its band', () => {
    const draw = new DrawingController(makeChart());
    const [a, b, c] = three(draw);
    draw.setZIndex(a.id, 2);
    draw.sendToBack(c.id);
    expect(order(draw)).toEqual([`${c.id}@0`, `${a.id}@2`, `${b.id}@0`]);
  });

  it('never crosses the series: front and back are settled within a band', () => {
    const draw = new DrawingController(makeChart());
    const [a, b] = three(draw);
    draw.sendBehindSeries(a.id);
    expect(draw.get(a.id)?.zIndex).toBe(-1);
    draw.bringToFront(a.id);
    expect(draw.get(a.id)?.zIndex).toBe(-1);     // still under the series
    draw.sendToBack(b.id);
    expect(draw.get(b.id)?.zIndex).toBe(0);      // still over it
    draw.bringAboveSeries(a.id);
    expect(draw.get(a.id)?.zIndex).toBe(0);
    // Already on that side: no change, no history.
    draw.fromJSON(draw.toJSON());                // keeps the drawings, clears the history
    draw.bringAboveSeries(a.id);
    expect(draw.canUndo()).toBe(false);
    draw.sendBehindSeries(a.id);
    expect(draw.canUndo()).toBe(true);
  });

  it('is one undo entry per call and reports a reorder', () => {
    const chart = makeChart();
    const kinds: string[] = [];
    chart.on('drawing:change', (p) => kinds.push((p as { kind: string }).kind));
    const draw = new DrawingController(chart);
    const [a, b] = three(draw);
    kinds.length = 0;
    draw.bringToFront(a.id);
    draw.setZIndex(b.id, -2);
    expect(kinds).toEqual(['reorder', 'reorder']);
    expect(draw.undo()).toBe(true);
    expect(draw.get(b.id)?.zIndex).toBe(0);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings().map((d) => d.id)[0]).toBe(a.id);
  });

  it('records nothing for a call that changes nothing', () => {
    const draw = new DrawingController(makeChart());
    const [a, , c] = three(draw);
    draw.fromJSON(draw.toJSON());                // keeps the drawings, clears the history
    draw.bringToFront(c.id);      // already last at the band's max
    draw.sendToBack(a.id);        // already first at the band's min
    draw.setZIndex(a.id, 0);      // already 0
    draw.setZIndex(a.id, Number.POSITIVE_INFINITY);
    draw.bringToFront('nope');
    expect(draw.drawings()).toHaveLength(3);
    expect(draw.canUndo()).toBe(false);
  });

  it('keeps bands per pane: a drawing on another pane does not set the ceiling', () => {
    const draw = new DrawingController(makeChart());
    const [a] = three(draw);
    const far = draw.add({ tool: 'trend-line', paneIndex: 1, zIndex: 9, style: {}, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }] });
    draw.bringToFront(a.id);
    expect(a.zIndex).toBe(0);
    expect(far.zIndex).toBe(9);
  });
});
