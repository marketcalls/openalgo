import { describe, expect, it } from 'vitest';
import { clipPolygon, clippedLine, insidePolygon, sampleArc } from '../src/draw/advanced-shared';
import { levelColor } from '../src/draw/levels';
import { ADVANCED_LINE_TOOLS } from '../src/draw/advanced-lines';
import { DataLayer } from '../src/model/data-layer';
import { RecordingContext } from './helpers/fake-ctx';
import type { Drawing, DrawingPoint, DrawingTool } from '../src/draw/types';
import type { PrimitiveRenderContext, Bar } from '../src';

const rc = (dpr = 1, bars: Bar[] = []): PrimitiveRenderContext => ({
  plotWidth: 800, plotHeight: 400, dpr, priceAxisWidth: 60,
  theme: { background: '#101010', lineColor: '#123456' },
  priceScale: { priceToY: (p: number) => 400 - p * 10, format: (p: number) => p.toFixed(2) },
  timeScale: { indexToX: (i: number) => 100 + i * 100 },
  dataLayer: { timeToIndexFloat: (t: number) => t / 60 }, bars: () => bars,
} as unknown as PrimitiveRenderContext);
const anchors = [{ time: 0, price: 10 }, { time: 60, price: 20 }, { time: 120, price: 14 }, { time: 180, price: 16 }];
function tool(id: string): DrawingTool { return ADVANCED_LINE_TOOLS.find(t => t.id === id)!; }
function drawing(id: string, points = anchors.slice(0, tool(id).points), patch: Partial<Drawing> = {}): Drawing {
  return { id: 'test', tool: id, points, style: { ...tool(id).defaultStyle }, paneIndex: 0, zIndex: 0, ...patch };
}
function project(points: DrawingPoint[], context = rc()) {
  return points.map(p => ({ x: context.timeScale.indexToX(context.dataLayer.timeToIndexFloat(p.time)), y: context.priceScale.priceToY(p.price) }));
}
function paint(d: Drawing, context = rc()) {
  const rec = new RecordingContext();
  rec.measureText = text => ({ width: text.length * (Number(/([0-9.]+)px/.exec(rec.font)?.[1]) || 11) * 0.6 });
  let alpha = 1;
  const stack: number[] = [];
  Object.defineProperty(rec, 'globalAlpha', { get: () => alpha, set: (v: number) => { alpha = v; } });
  const save = rec.save.bind(rec), restore = rec.restore.bind(rec), fill = rec.fill.bind(rec);
  rec.save = () => { stack.push(alpha); save(); };
  rec.restore = () => { alpha = stack.pop() ?? 1; restore(); };
  rec.fill = () => { fill(); rec.ops[rec.ops.length - 1].args.push(alpha); };
  tool(d.tool).draw({ ctx: rec as unknown as CanvasRenderingContext2D, rc: context,
    pts: project(d.points, context).map(p => ({ x: p.x * context.dpr, y: p.y * context.dpr })),
    drawing: d, style: { color: '#123456', lineWidth: 1.5, ...d.style }, selected: false, formatPrice: p => p.toFixed(2) });
  return rec;
}
const moves = (r: RecordingContext) => r.ops.filter(o => o.type === 'moveTo').map(o => o.args);
const ends = (r: RecordingContext) => r.ops.filter(o => o.type === 'lineTo').map(o => o.args);
const texts = (r: RecordingContext) => r.ops.filter(o => o.type === 'fillText').map(o => o.text!);
function hit(d: Drawing, x: number, y: number, context = rc()) {
  return tool(d.tool).distance(x, y, { drawing: d, pts: project(d.points, context), rc: context });
}
const barsOf = (closes: number[]) => closes.map((close, i) => ({ time: i * 60, open: close, high: close, low: close, close, volume: 1 }));

describe('advanced line descriptors', () => {
  it('provides every required distinct descriptor', () => {
    expect(ADVANCED_LINE_TOOLS.map(t => t.id)).toEqual([
      'disjoint-channel', 'flat-top-bottom', 'regression-channel', 'pitchfork', 'schiff-pitchfork',
      'modified-schiff-pitchfork', 'inside-pitchfork', 'info-line', 'trend-angle',
      'fib-extension-two-point', 'fib-speed-resistance-fan', 'icon-stamp',
    ]);
    expect(ADVANCED_LINE_TOOLS.every(t => t.settings!.fields.length > 0)).toBe(true);
  });
  it('keeps all four disjoint boundary endpoints independent', () => {
    const d = drawing('disjoint-channel', anchors, { style: { fill: false } });
    expect(moves(paint(d))).toEqual([[100, 300], [300, 260]]);
    expect(ends(paint(d))).toEqual([[200, 200], [400, 240]]);
    expect(hit(d, 350, 250)).toBe(0);
    expect(hit(d, 350, 300)).toBeGreaterThan(6);
  });
  it.each([
    { extendRight: true }, { extendLeft: true }, { extendLeft: true, extendRight: true },
  ])('keeps vertical channel strokes and fill at their anchors for %j', extension => {
    const points = [{ time: 0, price: 30 }, { time: 0, price: 20 }, { time: 60, price: 30 }, { time: 60, price: 20 }];
    for (const reversed of [false, true]) {
      const ordered = reversed ? [points[1], points[0], points[3], points[2]] : points;
      const baseline = drawing('disjoint-channel', ordered, { style: { fill: true } });
      const extended = drawing('disjoint-channel', ordered, { style: { fill: true, ...extension } });
      for (const dpr of [1, 2]) {
        const context = rc(dpr);
        expect(paint(extended, context).ops).toEqual(paint(baseline, context).ops);
        expect(hit(extended, 150, 150, context)).toBe(0);
        expect(hit(extended, 150, 300, context)).toBeCloseTo(Math.hypot(50, 100));
        expect(hit(extended, 150, 50, context)).toBeCloseTo(Math.hypot(50, 50));
      }
    }
  });
  it('extends only the sloped side of a mixed vertical and sloped channel', () => {
    const d = drawing('disjoint-channel', [
      { time: 0, price: 30 }, { time: 0, price: 20 }, { time: 60, price: 30 }, { time: 120, price: 20 },
    ], { style: { fill: true, extendRight: true } });
    for (const dpr of [1, 2]) {
      const context = rc(dpr);
      expect(ends(paint(d, context)).slice(-2)).toEqual([[100 * dpr, 200 * dpr], [500 * dpr, 400 * dpr]]);
      expect(hit(d, 150, 150, context)).toBe(0);
      expect(hit(d, 100, 300, context)).toBeGreaterThan(6);
    }
  });
  it('keeps the flat boundary horizontal across the sloped boundary span', () => {
    const d = drawing('flat-top-bottom', anchors.slice(0, 3), { style: { fill: false } });
    expect(moves(paint(d))).toEqual([[100, 300], [100, 260]]);
    expect(ends(paint(d))).toEqual([[200, 200], [200, 260]]);
    const p = tool(d.tool).constrain!(d.points, 2);
    expect(p[2]).toEqual({ time: 30, price: 14 });
  });
  it('does not accept the empty corners of a filled channel bounding box', () => {
    const d = drawing('disjoint-channel', anchors, { style: { fill: true } });
    expect(hit(d, 250, 250)).toBe(0);
    expect(hit(d, 380, 205)).toBeGreaterThan(6);
  });
  it.each([
    ['pitchfork', [100, 300]], ['schiff-pitchfork', [100, 250]],
    ['modified-schiff-pitchfork', [150, 250]], ['inside-pitchfork', [250, 230]],
  ])('uses the correct %s median origin', (id, origin) => {
    const d = drawing(id as string, anchors.slice(0, 3), { style: { fill: false, levels: [{ ratio: 0 }] } });
    expect(moves(paint(d))[0]).toEqual(origin);
  });
  it('emits parallel pitchfork tines and no hits for disabled additional levels', () => {
    const d = drawing('pitchfork', anchors.slice(0, 3), { style: { fill: false, levels: [{ ratio: 0 }, { ratio: 1, enabled: false }] } });
    expect(paint(d).count('stroke')).toBe(2); // median and base
    expect(hit(d, 450, 230)).toBeGreaterThan(6);
    d.style.levels![1].enabled = true;
    expect(paint(d).count('stroke')).toBe(4);
    const r = paint(d);
    const start = moves(r)[1];
    const end = ends(r)[1];
    expect((end[1] - start[1]) / (end[0] - start[0])).toBeCloseTo(-70 / 150);
  });
  it('fills an extended channel through the plot corner between boundary exits', () => {
    const d = drawing('disjoint-channel', anchors, { style: { fill: true, extendRight: true } });
    expect(hit(d, 780, 10)).toBe(0);
  });
  it('fills the band through plot corners when its rays exit different edges', () => {
    const d = drawing('pitchfork', anchors.slice(0, 3), { style: { fill: true, levels: [{ ratio: 1 }] } });
    expect(hit(d, 780, 10)).toBe(0);
  });
  it('keeps the fan construction color independent of the level palette', () => {
    const d = drawing('fib-speed-resistance-fan');
    d.style.color = '#ff0000';
    const colors = paint(d).ops.filter(o => o.type === 'stroke').map(o => o.strokeStyle);
    expect(colors).toContain('#ff0000');
    expect(colors).toContain(levelColor(0.382));
  });
  it('extends a reversed pitchfork towards its target and clips rays to the pane', () => {
    const d = drawing('pitchfork', [{ time: 240, price: 10 }, { time: 60, price: 20 }, { time: 120, price: 14 }], { style: { fill: false, levels: [{ ratio: 0 }] } });
    expect(ends(paint(d))[0][0]).toBe(0);
    expect(hit(d, 700, 356)).toBeGreaterThan(6);
  });
  it('fits actual closes and labels perfect fit without using anchor prices', () => {
    const d = drawing('regression-channel', [{ time: 0, price: 2 }, { time: 180, price: 3 }], { style: { fill: false } });
    const r = paint(d, rc(1, barsOf([10, 12, 14, 16])));
    expect(moves(r)[0]).toEqual([100, 300]);
    expect(ends(r)[0]).toEqual([400, 240]);
    expect(texts(r).some(t => t.includes('R^2 1.000'))).toBe(true);
  });
  it('fits shared logical indices from a real sparse multi-series timeline', () => {
    const dataLayer = new DataLayer(), primary = dataLayer.createSeries(), secondary = dataLayer.createSeries();
    dataLayer.setSeriesData(primary, barsOf([10, 12, 14, 16]));
    dataLayer.setSeriesData(secondary, barsOf([1, 2]).map((b, i) => ({ ...b, time: 30 + i * 60 })));
    const context = { ...rc(), dataLayer, bars: () => dataLayer.seriesBars(primary) };
    const d = drawing('regression-channel', [anchors[0], anchors[3]], { style: { fill: false } });
    const r = paint(d, context);
    expect(moves(r)[0][1]).toBeCloseTo(400 - 5800 / 59);
    expect(ends(r)[0]).toEqual([600, expect.closeTo(400 - 9200 / 59)]);
    expect(texts(r)).toContain('R^2 0.980  4 bars');
    dataLayer.update(primary, { ...dataLayer.seriesBars(primary)[1], close: 20 });
    expect(paint(d, context).ops).not.toEqual(r.ops);
  });
  it('keeps binary-search mapping calls bounded when scanning actual stored bars', () => {
    class CountedDataLayer extends DataLayer {
      fractionalCalls = 0;
      override timeToIndexFloat(time: number): number {
        this.fractionalCalls++;
        return super.timeToIndexFloat(time);
      }
    }
    const dataLayer = new CountedDataLayer(), primary = dataLayer.createSeries();
    dataLayer.setSeriesData(primary, barsOf(Array.from({ length: 100 }, (_, i) => 10 + i / 10)));
    const context = { ...rc(), dataLayer, bars: () => dataLayer.seriesBars(primary) };
    const d = drawing('regression-channel', [{ time: 0, price: 10 }, { time: 5940, price: 20 }]);
    paint(d, context);
    expect(dataLayer.fractionalCalls).toBeLessThan(20);
  });
  it('refreshes regression for in-place historical and forming-bar corrections', () => {
    const bars = barsOf([10, 12, 14, 16]);
    const context = rc(1, bars);
    const d = drawing('regression-channel', [{ time: 0, price: 2 }, { time: 180, price: 3 }]);
    const first = paint(d, context).ops;
    bars[1] = { ...bars[1], close: 20 };
    expect(paint(d, context).ops).not.toEqual(first);
    const corrected = paint(d, context).ops;
    bars[3].close = 30;
    expect(paint(d, context).ops).not.toEqual(corrected);
  });
  it('uses population residual deviation and honors its multiplier', () => {
    const d = drawing('regression-channel', [{ time: 0, price: 2 }, { time: 180, price: 3 }], { style: { fill: false }, props: { deviation: 2 } });
    const r = paint(d, rc(1, barsOf([10, 14, 12, 16])));
    expect(moves(r)[0][1]).toBeCloseTo(294);
    expect(moves(r)[1][1]).toBeCloseTo(294 - 20 * Math.sqrt(1.8));
    expect(texts(r).some(t => t.includes('R^2 0.640'))).toBe(true);
  });
  it('handles missing regression data without inventing a fit', () => {
    const d = drawing('regression-channel');
    expect(paint(d).count('stroke')).toBe(0);
    expect(texts(paint(d))).toContain('No bars in range');
    expect(hit(d, 200, 200)).toBeNull();
  });
  it('restricts regression to its inclusive selected time range', () => {
    const d = drawing('regression-channel', [{ time: 60, price: 0 }, { time: 120, price: 0 }], { style: { fill: false } });
    const r = paint(d, rc(1, barsOf([1000, 12, 14, 1000])));
    expect(moves(r)[0]).toEqual([200, 280]);
    expect(ends(r)[0]).toEqual([300, 260]);
  });
  it('prints price, percentage and logical bar count for info line', () => {
    expect(texts(paint(drawing('info-line'))).join(' ')).toContain('+10.00 (+100.00%)  1 bars');
  });
  it('draws a baseline and arc with the signed screen angle', () => {
    const r = paint(drawing('trend-angle'));
    expect(texts(r)).toContain('45.0 deg');
    expect(moves(r)).toContainEqual([100, 300]);
    expect(ends(r).some(([x, y]) => y === 300 && x > 100)).toBe(true);
    expect(r.count('lineTo')).toBeGreaterThan(5);
    expect(r.count('lineTo')).toBeLessThan(110);
  });
  it('places two-point extension targets beyond the second price', () => {
    const d = drawing('fib-extension-two-point', anchors.slice(0, 2), { style: { levels: [{ ratio: 1.618 }, { ratio: 2 }] } });
    const r = paint(d);
    expect(texts(r).some(t => t.includes('26.18'))).toBe(true);
    expect(texts(r).some(t => t.includes('30.00'))).toBe(true);
    expect(hit(d, 150, 100)).toBe(0);
    d.style.levels![1].enabled = false;
    expect(hit(d, 150, 100)).toBeGreaterThan(6);
  });
  it('draws price and time fan rays with a single common diagonal', () => {
    const d = drawing('fib-speed-resistance-fan', anchors.slice(0, 2), { style: { levels: [{ ratio: 0.5 }, { ratio: 1 }] } });
    expect(paint(d).count('stroke')).toBe(4); // Three rays and the two-edge construction path.
    expect(hit(d, 300, 200)).toBeCloseTo(0);
    expect(hit(d, 200, 100)).toBeCloseTo(0);
    expect(hit(d, 200, 200)).toBeCloseTo(0);
    d.style.levels![0].enabled = false;
    expect(hit(d, 300, 200)).toBeGreaterThan(6);
    expect(hit(d, 200, 100)).toBeGreaterThan(6);
  });
  it('includes both zero rays and conventional colors in the default fan', () => {
    const d = drawing('fib-speed-resistance-fan');
    expect(d.style.levels!.map(l => l.ratio)).toContain(0);
    for (const level of d.style.levels!) expect(level.color).toBe(levelColor(level.ratio));
    expect(hit(d, 400, 300)).toBeCloseTo(0);
    expect(hit(d, 100, 100)).toBeCloseTo(0);
  });
  it('places compact fan ratios at anchor-box edges without overlap', () => {
    const d = drawing('fib-speed-resistance-fan', [{ time: 0, price: 8 }, { time: 84, price: 30 }]);
    for (const dpr of [1, 2]) {
      const labels = paint(d, rc(dpr)).ops.filter(o => o.type === 'fillText');
      expect(labels.length).toBeGreaterThanOrEqual(5);
      const boxes = labels.map(o => {
        expect(o.text).toMatch(/^[0-9.]+$/);
        const x = o.args[0] / dpr, y = o.args[1] / dpr;
        expect(Math.abs(x - 244) < 0.01 || Math.abs(y - 96) < 0.01).toBe(true);
        return { x, y: y - 11, width: o.text!.length * 11 * 0.6, height: 11 };
      });
      for (let i = 0; i < boxes.length; i++) for (let j = 0; j < i; j++) {
        const a = boxes[i], b = boxes[j];
        expect(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y).toBe(true);
      }
    }
  });
  it('skips fan labels when the anchor box cannot fit their text', () => {
    const d = drawing('fib-speed-resistance-fan', [{ time: 0, price: 10 }, { time: 0.6, price: 10.1 }]);
    expect(texts(paint(d))).toEqual([]);
    expect(paint(d).count('stroke')).toBeGreaterThan(1);
  });
  it('bounds crowded fan labels without discarding their rays', () => {
    const d = drawing('fib-speed-resistance-fan');
    d.style.levels = Array.from({ length: 100 }, (_, i) => ({ ratio: i / 99 }));
    const r = paint(d);
    expect(texts(r).length).toBeLessThanOrEqual(32);
    expect(r.count('stroke')).toBe(200); // 199 rays plus the construction path.
  });
  it('keeps fan user labels and colors and honors hidden labels', () => {
    const d = drawing('fib-speed-resistance-fan', [{ time: 0, price: 8 }, { time: 180, price: 30 }]);
    d.style.levels = [{ ratio: 0.5, color: '#aa5511', label: 'Half' }];
    const labels = paint(d).ops.filter(o => o.type === 'fillText');
    expect(labels.map(o => o.text)).toEqual(['Half', 'Half']);
    expect(labels.every(o => o.fillStyle === '#aa5511')).toBe(true);
    expect(paint(d).ops.filter(o => o.type === 'stroke' && o.strokeStyle === '#aa5511')).toHaveLength(2);
    d.style.showLabels = false;
    expect(texts(paint(d))).toEqual([]);
  });
  it('includes intermediate extension targets and exposes optional fill settings', () => {
    const d = drawing('fib-extension-two-point');
    expect(d.style.levels!.map(l => l.ratio)).toEqual(expect.arrayContaining([0.382, 0.618]));
    expect(tool(d.tool).settings!.fields.map(f => f.path)).toEqual(expect.arrayContaining(['style.fill', 'style.fillColor', 'style.fillOpacity']));
  });
  it('fills extension bands only between enabled targets with configured appearance', () => {
    const d = drawing('fib-extension-two-point', anchors.slice(0, 2), { style: {
      fill: true, fillColor: '#aabbcc', fillOpacity: 0.17, levels: [0, 0.382, 0.618, 1].map(ratio => ({ ratio })),
    } });
    const fills = paint(d).ops.filter(o => o.type === 'fill');
    expect(fills).toHaveLength(3);
    expect(fills.every(o => o.fillStyle === '#aabbcc' && o.args[0] === 0.17)).toBe(true);
    expect(hit(d, 180, 280)).toBe(0);
    d.style.levels![0].enabled = false;
    expect(hit(d, 180, 280)).toBeGreaterThan(6);
    d.style.fill = false;
    expect(paint(d).count('fill')).toBe(0);
    expect(hit(d, 180, 250)).toBeGreaterThan(6);
  });
  it.each([
    { extendRight: true }, { extendLeft: true }, { extendLeft: true, extendRight: true },
  ])('keeps equal-time extension fills zero-width for %j', extension => {
    for (const reversed of [false, true]) for (const dpr of [1, 2]) {
      const points = [{ time: 0, price: 10 }, { time: 0, price: 20 }];
      if (reversed) points.reverse();
      const d = drawing('fib-extension-two-point', points, { style: { fill: true, levels: [{ ratio: 0 }, { ratio: 1 }], ...extension } });
      const context = rc(dpr), r = paint(d, context);
      expect(r.count('fill')).toBe(0);
      expect(moves(r).every(p => p[0] === 100 * dpr)).toBe(true);
      expect(ends(r).every(p => p[0] === 100 * dpr)).toBe(true);
      expect(hit(d, 400, 250, context)).toBe(300);
      expect(hit(d, 50, 250, context)).toBe(50);
    }
  });
  it('retains extended fills for distinct-time extension anchors', () => {
    const d = drawing('fib-extension-two-point', anchors.slice(0, 2), { style: { fill: true, levels: [{ ratio: 0 }, { ratio: 1 }] } });
    expect(hit(d, 400, 250)).toBeGreaterThan(6);
    d.style.extendRight = true;
    expect(hit(d, 400, 250)).toBe(0);
    d.style.extendLeft = true;
    expect(hit(d, 50, 250)).toBe(0);
  });
  it.each([false, true])('labels visible negative fan rays in their actual direction, reversed=%s', reversed => {
    const points = [{ time: 120, price: 20 }, { time: 240, price: 30 }];
    if (reversed) points.reverse();
    const d = drawing('fib-speed-resistance-fan', points, { style: { showLabels: true, levels: [{ ratio: -0.5, label: 'Negative half', color: '#aa5511' }] } });
    for (const dpr of [1, 2]) {
      const context = rc(dpr), labels = paint(d, context).ops.filter(o => o.type === 'fillText');
      expect(labels.map(o => o.text)).toEqual(['Negative half', 'Negative half']);
      expect(labels.every(o => o.fillStyle === '#aa5511')).toBe(true);
      const [price, time] = labels.map(o => ({ x: o.args[0] / dpr, y: o.args[1] / dpr }));
      const width = 'Negative half'.length * 11 * 0.6;
      expect(price.x).toBeCloseTo(reversed ? 300 - width - 4 : 504);
      expect(reversed ? price.y < 100 : price.y > 200).toBe(true);
      expect(time.y).toBeCloseTo(reversed ? 200 + 11 * 1.2 + 4 : 96);
      expect(reversed ? time.x > 500 : time.x < 300).toBe(true);
      expect(paint(d, context).ops.filter(o => o.type === 'stroke' && o.strokeStyle === '#aa5511')).toHaveLength(2);
    }
    delete d.style.levels![0].label;
    expect(texts(paint(d))).toEqual(['-0.5', '-0.5']);
    d.style.showLabels = false;
    expect(texts(paint(d))).toEqual([]);
  });
  it('fits a negative fan label inside an edge that reaches the pane boundary', () => {
    const d = drawing('fib-speed-resistance-fan', [{ time: 240, price: 30 }, { time: 120, price: 20 }], { style: { levels: [{ ratio: -2, label: 'Negative', color: '#aa5511' }] } });
    for (const dpr of [1, 2]) {
      const labels = paint(d, rc(dpr)).ops.filter(o => o.type === 'fillText');
      expect(labels.map(o => o.text)).toEqual(['Negative', 'Negative']);
      expect(labels.every(o => o.args[1] / dpr >= 11 && o.args[1] / dpr <= 400)).toBe(true);
      expect(labels[0].args[1] / dpr).toBeCloseTo(11 * 1.2 + 4);
    }
  });
  it('retains all crowded negative fan rays while filtering colliding labels', () => {
    const d = drawing('fib-speed-resistance-fan', [{ time: 120, price: 20 }, { time: 240, price: 30 }]);
    d.style.levels = Array.from({ length: 100 }, (_, i) => ({ ratio: -(i + 1) / 100, label: `Level ${i}` }));
    const r = paint(d), labels = r.ops.filter(o => o.type === 'fillText');
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.length).toBeLessThanOrEqual(32);
    expect(r.count('stroke')).toBe(201);
    for (let i = 0; i < labels.length; i++) for (let j = 0; j < i; j++) {
      const a = labels[i], b = labels[j], wa = a.text!.length * 11 * 0.6, wb = b.text!.length * 11 * 0.6;
      expect(a.args[0] + wa <= b.args[0] || b.args[0] + wb <= a.args[0] || a.args[1] <= b.args[1] - 11 || b.args[1] <= a.args[1] - 11).toBe(true);
    }
  });
  it('keeps fan projection direction when anchors are reversed', () => {
    const d = drawing('fib-speed-resistance-fan', [anchors[1], anchors[0]], { style: { levels: [{ ratio: 0.5 }] } });
    expect(hit(d, 100, 250)).toBeCloseTo(0);
    expect(hit(d, 150, 300)).toBeCloseTo(0);
    expect(hit(d, 300, 150)).toBeGreaterThan(6);
  });
  it('offers and paints distinct vector stamp shapes with plain labels', () => {
    const options = tool('icon-stamp').settings!.fields.find(f => f.path === 'props.shape')!.options!;
    expect(options.length).toBeGreaterThanOrEqual(4);
    const streams = options.map(({ value, label }) => {
      expect(label).toMatch(/^[A-Za-z ]+$/);
      const r = paint(drawing('icon-stamp', [anchors[0]], { props: { shape: value } }));
      expect(r.count('fillText')).toBe(0);
      expect(r.count('stroke')).toBeGreaterThan(0);
      return JSON.stringify(r.ops);
    });
    expect(new Set(streams).size).toBe(options.length);
  });
  it('scales stamp size and excludes empty corners from hit tests', () => {
    const d = drawing('icon-stamp', [anchors[0]], { props: { shape: 'diamond', size: 40 }, style: { fill: true } });
    expect(hit(d, 100, 300)).toBe(0);
    expect(hit(d, 118, 318)).toBeGreaterThan(6);
    d.props!.size = 80;
    expect(hit(d, 118, 318)).toBe(0);
  });
  it.each(ADVANCED_LINE_TOOLS.map(t => t.id))('keeps %s finite for coincident anchors and DPR 2', id => {
    const d = drawing(id, Array.from({ length: tool(id).points }, () => anchors[0]));
    const r = paint(d, rc(2, barsOf([10])));
    expect(r.ops.flatMap(o => o.args).every(Number.isFinite)).toBe(true);
    expect(r.ops.length).toBeLessThan(1000);
  });
  it.each(ADVANCED_LINE_TOOLS.flatMap(t => t.settings!.fields.map(f => [t.id, f.path] as const)))('%s consumes %s in its painted output', (id, path) => {
    const d = drawing(id);
    if (id === 'regression-channel') d.points = [anchors[0], anchors[3]];
    const context = rc(1, barsOf([10, 14, 12, 16]));
    const before = paint(d, context).ops;
    const values: Record<string, unknown> = {
      'style.color': '#ff0099', 'style.lineWidth': 7, 'style.lineStyle': 'dashed',
      'style.fill': false, 'style.fillColor': '#aaff00', 'style.fillOpacity': 0.6,
      'style.extendLeft': true, 'style.extendRight': true, 'style.showLabels': false,
      'style.levels': [{ ratio: 0.25, color: '#aa1122', label: 'Quarter' }],
      'text.color': '#ffff00', 'text.fontSize': 24, 'text.fontFamily': 'monospace',
      'text.bold': true, 'text.italic': true, 'props.deviation': 4,
      'props.shape': 'diamond', 'props.size': 80,
    };
    expect(values[path]).toBeDefined();
    const [root, key] = path.split('.');
    if (root === 'style') d.style = { ...d.style, [key]: values[path] };
    if (root === 'text') d.text = { value: '', [key]: values[path] };
    if (root === 'props') d.props = { [key]: values[path] };
    expect(paint(d, context).ops).not.toEqual(before);
  });
  it('honors level-specific colors and labels for every level family', () => {
    for (const id of ['pitchfork', 'schiff-pitchfork', 'modified-schiff-pitchfork', 'inside-pitchfork', 'fib-extension-two-point', 'fib-speed-resistance-fan']) {
      const d = drawing(id);
      d.style.levels = [{ ratio: 0.618, color: '#aa5511', label: 'Target' }];
      const r = paint(d);
      expect(r.ops.some(o => o.type === 'stroke' && o.strokeStyle === '#aa5511')).toBe(true);
      expect(texts(r).some(t => t.startsWith('Target'))).toBe(true);
    }
  });
  it('computes the trend-angle hit shape from the same bounded arc samples', () => {
    const d = drawing('trend-angle');
    const arcPoint = { x: 100 + 40 * Math.cos(-Math.PI / 8), y: 300 + 40 * Math.sin(-Math.PI / 8) };
    expect(hit(d, arcPoint.x, arcPoint.y)).toBeLessThan(0.1);
    expect(hit(d, 100 - 40, 300)).toBeGreaterThan(6);
  });
  it('treats a zero-price info-line percentage as unavailable', () => {
    const d = drawing('info-line', [{ time: 0, price: 0 }, anchors[1]]);
    expect(texts(paint(d)).join(' ')).toContain('(n/a)');
  });
  it('returns finite geometry and no false hits for unmappable anchors', () => {
    for (const descriptor of ADVANCED_LINE_TOOLS) {
      const d = drawing(descriptor.id, Array.from({ length: descriptor.points }, () => ({ time: NaN, price: NaN })));
      expect(paint(d).ops.flatMap(o => o.args).every(Number.isFinite)).toBe(true);
      expect(hit(d, 20, 20)).toBeNull();
    }
  });
  it('keeps reversed regression selection identical and reflects replacement data', () => {
    const d = drawing('regression-channel', [anchors[0], anchors[3]]);
    const context = rc(1, barsOf([10, 12, 14, 16]));
    const original = paint(d, context).ops;
    d.points.reverse();
    expect(paint(d, context).ops).toEqual(original);
    context.bars = () => barsOf([20, 22, 24, 26]);
    expect(paint(d, context).ops).not.toEqual(original);
  });
  it('converts the same geometry once at the DPR boundary', () => {
    const d = drawing('disjoint-channel', anchors, { style: { fill: false } });
    expect(moves(paint(d, rc(2)))).toEqual(moves(paint(d)).map(p => p.map(n => n * 2)));
    expect(hit(d, 350, 250, rc(2))).toBe(0);
  });
});

describe('advanced shared geometry', () => {
  it('bounds arc samples independently of radius and resolution', () => {
    expect(sampleArc({ x: 0, y: 0 }, 1e9, 1e9, 0, Math.PI * 2)).toHaveLength(97);
    expect(sampleArc({ x: 0, y: 0 }, 0, 0, 0, 0)).toHaveLength(3);
  });
  it('clips vertical rays and rejects rays that point away from the pane', () => {
    expect(clippedLine({ x: 100, y: 100 }, { x: 100, y: 200 }, rc(), 0, Infinity)).toEqual([{ x: 100, y: 100 }, { x: 100, y: 400 }]);
    expect(clippedLine({ x: -100, y: 100 }, { x: -200, y: 100 }, rc(), 0, Infinity)).toEqual([]);
  });
  it('clips polygon fills to each plot edge and preserves interior membership', () => {
    const polygon = clipPolygon([{ x: -50, y: -50 }, { x: 900, y: -50 }, { x: 900, y: 450 }, { x: -50, y: 450 }], rc());
    expect(polygon).toHaveLength(4);
    expect(insidePolygon(799, 399, polygon)).toBe(true);
    expect(insidePolygon(801, 399, polygon)).toBe(false);
  });
});
