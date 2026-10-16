import { describe, expect, it } from 'vitest';
import { ADVANCED_GEOMETRY_TOOLS } from '../src/draw/advanced-geometry';
import { geometryDistance, geometryTool, type DrawingGeometry } from '../src/draw/advanced-shared';
import { DataLayer } from '../src/model/data-layer';
import { RecordingContext } from './helpers/fake-ctx';
import type { Drawing, DrawingPoint, DrawingTool } from '../src/draw/types';
import type { PrimitiveRenderContext } from '../src';

const ids = ['trend-fib-time', 'fib-circles', 'fib-speed-resistance-arcs', 'fib-wedge', 'fib-spiral',
  'gann-square', 'dedekind-tessellation', 'sonic', 'supersonic', 'golden-sonic', 'golden-supersonic'];
const rc = (dpr = 1): PrimitiveRenderContext => ({
  plotWidth: 800, plotHeight: 600, dpr, priceAxisWidth: 60,
  priceScale: { priceToY: (p: number) => 600 - p, format: String },
  timeScale: { indexToX: (i: number) => i }, dataLayer: { timeToIndexFloat: (t: number) => t },
} as unknown as PrimitiveRenderContext);
const at = (x: number, y: number): DrawingPoint => ({ time: x, price: 600 - y });
const anchors = [at(200, 300), at(300, 300), at(200, 200)];
function tool(id: string): DrawingTool { return ADVANCED_GEOMETRY_TOOLS.find(t => t.id === id)!; }
function drawing(id: string, points = anchors.slice(0, tool(id).points), patch: Partial<Drawing> = {}): Drawing {
  return { id: 'geometry', tool: id, points, style: { ...tool(id).defaultStyle }, paneIndex: 0, zIndex: 0, ...patch };
}
function project(d: Drawing, context = rc()) {
  return d.points.map(p => ({ x: context.timeScale.indexToX(context.dataLayer.timeToIndexFloat(p.time)), y: context.priceScale.priceToY(p.price) }));
}
class CurvesContext extends RecordingContext {
  globalAlpha = 1;
  private alphas: number[] = [];
  override save(): void { this.alphas.push(this.globalAlpha); super.save(); }
  override restore(): void { this.globalAlpha = this.alphas.pop() ?? 1; super.restore(); }
  override fill(): void { super.fill(); this.ops[this.ops.length - 1].args.push(this.globalAlpha); }
  override arc(x: number, y: number, r: number, start = 0, end = Math.PI * 2, ccw = false): void {
    this.ops.push({ type: 'arc', args: [x, y, r, start, end, Number(ccw)] });
  }
  override ellipse(x: number, y: number, rx: number, ry: number, rotation = 0, start = 0, end = Math.PI * 2, ccw = false): void {
    this.ops.push({ type: 'ellipse', args: [x, y, rx, ry, rotation, start, end, Number(ccw)] });
  }
}
function paint(d: Drawing, context = rc()) {
  const rec = new CurvesContext();
  tool(d.tool).draw({ ctx: rec as unknown as CanvasRenderingContext2D, rc: context,
    pts: project(d, context).map(p => ({ x: p.x * context.dpr, y: p.y * context.dpr })),
    drawing: d, style: { color: '#123456', lineWidth: 1.5, ...d.style }, selected: false, formatPrice: String });
  return rec;
}
function hit(d: Drawing, x: number, y: number, context = rc()) {
  return tool(d.tool).distance(x, y, { drawing: d, pts: project(d, context), rc: context });
}
const moves = (r: RecordingContext) => r.ops.filter(o => o.type === 'moveTo').map(o => o.args);
const ends = (r: RecordingContext) => r.ops.filter(o => o.type === 'lineTo').map(o => o.args);
const texts = (r: RecordingContext) => r.ops.filter(o => o.type === 'fillText').map(o => o.text!);
const curves = (r: RecordingContext) => r.ops.filter(o => o.type === 'ellipse' || o.type === 'arc').map(o => o.type === 'arc'
  ? [o.args[0], o.args[1], o.args[2], o.args[2], 0, ...o.args.slice(3)] : o.args);

describe('advanced geometry tools', () => {
  it('supplies all eleven independently placeable descriptors', () => {
    expect(ADVANCED_GEOMETRY_TOOLS.map(t => t.id)).toEqual(ids);
    for (const id of ids) expect(tool(id).points).toBe(['trend-fib-time', 'fib-wedge'].includes(id) ? 3 : 2);
  });
  it('projects trend time levels from the third anchor using logical indices over a session gap', () => {
    const dataLayer = new DataLayer(), series = dataLayer.createSeries();
    dataLayer.setSeriesData(series, [0, 60, 86400, 86460].map(time => ({ time, open: 1, high: 1, low: 1, close: 1, volume: 1 })));
    const context = { ...rc(), dataLayer, timeScale: { indexToX: (i: number) => 100 + 50 * i } } as unknown as PrimitiveRenderContext;
    const d = drawing('trend-fib-time', [{ time: 0, price: 100 }, { time: 60, price: 200 }, { time: 86400, price: 150 }],
      { style: { levels: [{ ratio: 1 }, { ratio: 2 }] } });
    expect(moves(paint(d, context))).toContainEqual([250, 0]);
    expect(moves(paint(d, context))).toContainEqual([300, 0]);
    expect(hit(d, 300, 500, context)).toBe(0);
    d.points = [d.points[1], d.points[0], d.points[2]];
    expect(moves(paint(d, context))).toContainEqual([100, 0]);
  });
  it('uses the center-to-edge screen distance for circular radii', () => {
    const d = drawing('fib-circles', [at(200, 300), at(260, 220)], { style: { levels: [{ ratio: 0.5 }, { ratio: 1 }] } });
    expect(curves(paint(d)).map(a => a.slice(0, 4))).toEqual([[200, 300, 50, 50], [200, 300, 100, 100]]);
    expect(hit(d, 200, 400)).toBeCloseTo(0);
    expect(hit(d, 200, 300)).toBeGreaterThan(40);
  });
  it('orients a resistance semicircle toward the second anchor with a baseline', () => {
    const d = drawing('fib-speed-resistance-arcs', undefined, { style: { levels: [{ ratio: 1 }] } });
    const arc = curves(paint(d))[0];
    expect(arc.slice(0, 4)).toEqual([200, 300, 100, 100]);
    expect(arc[6] - arc[5]).toBeCloseTo(Math.PI);
    expect(hit(d, 300, 300)).toBeCloseTo(0);
    expect(hit(d, 100, 300)).toBeGreaterThan(50);
    expect(hit(d, 250, 300)).toBeCloseTo(0);
  });
  it('uses only the third wedge angle and rescales its ray to the second-anchor radius', () => {
    const d = drawing('fib-wedge', [at(200, 300), at(300, 300), at(200, 100)], { style: { levels: [{ ratio: 1 }] } });
    expect(ends(paint(d))).toContainEqual([200, 200]);
    expect(hit(d, 200, 200)).toBeCloseTo(0);
    expect(hit(d, 200, 100)).toBeGreaterThan(90);
    expect(hit(d, 200 + Math.SQRT1_2 * 100, 300 - Math.SQRT1_2 * 100)).toBeLessThan(0.2);
    expect(hit(d, 200 - Math.SQRT1_2 * 100, 300 - Math.SQRT1_2 * 100)).toBeGreaterThan(50);
  });
  it('takes the minor wedge sweep across the negative-x angle branch', () => {
    const d = drawing('fib-wedge', [at(400, 300), at(300, 310), at(300, 290)], { style: { levels: [{ ratio: 1 }] } });
    const arc = curves(paint(d))[0];
    expect(Math.abs(arc[6] - arc[5])).toBeCloseTo(2 * Math.atan(0.1));
    expect(hit(d, 400 - Math.hypot(100, 10), 300)).toBeLessThan(0.2);
    expect(hit(d, 500, 300)).toBeGreaterThan(90);
  });
  it('does not treat a zero-angle wedge as a complete selectable circle', () => {
    const d = drawing('fib-wedge', [at(200, 300), at(300, 300), at(400, 300)], { style: { levels: [{ ratio: 1 }], fill: true } });
    expect(hit(d, 200, 400)).toBeGreaterThan(90);
    expect(hit(d, 250, 300)).toBe(0);
  });
  it('passes the spiral through its edge and grows by the golden ratio each quarter turn', () => {
    const d = drawing('fib-spiral');
    const vertices = [...moves(paint(d)), ...ends(paint(d))];
    expect(vertices.some(([x, y]) => Math.abs(x - 300) < 1e-8 && Math.abs(y - 300) < 1e-8)).toBe(true);
    expect(vertices.some(([x, y]) => Math.abs(x - 200) < 1e-8 && Math.abs(y - 461.8033988749895) < 1e-8)).toBe(true);
    expect(hit(d, 300, 300)).toBeLessThan(1e-8);
    expect(paint(d).count('lineTo')).toBeLessThan(1100);
  });
  it('builds the Gann price grid in price space and time grid in logical space', () => {
    const context = { ...rc(), priceScale: { priceToY: (p: number) => 600 - Math.log2(p) * 100 } } as unknown as PrimitiveRenderContext;
    const d = drawing('gann-square', [{ time: 100, price: 2 }, { time: 500, price: 8 }], { style: { levels: [{ ratio: 0.5 }] } });
    expect(moves(paint(d, context))).toContainEqual([100, 600 - Math.log2(5) * 100]);
    expect(moves(paint(d, context))).toContainEqual([300, 300]);
    expect(curves(paint(d, context)).some(a => a[2] === 400 && a[3] === 200)).toBe(true);
  });
  it('adds five Gann fan diagonals and four quarter-ellipse arcs', () => {
    const d = drawing('gann-square', [at(200, 400), at(500, 100)], { style: { levels: [] } });
    const r = paint(d);
    for (const end of [[500, 300], [500, 250], [500, 100], [350, 100], [300, 100]]) expect(ends(r)).toContainEqual(end);
    expect(curves(r)).toHaveLength(4);
    expect(hit(d, 350, 250)).toBeCloseTo(0);
  });
  it('uses Dedekind curvatures rather than equally spaced nested circles', () => {
    const d = drawing('dedekind-tessellation', [at(100, 100), at(500, 300)], { props: { maxCurvature: 8 } });
    const arcs = curves(paint(d));
    expect(arcs.some(a => a[0] === 300 && a[1] === 300 && a[2] === 200)).toBe(true);
    expect(arcs.some(a => Math.abs(a[0] - 100 - 200 / 3) < 1e-8 && Math.abs(a[2] - 200 / 3) < 1e-8)).toBe(true);
    expect(arcs.some(a => a[2] === 100 || a[2] === 50)).toBe(false);
    expect(arcs.some(a => a[0] === 175 && a[2] === 25)).toBe(true);
    expect(moves(paint(d))).toContainEqual([200, 300]);
    expect(hit(d, 200, 170)).toBeCloseTo(0);
    expect(hit(d, 50, 300)).toBeGreaterThan(40);
  });
  it.each(['sonic', 'supersonic', 'golden-sonic', 'golden-supersonic'])('%s uses diameter anchors for its first circle', id => {
    const d = drawing(id, undefined, { style: { levels: [{ ratio: 1 }, { ratio: 2 }] } });
    const arcs = curves(paint(d));
    expect(arcs[0].slice(0, 4)).toEqual([250, 300, 50, 50]);
    expect(arcs[1].slice(0, 4)).toEqual([id.includes('supersonic') ? 350 : 300, 300, 100, 100]);
    expect(hit(d, 250, 250)).toBeLessThan(0.1);
  });
  it('constructs the supersonic cone at asin(1/M), tangent to its waves', () => {
    const d = drawing('supersonic', undefined, { style: { levels: [{ ratio: 1 }] }, props: { mach: 2 } });
    expect(moves(paint(d)).filter(p => p[0] === 150 && p[1] === 300)).toHaveLength(2);
    expect(hit(d, 225, 300 + 25 * Math.sqrt(3))).toBeLessThan(0.15);
    expect(hit(d, 225, 300 - 25 * Math.sqrt(3))).toBeLessThan(0.15);
    expect(hit(d, 150, 400)).toBeGreaterThan(50);
  });
  it('uses Fibonacci radius spacing for golden wavefronts', () => {
    const ordinary = curves(paint(drawing('sonic'))).map(a => a[2]);
    const golden = curves(paint(drawing('golden-sonic'))).map(a => a[2]);
    expect(ordinary).toEqual([50, 100, 150, 200, 250, 300]);
    expect(golden).toContain(80.9);
    expect(golden).toContain(130.9);
    expect(golden).toContainEqual(expect.closeTo(11.8));
    expect(golden).not.toEqual(ordinary);
  });
  it.each(['fib-circles', 'fib-speed-resistance-arcs', 'fib-wedge', 'gann-square'])('%s keeps fill color independent and fill hits optional', id => {
    const points = id === 'gann-square' ? [at(200, 400), at(500, 100)] : undefined;
    const d = drawing(id, points, { style: { fill: true, fillColor: '#fedcba', color: '#123456', levels: [{ ratio: 1 }] } });
    expect(paint(d).ops.some(o => o.type === 'fill' && o.fillStyle === '#fedcba')).toBe(true);
    expect(paint(d).ops.filter(o => o.type === 'stroke').every(o => o.strokeStyle !== '#fedcba')).toBe(true);
    const position = id === 'gann-square' ? [270, 340] : [230, 280];
    expect(hit(d, position[0], position[1])).toBe(0);
    d.style.fill = false;
    expect(hit(d, position[0], position[1])).toBeGreaterThan(1);
    d.style.fill = true; d.style.fillOpacity = 0;
    expect(hit(d, position[0], position[1])).toBeGreaterThan(1);
  });
  it.each(ids)('%s produces finite bounded geometry for coincident, reversed and invalid anchors at either DPR', id => {
    const count = ['trend-fib-time', 'fib-wedge'].includes(id) ? 3 : 2;
    for (const points of [Array.from({ length: count }, () => at(300, 300)), anchors.slice(0, count).reverse(),
      Array.from({ length: count }, () => at(NaN, Infinity)), [at(-1e12, 1e12), at(1e12, -1e12), at(400, 300)].slice(0, count)]) {
      const d = drawing(id, points);
      for (const dpr of [1, 2]) {
        const r = paint(d, rc(dpr));
        expect(r.ops.flatMap(o => o.args).every(Number.isFinite)).toBe(true);
        expect(r.ops.length).toBeLessThan(15000);
        expect(hit(d, -1, 300, rc(dpr))).toBeNull();
      }
    }
  });
  it.each(['trend-fib-time', 'fib-wedge'])('%s shows the measured first leg while placing its third anchor', id => {
    const d = drawing(id, anchors.slice(0, 2));
    expect(paint(d).count('stroke')).toBeGreaterThan(0);
    expect(moves(paint(d))).toContainEqual([200, 300]);
    expect(ends(paint(d))).toContainEqual([300, 300]);
  });
});


describe('geometry settings and selection', () => {
  it.each(ADVANCED_GEOMETRY_TOOLS.flatMap(t => t.settings!.fields.map(f => [t.id, f.path] as const)))('%s consumes %s', (id, path) => {
    const d = drawing(id, id === 'gann-square' || id === 'dedekind-tessellation' ? [at(100, 100), at(500, 400)] : undefined);
    if (['fib-circles', 'fib-speed-resistance-arcs', 'fib-wedge', 'gann-square'].includes(id)) d.style.fill = true;
    const before = paint(d).ops;
    const values: Record<string, unknown> = {
      'style.color': '#ff0099', 'style.lineWidth': 7, 'style.lineStyle': 'dashed',
      'style.fill': false, 'style.fillColor': '#aaff00', 'style.fillOpacity': 0.6,
      'style.showLabels': false, 'style.levels': [{ ratio: 0.45, color: '#aa1122', label: 'Custom' }],
      'text.color': '#ffff00', 'text.fontSize': 24, 'text.fontFamily': 'monospace',
      'text.bold': true, 'text.italic': true, 'props.maxCurvature': 4, 'props.waveCount': 3, 'props.mach': 4,
    };
    expect(values[path]).toBeDefined();
    const [root, key] = path.split('.');
    if (root === 'style') d.style = { ...d.style, [key]: values[path] };
    if (root === 'text') d.text = { value: '', [key]: values[path] };
    if (root === 'props') d.props = { [key]: values[path] };
    expect(paint(d).ops).not.toEqual(before);
  });
  it.each(ids.filter(id => !['fib-spiral', 'dedekind-tessellation'].includes(id)))('%s paints enabled level colors and custom labels', id => {
    const d = drawing(id, id === 'gann-square' ? [at(100, 100), at(500, 400)] : undefined,
      { style: { levels: [{ ratio: 0.45, color: '#aa1122', label: 'Target' }, { ratio: 0.8, enabled: false, color: '#bb2233', label: 'Hidden' }] } });
    const r = paint(d);
    expect(r.ops.some(o => o.type === 'stroke' && o.strokeStyle === '#aa1122')).toBe(true);
    expect(r.ops.some(o => o.type === 'stroke' && o.strokeStyle === '#bb2233')).toBe(false);
    expect(texts(r)).toContain('Target');
    expect(texts(r)).not.toContain('Hidden');
    d.style.showLabels = false;
    expect(texts(paint(d))).toHaveLength(0);
  });
  it.each(['fib-circles', 'fib-speed-resistance-arcs', 'fib-wedge', 'sonic', 'supersonic', 'golden-sonic', 'golden-supersonic'])('%s excludes disabled and invalid radial levels from body hits', id => {
    const d = drawing(id, undefined, { style: { levels: [{ ratio: 1, enabled: false }, { ratio: -2 }, { ratio: NaN }, { ratio: Infinity }] } });
    const point = id === 'fib-circles' || id === 'fib-speed-resistance-arcs' ? [200, 400]
      : id === 'fib-wedge' ? [270.71067811865476, 229.28932188134524] : [250, 250];
    expect(curves(paint(d))).toHaveLength(0);
    const distance = hit(d, point[0], point[1]);
    expect(distance === null || distance > 6).toBe(true);
    d.style.levels = [{ ratio: 1 }];
    expect(hit(d, point[0], point[1])).toBeLessThan(0.2);
  });
  it('hides a Gann grid level without leaving its old hit region', () => {
    const d = drawing('gann-square', [at(100, 100), at(500, 500)], { style: { levels: [{ ratio: 0.45 }] } });
    expect(hit(d, 280, 430)).toBeCloseTo(0);
    d.style.levels![0].enabled = false;
    expect(hit(d, 280, 430)).toBeGreaterThan(6);
  });
  it('hides projected time levels from both paint and hit', () => {
    const d = drawing('trend-fib-time', undefined, { style: { levels: [{ ratio: 1, enabled: false }] } });
    expect(hit(d, 300, 500)).toBeNull();
    expect(paint(d).count('stroke')).toBe(0);
  });
  it.each(['sonic', 'supersonic'])('%s wave-count setting adds and removes actual circles and their hit geometry', id => {
    const d = drawing(id, undefined, { props: { waveCount: 1 } });
    expect(curves(paint(d))).toHaveLength(1);
    const x = id === 'sonic' ? 300 : 350;
    expect(hit(d, x, 200)).toBeGreaterThan(1);
    d.props!.waveCount = 2;
    expect(curves(paint(d))).toHaveLength(2);
    expect(hit(d, x, 200)).toBeLessThan(0.1);
  });
  it.each(['sonic', 'supersonic'])('%s exposes all default waves as the limit increases from six through twelve', id => {
    const d = drawing(id);
    expect(curves(paint(d))).toHaveLength(6);
    for (let waveCount = 7; waveCount <= 12; waveCount++) {
      d.props = { waveCount };
      expect(curves(paint(d))).toHaveLength(waveCount);
      expect(texts(paint(d))).toContain(String(waveCount));
    }
  });
  it('makes an edited Mach number move both wavefronts and the tangent envelope', () => {
    const d = drawing('supersonic', undefined, { style: { levels: [{ ratio: 2 }] }, props: { mach: 2 } });
    expect(hit(d, 350, 200)).toBeLessThan(0.1);
    d.props!.mach = 3;
    expect(curves(paint(d))[0].slice(0, 4)).toEqual([400, 300, 100, 100]);
    expect(hit(d, 350, 200)).toBeGreaterThan(6);
    expect(hit(d, 400, 200)).toBeLessThan(0.1);
  });
  it('reverses wavefront expansion when the diameter anchors are swapped', () => {
    const d = drawing('supersonic', [...anchors.slice(0, 2)].reverse(), { style: { levels: [{ ratio: 2 }] } });
    expect(curves(paint(d))[0].slice(0, 4)).toEqual([150, 300, 100, 100]);
    expect(hit(d, 150, 200)).toBeLessThan(0.1);
  });
  it.each(ids)('%s converts media coordinates once at the DPR boundary', id => {
    const d = drawing(id, id === 'gann-square' || id === 'dedekind-tessellation' ? [at(100, 100), at(500, 400)] : undefined);
    const normal = paint(d), double = paint(d, rc(2));
    expect(moves(double)).toEqual(moves(normal).map(p => p.map(v => v * 2)));
    expect(ends(double)).toEqual(ends(normal).map(p => p.map(v => v * 2)));
    expect(curves(double)).toEqual(curves(normal).map(p => [...p.slice(0, 4).map(v => v * 2), ...p.slice(4)]));
    expect(hit(d, 250, 250, rc(2))).toEqual(hit(d, 250, 250));
  });
  it('bounds native-curve paint work for a maximally dense, extremely wide Dedekind domain', () => {
    const d = drawing('dedekind-tessellation', [at(-1e9, 299), at(1e9, 300)], { props: { maxCurvature: 64 } });
    const r = paint(d);
    expect(curves(r).length).toBeGreaterThan(100);
    expect(curves(r).length).toBeLessThan(4100);
    expect(r.count('lineTo')).toBeLessThan(1000);
    expect(r.ops.length).toBeLessThan(15000);
  });
  it('clips Dedekind geodesics to its box and culls a completely offscreen domain', () => {
    const d = drawing('dedekind-tessellation', [at(100, 100), at(500, 300)], { props: { maxCurvature: 8 } });
    for (const arc of curves(paint(d))) {
      for (const t of [arc[5], (arc[5] + arc[6]) / 2, arc[6]]) {
        expect(arc[0] + arc[2] * Math.cos(t)).toBeGreaterThanOrEqual(100 - 1e-8);
        expect(arc[0] + arc[2] * Math.cos(t)).toBeLessThanOrEqual(500 + 1e-8);
        expect(arc[1] + arc[3] * Math.sin(t)).toBeGreaterThanOrEqual(100 - 1e-8);
        expect(arc[1] + arc[3] * Math.sin(t)).toBeLessThanOrEqual(300 + 1e-8);
      }
    }
    d.points = [at(-1000, -1000), at(-500, -500)];
    expect(paint(d).count('stroke')).toBe(0);
    expect(hit(d, 1, 1)).toBeNull();
  });
});

describe('shared native ellipse paths', () => {
  const arcGeometry = (rx: number, ry: number, start: number, sweep: number, closed = false, sector = false): DrawingGeometry => ({
    paths: [{ points: [], arc: { center: { x: 200, y: 300 }, rx, ry, start, sweep, sector }, closed }],
  });
  it.each([false, true])('rejects DPR-overflowing circle paint, labels and hits together with fill %s', fill => {
    const d = drawing('fib-circles', undefined, { style: { levels: [{ ratio: 1e306 }], fill } });
    const single = paint(d, rc(1));
    expect(curves(single)).toHaveLength(fill ? 2 : 1);
    expect(single.count('fill')).toBe(fill ? 1 : 0);
    expect(single.count('fillText')).toBe(1);
    expect(single.ops.flatMap(o => o.args).every(Number.isFinite)).toBe(true);
    expect(hit(d, 400, 300, rc(1))).toBe(fill ? 0 : 1e308);

    const double = paint(d, rc(2));
    expect({
      curves: curves(double).length, fills: double.count('fill'), labels: double.count('fillText'),
      finite: double.ops.flatMap(o => o.args).every(Number.isFinite), distance: hit(d, 400, 300, rc(2)),
    }).toEqual({ curves: 0, fills: 0, labels: 0, finite: true, distance: null });

    d.style.levels = [{ ratio: 1 }];
    const ordinary = paint(d, rc(2));
    expect(curves(ordinary)).toHaveLength(fill ? 2 : 1);
    expect(ordinary.count('fillText')).toBe(1);
    expect(hit(d, 300, 300, rc(2))).toBe(0);
  });
  it('applies render-context DPR validity to point paths while preserving media-only distance callers', () => {
    const d = drawing('fib-circles', undefined, { style: { fill: true } });
    const g: DrawingGeometry = { paths: [{
      points: [{ x: 100, y: 100 }, { x: 1e308, y: 100 }, { x: 1e308, y: 400 }, { x: 100, y: 400 }],
      fill: true, closed: true,
    }] };
    const descriptor = geometryTool({ id: 'probe', name: 'Probe', points: 2 }, () => g);
    expect(geometryDistance(200, 200, g, d)).toBe(0);
    for (const dpr of [1, 2]) {
      const rec = new CurvesContext(), context = rc(dpr);
      descriptor.draw({ ctx: rec as unknown as CanvasRenderingContext2D, rc: context, pts: [], drawing: d,
        style: { color: '#123456', lineWidth: 1, fill: true }, selected: false, formatPrice: String });
      expect(rec.count('fill')).toBe(dpr === 1 ? 1 : 0);
      expect(rec.ops.flatMap(o => o.args).every(Number.isFinite)).toBe(true);
      expect(descriptor.distance(200, 200, { rc: context, pts: [], drawing: d })).toBe(dpr === 1 ? 0 : null);
    }
  });
  it('measures native ellipse points without flattening the painted curve', () => {
    const d = drawing('fib-circles');
    const g = arcGeometry(200, 50, 0, Math.PI / 2);
    expect(geometryDistance(200 + 200 * Math.SQRT1_2, 300 + 50 * Math.SQRT1_2, g, d)).toBeLessThan(1e-5);
    expect(geometryDistance(200, 250, g, d)).toBeCloseTo(100);
  });
  it('refines the last ellipse interval when its endpoint beats all coarse interior samples', () => {
    const d = drawing('fib-circles'), angle = Math.PI / 2 - 0.00001;
    const g = arcGeometry(200, 50, 0, Math.PI / 2);
    expect(geometryDistance(200 + 200 * Math.cos(angle), 300 + 50 * Math.sin(angle), g, d)).toBeLessThan(1e-5);
  });
  it('retains subpixel native ellipse selection at extreme zoom with bounded refinement', () => {
    const d = drawing('fib-circles'), angle = 0.713;
    const g = arcGeometry(1e12, 7e11, 0, Math.PI / 2);
    g.paths[0].arc!.center = { x: 400 - 1e12 * Math.cos(angle), y: 300 - 7e11 * Math.sin(angle) };
    expect(geometryDistance(400, 300, g, d)).toBeLessThan(0.5);
  });
  it('includes a closed arc chord and sector edges in stroked hit geometry', () => {
    const d = drawing('fib-circles');
    expect(geometryDistance(250, 350, arcGeometry(100, 100, 0, Math.PI / 2, true), d)).toBeLessThan(1e-8);
    expect(geometryDistance(250, 300, arcGeometry(100, 100, 0, Math.PI / 2, true, true), d)).toBeLessThan(1e-8);
    expect(geometryDistance(200, 350, arcGeometry(100, 100, 0, Math.PI / 2, true, true), d)).toBeLessThan(1e-8);
  });
  it('matches filled segment and sector interiors without adding hidden edges', () => {
    const d = drawing('fib-circles', undefined, { style: { fill: true } });
    const segment = arcGeometry(100, 100, 0, Math.PI / 2);
    segment.paths[0].fill = true; segment.paths[0].stroke = false;
    expect(geometryDistance(260, 360, segment, d)).toBe(0);
    expect(geometryDistance(210, 310, segment, d)).toBeNull();
    segment.paths[0].arc!.sector = true;
    expect(geometryDistance(210, 310, segment, d)).toBe(0);
    expect(geometryDistance(190, 310, segment, d)).toBeNull();
  });
  it('does not feed nonfinite or invalid native curve coordinates to canvas', () => {
    const d = drawing('fib-circles');
    for (const values of [[Infinity, 20], [-10, 20], [0, 20], [Number.MAX_VALUE, 20]]) {
      const g = arcGeometry(values[0], values[1], 0, Math.PI);
      const descriptor = geometryTool({ id: 'probe', name: 'Probe', points: 2 }, () => g);
      const rec = new CurvesContext();
      descriptor.draw({ ctx: rec as unknown as CanvasRenderingContext2D, rc: rc(2), pts: [], drawing: d,
        style: { color: '#123456', lineWidth: 1 }, selected: false, formatPrice: String });
      expect(rec.ops.flatMap(o => o.args).every(Number.isFinite)).toBe(true);
      expect(curves(rec)).toHaveLength(0);
    }
  });
});
