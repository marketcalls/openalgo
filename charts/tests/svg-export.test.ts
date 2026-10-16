/**
 * Vector export: the serialising context and `chart.exportSVG`.
 *
 * The export is the ordinary paint run into `SvgContext`, so the contract has
 * two halves. The context must express every op the paint code emits (the
 * recorder in `helpers/fake-ctx.ts` sees the same stream, which is how the set
 * is enumerated here), and the document it writes must be one well-formed root
 * with the panes as clipped groups and the labels as text.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import type { PaneRenderContext } from '../src/core/pane';
import { SvgContext, SvgLinearGradient } from '../src/render/svg-export';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { fakeDocument } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';
import { DrawingController } from '../src/draw/index';
import type { Bar } from '../src/model/bar';

const W = 800;
const H = 600;

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * 60, open: c - 0.5, high: c + 2, low: c - 2, close: c, volume: 10 + (i % 5) };
  });

/**
 * A chart that paints synchronously: the recorder canvases hold a full frame
 * by the time a call returns, and the export sees measured scales.
 */
function makeChart(ratio = 1): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => ratio,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(W, H);
  return chart;
}

/**
 * The reference chart: a candlestick, a volume histogram on its own pane, an
 * area (the one series that fills with a gradient), a dashed price line and a
 * rectangle drawing. Between them they touch every op the export has to carry.
 */
function loaded(ratio = 1): { chart: Chart; data: Bar[] } {
  const chart = makeChart(ratio);
  const data = bars(120);
  chart.addSeries('candlestick').setData(data);
  chart.addSeries('histogram', { paneIndex: 1 }).setData(data.map((b) => ({ time: b.time, open: 0, high: b.volume ?? 0, low: 0, close: b.volume ?? 0 })));
  chart.addSeries('area', { style: { color: '#2962ff' } }).setData(data.map((b) => ({ time: b.time, value: b.close - 3 })));
  chart.addPriceLine({ id: 'sl', price: 101, color: '#ef5350', lineStyle: 'dashed', label: 'SL' });
  const draw = new DrawingController(chart);
  draw.add({
    tool: 'rectangle', paneIndex: 0, style: {},
    points: [{ time: data[20].time, price: 98 }, { time: data[60].time, price: 104 }],
  });
  return { chart, data };
}

/** Every op type the recorder canvases saw across both layers of every pane. */
function recordedOps(chart: Chart): Set<string> {
  const types = new Set<string>();
  for (const pane of chart.panes()) {
    for (const layer of [pane.base, pane.top]) {
      for (const op of (layer.ctx as unknown as RecordingContext).ops) types.add(op.type);
    }
  }
  return types;
}

/** A render context equal to the chart's own, for painting a pane by hand. */
function renderContext(chart: Chart, showTimeAxis: boolean): PaneRenderContext {
  return {
    timeScale: chart.timeScale, dataLayer: chart.dataLayer, dpr: 1,
    priceAxisWidth: 56, timeAxisHeight: 22, showTimeAxis,
    conflate: false, conflationFactor: 1, theme: chart.theme(),
    showVertGrid: true, showHorzGrid: true,
  };
}

/** Walk the tags and check every open has its close, in order. */
function assertWellFormed(svg: string): void {
  const stack: string[] = [];
  const re = /<(\/?)([a-zA-Z]+)(?:\s[^>]*?)?(\/?)>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(svg)) !== null) {
    const [, closing, name, selfClosing] = m;
    if (closing === '/') {
      expect(stack.pop(), `close of ${name} at ${m.index}`).toBe(name);
    } else if (selfClosing !== '/') {
      stack.push(name);
    }
  }
  expect(stack).toEqual([]);
}

const count = (s: string, re: RegExp): number => (s.match(re) ?? []).length;

describe('chart.exportSVG', () => {
  it('serialises every op the recorders emit for the reference chart, and none of them is refused', () => {
    const { chart } = loaded();
    const types = recordedOps(chart);
    // The reference chart really does exercise the set the export exists for.
    for (const t of ['fillRect', 'fillText', 'moveTo', 'lineTo', 'stroke', 'fill', 'clip', 'setLineDash', 'createLinearGradient', 'save', 'restore']) {
      expect(types.has(t), `reference chart emits ${t}`).toBe(true);
    }
    // `setTransform` and `clearRect` come from `clearBitmap`, which sizes the
    // real canvas and is skipped when painting into a target.
    types.delete('setTransform');
    types.delete('clearRect');
    // `addColorStop` is a method of the gradient handle, not of the context.
    types.delete('addColorStop');
    expect(typeof SvgLinearGradient.prototype.addColorStop).toBe('function');
    for (const t of types) {
      expect(typeof (SvgContext.prototype as unknown as Record<string, unknown>)[t], `SvgContext.${t}`).toBe('function');
    }
    // The strict context throws on anything it cannot express, so the same
    // paint that filled the recorders has to run clean through it.
    const strict = new SvgContext(W, H, { strict: true });
    const g = strict.asCanvasContext();
    const panes = chart.panes();
    for (let i = 0; i < panes.length; i++) {
      const ctx = renderContext(chart, i === panes.length - 1);
      panes[i].autoscale(ctx);
      expect(() => { panes[i].paintBase(ctx, g); panes[i].paintTop(null, ctx, g); }).not.toThrow();
    }
    expect(strict.unsupported).toEqual([]);
    const out = strict.toString();
    expect(out).toContain('<path');
    expect(out).toContain('stroke-dasharray=');
    expect(out).toContain('<linearGradient');
  });

  it('writes numbers to at most two decimals', () => {
    const { chart } = loaded();
    const svg = chart.exportSVG();
    const decimals = svg.match(/\d+\.\d+/g) ?? [];
    expect(decimals.length).toBeGreaterThan(0);
    const long = decimals.filter((n) => n.split('.')[1].length > 2);
    expect(long).toEqual([]);
  });

  it('is one well-formed root with balanced groups', () => {
    const { chart } = loaded();
    const svg = chart.exportSVG();
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg" ')).toBe(true);
    expect(svg.endsWith('</svg>')).toBe(true);
    expect(count(svg, /<svg\b/g)).toBe(1);
    expect(svg).toContain(`viewBox="0 0 ${W} ${H}"`);
    expect(count(svg, /<g\b/g)).toBe(count(svg, /<\/g>/g));
    expect(count(svg, /<clipPath\b/g)).toBe(count(svg, /<\/clipPath>/g));
    assertWellFormed(svg);
  });

  it('gives each pane its own clipped group at the box the DOM lays it out in', () => {
    const { chart } = loaded();
    const [p0, p1] = chart.panes();
    const total = p0.weight + p1.weight;
    // The boundary between the panes sits on a whole pixel, as it does on
    // screen at ratio 1, the ratio the document is at.
    const h0 = Math.round((H * p0.weight) / total);
    const h1 = H - h0;
    const svg = chart.exportSVG();
    expect(count(svg, /<g data-pane="/g)).toBe(2);
    // The first pane sits at the top; the second is one row down, behind the
    // separator the DOM draws as its border at ratio 1, and one row shorter for it.
    expect(svg).toContain(`<g data-pane="0" transform="translate(0 0)" clip-path="url(#`);
    expect(svg).toContain(`<g data-pane="1" transform="translate(0 ${h0 + 1})" clip-path="url(#`);
    const clips = svg.match(/<clipPath id="c\d+"><rect x="0" y="0" width="800" height="([\d.]+)"\/><\/clipPath>/g) ?? [];
    expect(clips.map((c) => /height="([\d.]+)"/.exec(c)?.[1])).toEqual([String(h0), String(h1 - 1)]);
    expect(svg).toContain(`<rect x="0" y="${h0}" width="800" height="1" fill="${chart.theme().paneSeparator}"/>`);
  });

  it('is the same document at every screen pixel ratio', () => {
    // Three panes whose boundaries round differently at 1, 1.5 and 2.
    const exports = [1, 1.5, 2].map((ratio) => {
      const { chart } = loaded(ratio);
      chart.addSeries('line', { paneIndex: 2 }).setData(bars(120).map((b) => ({ time: b.time, value: b.close })));
      chart.applySize(W, 517);
      const screen = (): unknown => chart.panes().map((pane, i) => [pane.priceScale.height, chart.priceToCoordinate(100, i)]);
      const before = screen();
      const svg = chart.exportSVG();
      // And the screen's own layout is put back afterwards.
      expect(screen()).toEqual(before);
      return svg;
    });
    expect(exports[0]).toMatch(/<g data-pane="2" transform="translate\(0 \d+\)"/);
    expect(exports[1]).toBe(exports[0]);
    expect(exports[2]).toBe(exports[0]);
  });

  it('keeps the axis labels as text', () => {
    const { chart, data } = loaded();
    const svg = chart.exportSVG();
    const last = chart.panes()[0].priceScale.format(data[data.length - 1].close);
    expect(svg).toContain(`>${last}</text>`);
    // The ladder, the time strip and the price-line label together.
    expect(count(svg, /<text\b/g)).toBeGreaterThan(8);
    expect(svg).toContain('>SL</text>');
  });

  it('paints the background only when asked to', () => {
    const { chart } = loaded();
    const bg = chart.theme().background;
    const root = `<rect x="0" y="0" width="${W}" height="${H}" fill="${bg}"/>`;
    const withBg = chart.exportSVG();
    expect(withBg).toContain(root);
    expect(count(withBg, new RegExp(`<rect x="0" y="0" width="800" height="[\\d.]+" fill="${bg}"/>`, 'g'))).toBe(3);
    const without = chart.exportSVG({ background: false });
    expect(without).not.toContain(root);
    // The pane fill is off too, or the option would leave a chart-shaped hole.
    expect(count(without, new RegExp(`<rect x="0" y="0" width="800" height="[\\d.]+" fill="${bg}"/>`, 'g'))).toBe(0);
    // Everything else is still there.
    expect(count(without, /<text\b/g)).toBe(count(withBg, /<text\b/g));
  });

  it('exports at a requested size and leaves the live layout untouched', () => {
    const { chart } = loaded();
    let resizes = 0;
    chart.on('resize', () => { resizes++; });
    const scale = chart.panes()[0].priceScale;
    const liveHeight = scale.height;
    const liveWidth = chart.timeScale.width;
    const spacing = chart.timeScale.barSpacing;
    const svg = chart.exportSVG({ width: 1200, height: 900 });
    expect(svg).toContain('viewBox="0 0 1200 900"');
    expect(svg).toContain('width="1200" height="900"');
    // The plot was really laid out at the new size: the pane clip is 1200 wide
    // and the time axis strip sits where a 900px chart puts it.
    expect(svg).toMatch(/<clipPath id="c\d+"><rect x="0" y="0" width="1200" height="/);
    expect(chart.timeScale.width).toBe(liveWidth);
    expect(chart.timeScale.barSpacing).toBe(spacing);
    expect(scale.height).toBe(liveHeight);
    expect(resizes).toBe(0);
    // A same-size export after it still describes the live chart.
    expect(chart.exportSVG()).toContain(`viewBox="0 0 ${W} ${H}"`);
  });

  it('refuses a pixel ratio other than 1', () => {
    const { chart } = loaded();
    expect(() => chart.exportSVG({ dpr: 2 as unknown as 1 })).toThrow(RangeError);
    expect(() => chart.exportSVG({ dpr: 1 })).not.toThrow();
  });

  it('leaves out a pane hidden behind a maximized one', () => {
    const { chart } = loaded();
    chart.maximizePane(0);
    const svg = chart.exportSVG();
    expect(count(svg, /<g data-pane="/g)).toBe(1);
    expect(svg).toContain('<g data-pane="0"');
  });
});

describe('SvgContext', () => {
  const body = (c: SvgContext): string => {
    const s = c.toString();
    const start = s.indexOf('>', s.indexOf('<svg')) + 1;
    return s.slice(start, -'</svg>'.length).replace(/<defs>.*<\/defs>/, '');
  };
  const defs = (c: SvgContext): string => /<defs>(.*)<\/defs>/.exec(c.toString())?.[1] ?? '';

  it.each([
    [1e307, '1e+307'],
    [-1e307, '-1e+307'],
    [Number.MAX_VALUE, '1.7976931348623157e+308'],
    [-Number.MAX_VALUE, '-1.7976931348623157e+308'],
  ])('preserves the finite coordinate %s when decimal scaling would overflow', (value, serialized) => {
    const c = new SvgContext(240, 180, { strict: true });
    c.moveTo(value, 60);
    c.lineTo(120, 60);
    c.stroke();
    expect(body(c)).toContain(`d="M${serialized} 60L120 60"`);
    expect(c.toString()).not.toMatch(/Infinity|NaN/);
  });

  it('retains ordinary rounding, zero normalization and the nonfinite fallback', () => {
    const c = new SvgContext(240, 180);
    c.moveTo(1.234, -1.236);
    c.lineTo(NaN, Infinity);
    c.lineTo(-Infinity, -0.001);
    c.lineTo(Number.MIN_VALUE, -0);
    c.stroke();
    expect(body(c)).toContain('d="M1.23 -1.24L0 0L0 0L0 0"');
  });

  it('exports a clipped smooth path with huge finite anchors and controls', () => {
    const primitive = new IndicatorDrawings();
    primitive.setItems([{
      kind: 'polyline', curve: 'smooth',
      points: [{ time: 0, price: -1e307 }, { time: 60, price: 60 }, { time: 120, price: 1e307 }],
    }]);
    const rc = {
      dpr: 1, plotWidth: 240, plotHeight: 180, theme: { axisText: '#fff' },
      timeScale: { indexToX: (n: number) => n },
      dataLayer: { timeToIndexFloat: (n: number) => n },
      priceScale: { priceToY: (n: number) => n },
    } as unknown as PrimitiveRenderContext;
    const c = new SvgContext(240, 180, { strict: true });
    primitive.draw(c.asCanvasContext(), rc);
    const svg = c.toString();
    expect(svg).toContain('clip-path="url(#c1)"');
    expect(svg).toContain('d="M0 -1e+307C');
    expect(svg).toContain('120 1e+307"');
    expect(svg.match(/C/g)).toHaveLength(2);
    expect(svg).not.toMatch(/Infinity|NaN/);
    expect(c.unsupported).toEqual([]);
    assertWellFormed(svg);
  });

  it('writes a rect path and a filled path', () => {
    const c = new SvgContext(10, 10);
    c.fillStyle = '#abc';
    c.beginPath();
    c.rect(1, 2, 3, 4);
    c.fill();
    expect(body(c)).toBe('<path d="M1 2h3v4h-3Z" fill="#abc"/>');
  });

  it('carries every stroke property onto the path', () => {
    const c = new SvgContext(10, 10);
    c.strokeStyle = '#fff';
    c.lineWidth = 2;
    c.lineCap = 'round';
    c.lineJoin = 'round';
    c.setLineDash([4, 2]);
    c.globalAlpha = 0.5;
    c.beginPath();
    c.moveTo(0, 0.5);
    c.lineTo(10, 0.5);
    c.stroke();
    expect(body(c)).toBe('<path d="M0 0.5L10 0.5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="4 2" opacity="0.5"/>');
    expect(c.getLineDash()).toEqual([4, 2]);
  });

  it('carries a dash offset with the dash list, and not without one', () => {
    const c = new SvgContext(10, 10);
    c.setLineDash([6, 4]);
    c.save();
    c.lineDashOffset = 7.25;
    c.beginPath(); c.moveTo(0, 0); c.lineTo(10, 0); c.stroke();
    c.restore();
    c.beginPath(); c.moveTo(0, 1); c.lineTo(10, 1); c.stroke();
    expect(c.lineDashOffset).toBe(0);
    const paths = body(c).split('/>');
    expect(paths[0]).toContain('stroke-dasharray="6 4" stroke-dashoffset="7.25"');
    expect(paths[1]).not.toContain('stroke-dashoffset');
    const solid = new SvgContext(10, 10);
    solid.lineDashOffset = 3;
    solid.beginPath(); solid.moveTo(0, 0); solid.lineTo(1, 1); solid.stroke();
    expect(body(solid)).not.toContain('stroke-dashoffset');
  });

  it('turns an empty dash list back into a solid line', () => {
    const c = new SvgContext(10, 10);
    c.setLineDash([4, 2]);
    c.setLineDash([]);
    c.beginPath(); c.moveTo(0, 0); c.lineTo(1, 1); c.stroke();
    expect(body(c)).not.toContain('stroke-dasharray');
  });

  it('draws a full circle as two arcs and a partial arc with the right flags', () => {
    const c = new SvgContext(20, 20);
    c.beginPath(); c.arc(10, 10, 5, 0, Math.PI * 2); c.fill();
    expect(body(c)).toBe('<path d="M15 10A5 5 0 0 1 5 10A5 5 0 0 1 15 10" fill="#000"/>');
    const d = new SvgContext(20, 20);
    // Anticlockwise upper half: from (1,0) back round through (0,-1) to (-1,0).
    d.beginPath(); d.arc(0, 0, 1, 0, Math.PI, true); d.stroke();
    expect(body(d)).toContain('d="M1 0A1 1 0 0 0 -1 0"');
    const e = new SvgContext(20, 20);
    // Three quarters clockwise is the large arc.
    e.beginPath(); e.arc(0, 0, 1, 0, Math.PI * 1.5); e.stroke();
    expect(body(e)).toContain('d="M1 0A1 1 0 1 1 0 -1"');
  });

  it('joins an arc to the subpath in progress with a line', () => {
    const c = new SvgContext(20, 20);
    c.beginPath(); c.moveTo(0, 0); c.arc(10, 10, 2, 0, Math.PI); c.stroke();
    expect(body(c)).toContain('d="M0 0L12 10A2 2 0 0 1 8 10"');
  });

  it('writes an ellipse, a rounded rectangle and both curve kinds', () => {
    const c = new SvgContext(20, 20);
    c.beginPath(); c.ellipse(0, 0, 2, 1, 0, 0, Math.PI * 2); c.fill();
    expect(body(c)).toContain('d="M2 0A2 1 0 0 1 -2 0A2 1 0 0 1 2 0"');
    const r = new SvgContext(20, 20);
    r.beginPath(); r.roundRect(0, 0, 10, 4, 1); r.fill();
    expect(body(r)).toContain('d="M1 0H9A1 1 0 0 1 10 1V3A1 1 0 0 1 9 4H1A1 1 0 0 1 0 3V1A1 1 0 0 1 1 0Z"');
    // Per-corner radii in CSS order, the left-capped half of a button pair.
    const p = new SvgContext(20, 20);
    p.beginPath(); p.roundRect(0, 0, 10, 4, [2, 0, 0, 2]); p.fill();
    expect(body(p)).toContain('d="M2 0H10V4H2A2 2 0 0 1 0 2V2A2 2 0 0 1 2 0Z"');
    // A radius larger than the box shrinks to fit rather than folding over.
    const q = new SvgContext(20, 20);
    q.beginPath(); q.roundRect(0, 0, 10, 4, 10); q.fill();
    expect(body(q)).toContain('d="M2 0H8A2 2 0 0 1 10 2V2A2 2 0 0 1 8 4H2A2 2 0 0 1 0 2V2A2 2 0 0 1 2 0Z"');
    const k = new SvgContext(20, 20);
    k.beginPath(); k.moveTo(0, 0); k.quadraticCurveTo(1, 2, 3, 4); k.bezierCurveTo(5, 6, 7, 8, 9, 10); k.closePath(); k.stroke();
    expect(body(k)).toContain('d="M0 0Q1 2 3 4C5 6 7 8 9 10Z"');
  });

  it('writes rectangles directly, normalising a negative extent', () => {
    const c = new SvgContext(20, 20);
    c.fillStyle = '#123';
    c.fillRect(5, 5, -3, 2);
    c.strokeStyle = '#456';
    c.strokeRect(0, 0, 4, 4);
    c.fillRect(0, 0, 0, 4);
    expect(body(c)).toBe('<rect x="2" y="5" width="3" height="2" fill="#123"/><rect x="0" y="0" width="4" height="4" fill="none" stroke="#456" stroke-width="1"/>');
  });

  it('maps text alignment, baseline and font onto the text element and escapes the content', () => {
    const c = new SvgContext(20, 20);
    c.font = '600 11px system-ui, sans-serif';
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    c.fillStyle = '#fff';
    c.fillText('a <b> & "c"', 1, 2);
    expect(body(c)).toBe('<text x="1" y="2" font-family="system-ui, sans-serif" font-size="11" font-weight="600" text-anchor="middle" dominant-baseline="central" fill="#fff">a &lt;b&gt; &amp; &quot;c&quot;</text>');
    const d = new SvgContext(20, 20);
    d.font = 'italic bold 9pt Georgia';
    d.textAlign = 'right';
    d.textBaseline = 'top';
    d.fillText('x', 0, 0);
    expect(body(d)).toBe('<text x="0" y="0" font-family="Georgia" font-size="12" font-weight="bold" font-style="italic" text-anchor="end" dominant-baseline="text-before-edge" fill="#000">x</text>');
    const e = new SvgContext(20, 20);
    e.fillText('', 0, 0);
    expect(body(e)).toBe('');
  });

  it('measures text in proportion to the font size', () => {
    const c = new SvgContext(20, 20);
    c.font = '10px system-ui, sans-serif';
    const ten = c.measureText('1234.56').width;
    c.font = '20px system-ui, sans-serif';
    expect(c.measureText('1234.56').width).toBeCloseTo(ten * 2, 6);
    // Digits sit at the average width; the point is narrow.
    expect(ten).toBeCloseTo((6 * 0.55 + 0.3) * 10, 6);
    c.font = '600 20px system-ui, sans-serif';
    expect(c.measureText('1234.56').width).toBeGreaterThan(ten * 2);
    expect(c.measureText('').width).toBe(0);
  });

  it('defines a linear gradient once and fills by reference', () => {
    const c = new SvgContext(20, 100);
    const g = c.createLinearGradient(0, 0, 0, 100);
    expect(g).toBeInstanceOf(SvgLinearGradient);
    g.addColorStop(0, 'rgba(0,0,255,0.4)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    c.fillStyle = g;
    c.fillRect(0, 0, 20, 100);
    c.beginPath(); c.rect(0, 0, 1, 1); c.fill();
    expect(defs(c)).toBe('<linearGradient id="g1" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="100"><stop offset="0" stop-color="rgba(0,0,255,0.4)"/><stop offset="1" stop-color="rgba(0,0,0,0)"/></linearGradient>');
    expect(body(c)).toBe('<rect x="0" y="0" width="20" height="100" fill="url(#g1)"/><path d="M0 0h1v1h-1Z" fill="url(#g1)"/>');
  });

  it('nests transforms and clips as groups closed by restore, and restores the style', () => {
    const c = new SvgContext(20, 20);
    c.fillStyle = '#111';
    c.save();
    c.fillStyle = '#222';
    c.translate(10, 20);
    c.beginPath(); c.rect(0, 0, 5, 5); c.clip();
    c.fillRect(0, 0, 1, 1);
    c.restore();
    c.fillRect(0, 0, 1, 1);
    expect(defs(c)).toBe('<clipPath id="c1"><path d="M0 0h5v5h-5Z"/></clipPath>');
    expect(body(c)).toBe('<g transform="translate(10 20)"><g clip-path="url(#c1)"><rect x="0" y="0" width="1" height="1" fill="#222"/></g></g><rect x="0" y="0" width="1" height="1" fill="#111"/>');
    expect(c.fillStyle).toBe('#111');
  });

  it('skips identity transforms and writes scale and rotate', () => {
    const c = new SvgContext(20, 20);
    c.save(); c.translate(0, 0); c.scale(1, 1); c.rotate(0); c.fillRect(0, 0, 1, 1); c.restore();
    expect(body(c)).toBe('<rect x="0" y="0" width="1" height="1" fill="#000"/>');
    const d = new SvgContext(20, 20);
    d.save(); d.scale(2, 3); d.rotate(Math.PI / 2); d.fillRect(0, 0, 1, 1); d.restore();
    expect(body(d)).toBe('<g transform="scale(2 3)"><g transform="rotate(90)"><rect x="0" y="0" width="1" height="1" fill="#000"/></g></g>');
  });

  it('closes what is still open at serialisation time without consuming it', () => {
    const c = new SvgContext(20, 20);
    c.save(); c.translate(1, 1); c.fillRect(0, 0, 1, 1);
    const first = c.toString();
    expect(first.endsWith('</g></svg>')).toBe(true);
    expect(c.toString()).toBe(first);
    c.restore();
    expect(c.toString()).toBe(first);
    // A restore with nothing saved is a no-op, as on a canvas.
    c.restore();
    expect(c.toString()).toBe(first);
  });

  it('wraps a pushGroup in one element with its clip and attributes', () => {
    const c = new SvgContext(20, 20);
    c.pushGroup({ 'data-pane': 1 }, { translate: { x: 0, y: 5.004 }, clip: { x: 0, y: 0, width: 20, height: 15 } });
    c.save(); c.translate(2, 2); c.fillRect(0, 0, 1, 1); c.restore();
    c.popGroup();
    c.fillRect(1, 1, 1, 1);
    expect(defs(c)).toBe('<clipPath id="c1"><rect x="0" y="0" width="20" height="15"/></clipPath>');
    expect(body(c)).toBe('<g data-pane="1" transform="translate(0 5)" clip-path="url(#c1)"><g transform="translate(2 2)"><rect x="0" y="0" width="1" height="1" fill="#000"/></g></g><rect x="1" y="1" width="1" height="1" fill="#000"/>');
  });

  it('refuses a mismatched group or restore under strict, and mends it otherwise', () => {
    const strict = new SvgContext(20, 20, { strict: true });
    expect(() => strict.popGroup()).toThrow(/pushGroup/);
    strict.pushGroup({});
    strict.save();
    expect(() => strict.popGroup()).toThrow(/save/);
    const lax = new SvgContext(20, 20);
    lax.pushGroup({ id: 'a' });
    lax.save();
    lax.translate(1, 1);
    lax.popGroup();
    lax.fillRect(0, 0, 1, 1);
    expect(body(lax)).toBe('<g id="a"><g transform="translate(1 1)"></g></g><rect x="0" y="0" width="1" height="1" fill="#000"/>');
  });

  it('paints nothing for a transparent style or a zero alpha', () => {
    const c = new SvgContext(20, 20);
    c.fillStyle = 'transparent';
    c.fillRect(0, 0, 5, 5);
    c.fillStyle = '#fff';
    c.globalAlpha = 0;
    c.fillRect(0, 0, 5, 5);
    c.fillText('x', 0, 0);
    c.globalAlpha = 1;
    c.lineWidth = 0;
    c.beginPath(); c.moveTo(0, 0); c.lineTo(1, 1); c.stroke();
    expect(body(c)).toBe('');
  });

  it('clears to the background it was given and to nothing otherwise', () => {
    const c = new SvgContext(20, 20, { background: '#101010' });
    c.clearRect(0, 0, 5, 5);
    expect(body(c)).toBe('<rect x="0" y="0" width="5" height="5" fill="#101010"/>');
    const d = new SvgContext(20, 20);
    d.clearRect(0, 0, 5, 5);
    expect(body(d)).toBe('');
  });

  it('places an image by its source URL in each drawImage form', () => {
    const c = new SvgContext(20, 20);
    const img = { src: 'data:image/png;base64,AA==', naturalWidth: 4, naturalHeight: 2 } as unknown as CanvasImageSource;
    c.drawImage(img, 1, 1);
    c.drawImage(img, 1, 1, 8, 4);
    c.drawImage(img, 0, 0, 2, 2, 5, 5, 4, 4);
    expect(body(c)).toBe(
      '<image href="data:image/png;base64,AA==" x="1" y="1" width="4" height="2" preserveAspectRatio="none"/>' +
      '<image href="data:image/png;base64,AA==" x="1" y="1" width="8" height="4" preserveAspectRatio="none"/>' +
      '<svg x="5" y="5" width="4" height="4" viewBox="0 0 2 2" preserveAspectRatio="none"><image href="data:image/png;base64,AA==" width="4" height="2" preserveAspectRatio="none"/></svg>',
    );
    const canvas = { width: 3, height: 3, toDataURL: () => 'data:image/png;base64,BB==' } as unknown as CanvasImageSource;
    const d = new SvgContext(20, 20);
    d.drawImage(canvas, 0, 0);
    expect(body(d)).toContain('href="data:image/png;base64,BB=="');
  });

  it('throws on a call with no vector form under strict and records it otherwise', () => {
    const strict = new SvgContext(10, 10, { strict: true });
    expect(() => strict.setTransform()).toThrow(/setTransform/);
    expect(() => strict.drawImage({} as CanvasImageSource, 0, 0)).toThrow(/drawImage/);
    expect(() => strict.createPattern()).toThrow(/createPattern/);
    const lax = new SvgContext(10, 10);
    lax.setTransform();
    lax.setTransform();
    lax.drawImage({} as CanvasImageSource, 0, 0);
    expect(lax.isPointInPath()).toBe(false);
    expect(lax.unsupported).toEqual(['setTransform', 'drawImage', 'isPointInPath']);
    expect(lax.canvas).toBeUndefined();
    expect(body(lax)).toBe('');
  });
});
