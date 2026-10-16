import { describe, expect, it } from 'vitest';
import { PATTERN_DRAWING_TOOLS } from '../src/draw/pattern-tools';
import { RecordingContext } from './helpers/fake-ctx';
import type { Drawing, DrawingPoint, DrawingTool } from '../src/draw/types';
import type { PrimitiveRenderContext } from '../src';

const IDS = ['xabcd-pattern', 'abcd-pattern', 'elliott-impulse', 'elliott-correction', 'head-shoulders',
  'gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher'];
const POINTS: Record<string, number> = {
  'xabcd-pattern': 5, 'abcd-pattern': 4, 'elliott-impulse': 5, 'elliott-correction': 3,
  'head-shoulders': 7, gartley: 5, bat: 5, butterfly: 5, crab: 5, shark: 5, cypher: 5,
};
const rc = (dpr = 1): PrimitiveRenderContext => ({
  plotWidth: 800, plotHeight: 600, dpr, priceAxisWidth: 60,
  priceScale: { priceToY: (price: number) => 600 - price, format: String },
  timeScale: { indexToX: (index: number) => index },
  dataLayer: { timeToIndexFloat: (time: number) => time },
} as unknown as PrimitiveRenderContext);
const point = (time: number, price: number): DrawingPoint => ({ time, price });
const DEFAULT_POINTS = [point(100, 100), point(200, 300), point(300, 200), point(400, 260),
  point(500, 150), point(600, 280), point(700, 220)];
function tool(id: string): DrawingTool { return PATTERN_DRAWING_TOOLS.find(item => item.id === id)!; }
function drawing(id: string, points = DEFAULT_POINTS.slice(0, POINTS[id]), patch: Partial<Drawing> = {}): Drawing {
  return { id: 'pattern', tool: id, points, style: { ...tool(id).defaultStyle }, paneIndex: 0, zIndex: 0, ...patch };
}
function project(d: Drawing, context = rc()) {
  return d.points.map(p => ({
    x: context.timeScale.indexToX(context.dataLayer.timeToIndexFloat(p.time)),
    y: context.priceScale.priceToY(p.price),
  }));
}
class AlphaContext extends RecordingContext {
  public globalAlpha = 1;
  private stack: number[] = [];
  override save(): void { this.stack.push(this.globalAlpha); super.save(); }
  override restore(): void { this.globalAlpha = this.stack.pop() ?? 1; super.restore(); }
  override fill(): void { super.fill(); this.ops[this.ops.length - 1].args.push(this.globalAlpha); }
}
function paint(d: Drawing, context = rc()): AlphaContext {
  const rec = new AlphaContext();
  tool(d.tool).draw({
    ctx: rec as unknown as CanvasRenderingContext2D, rc: context,
    pts: project(d, context).map(p => ({ x: p.x * context.dpr, y: p.y * context.dpr })),
    drawing: d, style: { color: '#3366cc', lineWidth: 2, ...d.style }, selected: false, formatPrice: String,
  });
  return rec;
}
function hit(d: Drawing, x: number, y: number, context = rc()): number | null {
  return tool(d.tool).distance(x, y, { drawing: d, pts: project(d, context), rc: context });
}
const texts = (rec: RecordingContext): string[] => rec.ops.filter(op => op.type === 'fillText').map(op => op.text!);
const coords = (rec: RecordingContext, type: string): number[][] => rec.ops.filter(op => op.type === type).map(op => op.args.slice(0, 2));

describe('pattern drawing descriptors', () => {
  it('exports the eleven exact tools with fixed independent anchors', () => {
    expect(PATTERN_DRAWING_TOOLS.map(item => item.id)).toEqual(IDS);
    for (const id of IDS) {
      expect(tool(id).points).toBe(POINTS[id]);
      expect(tool(id).expand).toBeUndefined();
      expect(tool(id).constrain).toBeUndefined();
    }
  });

  it.each([
    ['xabcd-pattern', ['X', 'A', 'B', 'C', 'D']],
    ['abcd-pattern', ['A', 'B', 'C', 'D']],
    ['elliott-impulse', ['1', '2', '3', '4', '5']],
    ['elliott-correction', ['A', 'B', 'C']],
    ['head-shoulders', ['LS', 'H', 'RS']],
  ] as const)('%s connects its full sequence and labels every named point', (id, labels) => {
    const d = drawing(id);
    const rec = paint(d);
    for (let i = 1; i < POINTS[id]; i++) {
      expect(coords(rec, 'moveTo')).toContainEqual([DEFAULT_POINTS[i - 1].time, 600 - DEFAULT_POINTS[i - 1].price]);
      expect(coords(rec, 'lineTo')).toContainEqual([DEFAULT_POINTS[i].time, 600 - DEFAULT_POINTS[i].price]);
    }
    for (const label of labels) expect(texts(rec)).toContain(label);
  });

  it('measures generic XABCD and ABCD ratios from price legs', () => {
    const prices = [0, 100, 38.2, 69.1, 21.4];
    const xabcd = drawing('xabcd-pattern', prices.map((price, i) => point(100 + i * 100, price)));
    expect(texts(paint(xabcd))).toEqual(expect.arrayContaining([
      'X', 'A', 'B', 'C', 'D', 'AB/XA 0.618', 'BC/AB 0.500', 'CD/BC 1.544',
    ]));
    const abcd = drawing('abcd-pattern', prices.slice(1).map((price, i) => point(100 + i * 100, price)));
    expect(texts(paint(abcd))).toEqual(expect.arrayContaining(['A', 'B', 'C', 'D', 'BC/AB 0.500', 'CD/BC 1.544']));
  });

  it('draws two independently filled component triangles for XABCD families', () => {
    for (const id of ['xabcd-pattern', 'gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher']) {
      const rec = paint(drawing(id));
      expect(rec.count('fill'), id).toBe(2);
      expect(rec.count('stroke'), id).toBe(4);
    }
    expect(paint(drawing('abcd-pattern')).count('fill')).toBe(0);
  });

  it('extends the neckline through the outer shoulder legs', () => {
    const points = [point(100, 100), point(200, 200), point(300, 120), point(400, 300),
      point(500, 140), point(600, 210), point(700, 100)];
    const rec = paint(drawing('head-shoulders', points));
    expect(coords(rec, 'moveTo')).toContainEqual([100, 500]);
    expect(coords(rec, 'lineTo')).toContainEqual([650, 445]);
    expect(rec.count('stroke')).toBeGreaterThan(20);
    expect(hit(drawing('head-shoulders', points), 375, 472.5)).toBeLessThan(0.1);
  });
});

describe('harmonic rules and statuses', () => {
  const valid: Record<string, number[]> = {
    gartley: [0, 100, 38.2, 69.1, 21.4],
    bat: [0, 100, 55, 82, 11.4],
    butterfly: [0, 100, 21.4, 68.56, -40],
    crab: [0, 100, 50, 94.3, -61.8],
    shark: [0, 100, 50, 115, 0],
    cypher: [0, 100, 50, 130, 27.82],
  };
  const names: Record<string, string> = {
    gartley: 'Gartley', bat: 'Bat', butterfly: 'Butterfly', crab: 'Crab', shark: 'Shark', cypher: 'Cypher',
  };
  it.each([
    ['gartley', ['AB/XA 0.618 OK', 'BC/AB 0.500 OK', 'CD/BC 1.544 OK', 'AD/XA 0.786 OK']],
    ['bat', ['AB/XA 0.450 OK', 'BC/AB 0.600 OK', 'CD/BC 2.615 OK', 'AD/XA 0.886 OK']],
    ['butterfly', ['AB/XA 0.786 OK', 'BC/AB 0.600 OK', 'CD/BC 2.302 OK', 'AD/XA 1.400 OK']],
    ['crab', ['AB/XA 0.500 OK', 'BC/AB 0.886 OK', 'CD/BC 3.524 OK', 'AD/XA 1.618 OK']],
    ['shark', ['AB/XA 0.500 OK', 'BC/AB 1.300 OK', 'CD/BC 1.769 OK', 'AD/XA 1.000 OK']],
    ['cypher', ['AB/XA 0.500 OK', 'XC/XA 1.300 OK', 'CD/XC 0.786 OK']],
  ] as const)('%s accepts a sequence in its own expected ranges and prints measured rules', (id, expected) => {
    const d = drawing(id, valid[id].map((price, i) => point(100 + i * 100, price)));
    const labels = texts(paint(d));
    expect(labels).toContain(`${names[id]}: valid`);
    expect(labels).toEqual(expect.arrayContaining([...expected]));
  });

  it('applies distinct named ranges without changing arbitrary anchors', () => {
    const anchors = valid.gartley.map((price, i) => point(100 + i * 100, price));
    const statuses = ['gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher'].map(id => {
      const d = drawing(id, anchors);
      expect(d.points).toEqual(anchors);
      return texts(paint(d)).find(label => label.startsWith(names[id]));
    });
    expect(statuses).toEqual(['Gartley: valid', 'Bat: outside range', 'Butterfly: outside range',
      'Crab: outside range', 'Shark: outside range', 'Cypher: outside range']);
  });

  it('uses the non-adjacent projection and retracement rules for Cypher', () => {
    const d = drawing('cypher', valid.cypher.map((price, i) => point(100 + i * 100, price)));
    expect(texts(paint(d))).toEqual(expect.arrayContaining([
      'AB/XA 0.500 OK', 'XC/XA 1.300 OK', 'CD/XC 0.786 OK', 'Cypher: valid',
    ]));
  });

  it('rejects a same-direction leg sequence even when every magnitude is in range', () => {
    const prices = [0, 100, 161.8, 130.9, 178.6];
    const d = drawing('gartley', prices.map((price, i) => point(100 + i * 100, price)));
    expect(texts(paint(d))).toEqual(expect.arrayContaining([
      'AB/XA 0.618 OK', 'BC/AB 0.500 OK', 'CD/BC 1.544 OK', 'AD/XA 0.786 OK',
      'Gartley: invalid sequence',
    ]));
  });

  it('accepts the mirrored alternating sequence', () => {
    const prices = [0, -100, -38.2, -69.1, -21.4];
    const d = drawing('gartley', prices.map((price, i) => point(100 + i * 100, price)));
    expect(texts(paint(d))).toContain('Gartley: valid');
  });

  it('omits ratios with degenerate denominators and never paints non-finite arguments', () => {
    for (const id of IDS) {
      const same = Array.from({ length: POINTS[id] }, (_, i) => point(100 + i * 100, 100));
      const d = drawing(id, same);
      for (const dpr of [1, 2]) {
        const rec = paint(d, rc(dpr));
        expect(rec.ops.flatMap(op => op.args).every(Number.isFinite), `${id} at DPR ${dpr}`).toBe(true);
        expect(texts(rec).join(' ')).not.toMatch(/NaN|Infinity/);
      }
    }
  });
});

describe('pattern settings and hit geometry', () => {
  it.each(IDS)('%s ignores imported anchors beyond its declared fixed count', id => {
    const base = drawing(id);
    const extras = Array.from({ length: 256 }, (_, index) => point(780 - index % 2, index % 2 === 0 ? 100 : 500));
    const imported = drawing(id, [...base.points, ...extras]);
    expect(paint(imported).ops).toEqual(paint(base).ops);
    expect(imported.points).toHaveLength(base.points.length + extras.length);
  });

  it('does not hit an excess imported leg', () => {
    const points = [point(100, 500), point(200, 400), point(300, 500)];
    const base = drawing('elliott-correction', points);
    const imported = drawing('elliott-correction', [...points, point(300, 100)]);
    expect(hit(base, 300, 400)).toBeGreaterThan(100);
    expect(hit(imported, 300, 400)).toEqual(hit(base, 300, 400));
  });

  it.each(IDS)('%s hides every generated label when labels are disabled', id => {
    const d = drawing(id, undefined, { style: { ...tool(id).defaultStyle, showLabels: false } });
    expect(texts(paint(d))).toEqual([]);
  });

  it.each(['xabcd-pattern', 'gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher'])('%s fill settings affect paint and interior hits', id => {
    const points = [point(100, 100), point(200, 300), point(300, 200), point(400, 300), point(500, 100)];
    const d = drawing(id, points, { style: { ...tool(id).defaultStyle, fill: true, fillColor: '#fedcba', fillOpacity: 0.45 } });
    const rec = paint(d);
    expect(rec.ops.filter(op => op.type === 'fill').every(op => op.fillStyle === '#fedcba')).toBe(true);
    expect(rec.ops.filter(op => op.type === 'fill').every(op => op.args[op.args.length - 1] === 0.45)).toBe(true);
    expect(hit(d, 200, 400)).toBe(0);
    expect(hit(d, 400, 400)).toBe(0);
    d.style.fill = false;
    expect(hit(d, 200, 400)).toBeGreaterThan(20);
    d.style.fill = true;
    d.style.fillOpacity = 0;
    expect(hit(d, 200, 400)).toBeGreaterThan(20);
  });

  it('declares only settings that visibly change its output', () => {
    for (const descriptor of PATTERN_DRAWING_TOOLS) {
      const paths = descriptor.settings!.fields.map(field => field.path);
      expect(paths).toEqual(expect.arrayContaining(['style.color', 'style.lineWidth', 'style.lineStyle',
        'style.showLabels', 'text.color', 'text.fontSize', 'text.fontFamily', 'text.bold', 'text.italic']));
      expect(paths.includes('style.fill')).toBe(['xabcd-pattern', 'gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher'].includes(descriptor.id));
    }
  });

  it('consumes every declared setting in the painted output', () => {
    const values: Record<string, unknown> = {
      'style.color': '#cc1177', 'style.lineWidth': 7, 'style.lineStyle': 'dashed',
      'style.fill': false, 'style.fillColor': '#77cc11', 'style.fillOpacity': 0.67,
      'style.showLabels': false, 'text.color': '#ffff00', 'text.fontSize': 24,
      'text.fontFamily': 'monospace', 'text.bold': true, 'text.italic': true,
    };
    for (const descriptor of PATTERN_DRAWING_TOOLS) {
      for (const field of descriptor.settings!.fields) {
        const base = drawing(descriptor.id);
        const changed = { ...base, style: { ...base.style }, text: { value: '' } };
        const [root, key] = field.path.split('.');
        if (root === 'style') changed.style = { ...changed.style, [key]: values[field.path] };
        if (root === 'text') changed.text = { ...changed.text!, [key]: values[field.path] };
        expect(paint(changed).ops, `${descriptor.id} ${field.path}`).not.toEqual(paint(base).ops);
      }
    }
  });

  it.each(IDS)('%s converts media coordinates exactly once and keeps hit tests DPR independent', id => {
    const d = drawing(id);
    const normal = paint(d), double = paint(d, rc(2));
    expect(coords(double, 'moveTo')).toEqual(coords(normal, 'moveTo').map(pair => pair.map(value => value * 2)));
    expect(coords(double, 'lineTo')).toEqual(coords(normal, 'lineTo').map(pair => pair.map(value => value * 2)));
    expect(double.ops.filter(op => op.type === 'fillText').map(op => op.args.slice(0, 2)))
      .toEqual(normal.ops.filter(op => op.type === 'fillText').map(op => op.args.slice(0, 2).map(value => value * 2)));
    expect(hit(d, 250, 350, rc(2))).toEqual(hit(d, 250, 350));
  });
});
