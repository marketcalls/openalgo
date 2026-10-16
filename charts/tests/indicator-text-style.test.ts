import { describe, it, expect } from 'vitest';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import { SeriesMarkers, type SeriesMarker } from '../src/primitives/markers';
import type { IndicatorDrawing } from '../src/model/indicator-registry';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { SvgContext } from '../src/render/svg-export';
import { darkTheme } from '../src/theme';
import { makeCtx, type Op } from './helpers/fake-ctx';

type Drawing = IndicatorDrawing;
type Marker = SeriesMarker;
const at = (x: number, y: number) => ({ time: x, price: y });
const drawingsRc = (dpr = 1): PrimitiveRenderContext => ({
  timeScale: { indexToX: (i: number) => i }, dataLayer: { timeToIndexFloat: (t: number) => t },
  priceScale: { priceToY: (price: number) => price }, dpr, plotWidth: 400, plotHeight: 300,
  priceAxisWidth: 56, theme: darkTheme,
} as unknown as PrimitiveRenderContext);
const texts = (ops: Op[]) => ops.filter(op => op.type === 'fillText');
const plate = (ops: Op[]) => ops.find(op => op.type === 'roundRect')!;
function recorder() {
  const h = makeCtx(), measures: string[] = [];
  h.ctx.measureText = text => {
    measures.push(h.ctx.font);
    const size = Number(/([\d.]+)px/.exec(h.ctx.font)![1]);
    return { width: text.length * size / 2 } as TextMetrics;
  };
  return { ...h, measures };
}
function draw(items: Drawing[], dpr = 1) {
  const primitive = new IndicatorDrawings(), h = recorder(); primitive.setItems(items);
  primitive.draw(h.ctx, drawingsRc(dpr)); return { primitive, ...h };
}
function markerFixture(dpr = 1) {
  const dataLayer = new DataLayer(), id = dataLayer.createSeries();
  dataLayer.setSeriesData(id, [{ time: 100, open: 10, high: 12, low: 8, close: 10 }]);
  const timeScale = new TimeScale({ barSpacing: 20, rightOffset: 0 }); timeScale.setWidth(400); timeScale.setBaseIndex(0);
  const priceScale = new PriceScale(); priceScale.setHeight(300); priceScale.setPriceRange({ min: 0, max: 20 });
  const rc: PrimitiveRenderContext = { dataLayer, timeScale, priceScale, dpr, plotWidth: 400, plotHeight: 300, priceAxisWidth: 56, theme: darkTheme };
  return { primitive: new SeriesMarkers(id), rc };
}
function marker(patch: Partial<Marker> = {}): Marker {
  return { time: 100, position: 'atPrice', price: 10, shape: 'circle', size: 'medium', color: '#e14b64', text: 'a\nBBBB', id: 'event', ...patch };
}

describe('descriptor typography', () => {
  it('preserves omitted drawing font and legacy plate coordinates', () => {
    const h = draw([{ kind: 'label', at: at(200, 100), text: 'a\nBBBB' }]);
    expect(texts(h.rec.ops).map(op => op.font)).toEqual(['11px ui-sans-serif, system-ui, sans-serif', '11px ui-sans-serif, system-ui, sans-serif']);
    expect(plate(h.rec.ops).args.slice(0, 4)).toEqual([184, 82.15, 32, 35.7]);
  });

  for (const dpr of [1, 1.5, 2]) it(`uses one explicit font for measuring, drawing and hit bounds at DPR ${dpr}`, () => {
    const h = draw([{ kind: 'label', at: at(200, 100), text: 'a\nBBBB', id: 'caption', fontSize: 20,
      fontFamily: 'ui-monospace, monospace', bold: true, italic: true }], dpr);
    expect(h.measures).toEqual([`italic 600 ${20 * dpr}px ui-monospace, monospace`, `italic 600 ${20 * dpr}px ui-monospace, monospace`]);
    expect(texts(h.rec.ops).every(op => op.font === h.measures[0])).toBe(true);
    expect(plate(h.rec.ops).args.slice(0, 4)).toEqual([175 * dpr, 70 * dpr, 50 * dpr, 60 * dpr]);
    expect(texts(h.rec.ops).map(op => op.args)).toEqual([[180 * dpr, 86.5 * dpr], [180 * dpr, 113.5 * dpr]]);
    expect(h.primitive.hitTest(176, 71)?.externalId).toBe('caption');
    expect(h.primitive.hitTest(174, 71)).toBeNull();
  });

  it.each(['top', 'middle', 'bottom'] as const)('anchors a label plate on its %s edge', verticalAlign => {
    const h = draw([{ kind: 'label', at: at(200, 100), text: 'a\nBBBB', fontSize: 20, verticalAlign }]);
    expect(plate(h.rec.ops).args[1]).toBe(verticalAlign === 'top' ? 100 : verticalAlign === 'bottom' ? 40 : 70);
  });

  it.each([
    ['left', 'top', 100, 80], ['center', 'middle', 175, 110], ['right', 'bottom', 250, 140],
  ] as const)('positions a box caption %s/%s', (align, verticalAlign, x, y) => {
    const h = draw([{ kind: 'box', from: at(100, 80), to: at(300, 200), text: 'a\nBBBB', fontSize: 20, align, verticalAlign }]);
    expect(plate(h.rec.ops).args.slice(0, 4)).toEqual([x, y, 50, 60]);
  });

  it('resets the font for an unstyled item after a styled item', () => {
    const h = draw([{ kind: 'label', at: at(100, 100), text: 'Styled', fontSize: 20, bold: true },
      { kind: 'label', at: at(200, 100), text: 'Plain' }]);
    expect(texts(h.rec.ops).map(op => op.font)).toEqual(['600 20px ui-sans-serif, system-ui, sans-serif', '11px ui-sans-serif, system-ui, sans-serif']);
  });

  it('does not pass the caption font into the separate hover detail', () => {
    const primitive = new IndicatorDrawings(), h = recorder();
    primitive.setItems([{ kind: 'label', at: at(200, 150), text: 'Caption', tooltip: 'Detail', id: 'tip', fontSize: 20, bold: true } as Drawing]);
    primitive.draw(h.ctx, { ...drawingsRc(), hoverId: 'tip' });
    expect(texts(h.rec.ops).map(op => op.font)).toEqual(['600 20px ui-sans-serif, system-ui, sans-serif', '11px ui-sans-serif, system-ui, sans-serif']);
  });

  it.each([['left', 180], ['center', 200], ['right', 220]] as const)('aligns multiline rows %s without moving the plate', (textAlign, x) => {
    const h = draw([{ kind: 'label', at: at(200, 100), text: 'a\nBBBB', fontSize: 20, textAlign }]);
    expect(plate(h.rec.ops).args.slice(0, 4)).toEqual([175, 70, 50, 60]);
    expect(texts(h.rec.ops).map(op => op.args[0])).toEqual([x, x]);
  });

  it('measures styled labels before culling and clips their painted and hit bounds to the plot', () => {
    const h = draw([{ kind: 'label', at: at(-250, 100), text: 'AAAAAAAAAA', fontSize: 60, align: 'left', id: 'wide' }]);
    expect(texts(h.rec.ops)).toHaveLength(1);
    expect(h.rec.ops.some(op => op.type === 'clip')).toBe(true);
    expect(h.primitive.hitTest(5, 100)?.externalId).toBe('wide');
    expect(h.primitive.hitTest(-1, 100)).toBeNull();
  });

  it('keeps the legacy caption overflow relative to the box while adding a plot clip', () => {
    const h = draw([{ kind: 'box', from: at(100, 100), to: at(110, 110), text: 'BBBB', fontSize: 20 }]);
    expect(plate(h.rec.ops).args[2]).toBe(50);
    expect(h.rec.ops.some(op => op.type === 'rect' && op.args.join() === '0,0,400,300')).toBe(true);
  });

  it.each(['replace', 'hide', 'detach'] as const)('clears measured label hits immediately on %s', action => {
    const h = draw([{ kind: 'label', at: at(200, 100), text: 'Old', id: 'old', fontSize: 20 }]);
    expect(h.primitive.hitTest(200, 100)?.externalId).toBe('old');
    if (action === 'replace') h.primitive.setItems([]);
    else if (action === 'hide') h.primitive.setVisible(false);
    else h.primitive.detached();
    expect(h.primitive.hitTest(200, 100)).toBeNull();
  });

  it('serializes the requested typography and literal text through strict SVG, restoring incoming state', () => {
    const primitive = new IndicatorDrawings();
    primitive.setItems([{ kind: 'label', at: at(200, 100), text: '<A>&B', fontSize: 20, bold: true,
      italic: true, fontFamily: 'ui-monospace, monospace', textColor: '#123456' } as Drawing]);
    const svg = new SvgContext(400, 300, { strict: true }); svg.font = '13px serif'; svg.fillStyle = '#abcdef';
    primitive.draw(svg.asCanvasContext(), drawingsRc());
    expect(svg.font).toBe('13px serif'); expect(svg.fillStyle).toBe('#abcdef');
    const output = svg.toString();
    expect(output).toContain('font-size="20"'); expect(output).toContain('font-weight="600"');
    expect(output).toContain('font-style="italic"'); expect(output).toContain('font-family="ui-monospace, monospace"');
    expect(output).toContain('&lt;A&gt;&amp;B');
  });

  it.each([0, -1, Infinity, NaN, '20'])('rejects fontSize %s atomically', value => {
    const h = draw([{ kind: 'label', at: at(200, 100), text: 'Old', id: 'old' }]);
    expect(() => h.primitive.setItems([{ kind: 'label', at: at(200, 100), text: 'Bad', fontSize: value } as unknown as Drawing])).toThrow();
    expect(h.primitive.hitTest(200, 100)?.externalId).toBe('old');
    const next = recorder(); h.primitive.draw(next.ctx, drawingsRc()); expect(texts(next.rec.ops).map(op => op.text)).toEqual(['Old']);
  });

  it.each([{ fontFamily: '' }, { fontFamily: 20 }, { bold: 'yes' }, { italic: 1 }, { textAlign: 'end' }, { verticalAlign: 'center' }])('rejects malformed new fields %j', patch => {
    const h = draw([{ kind: 'label', at: at(200, 100), text: 'Old', id: 'old' }]);
    expect(() => h.primitive.setItems([{ kind: 'label', at: at(200, 100), text: 'Bad', ...patch } as unknown as Drawing])).toThrow();
    expect(h.primitive.hitTest(200, 100)?.externalId).toBe('old');
  });
});

describe('independent marker text typography', () => {
  it('preserves default fonts and contrasting versus matching ink', () => {
    const h = markerFixture(), c = recorder();
    h.primitive.setMarkers([marker({ shape: 'labelUp', text: 'One' }), marker({ text: 'Two' })]); h.primitive.draw(c.ctx, h.rc);
    expect(texts(c.rec.ops).map(op => op.font)).toEqual(['600 12px system-ui, sans-serif', '12px system-ui, sans-serif']);
    expect(texts(c.rec.ops)[1].fillStyle).toBe('#e14b64'); expect(texts(c.rec.ops)[0].fillStyle).not.toBe('#e14b64');
  });

  it.each(['circle', 'labelUp', 'labelDown', 'text'] as const)('styles %s text independently from its shape', shape => {
    const h = markerFixture(), c = recorder();
    h.primitive.setMarkers([marker({ shape, fontSize: 18, fontFamily: 'ui-monospace, monospace', bold: true, italic: true, textColor: '#123456' })]);
    h.primitive.draw(c.ctx, h.rc);
    const ops = texts(c.rec.ops);
    expect(ops.every(op => op.font === 'italic 600 18px ui-monospace, monospace')).toBe(true);
    expect(ops.every(op => op.fillStyle === '#123456')).toBe(true);
    expect(Math.abs(ops[1].args[1] - ops[0].args[1])).toBeCloseTo(24.3);
    if (shape !== 'text') expect(c.rec.ops.some(op => op.type === 'fill' && op.fillStyle === '#e14b64')).toBe(true);
  });

  it('lets a plate marker explicitly opt out of its semibold default', () => {
    const h = markerFixture(), c = recorder(); h.primitive.setMarkers([marker({ shape: 'labelUp', bold: false })]);
    h.primitive.draw(c.ctx, h.rc); expect(texts(c.rec.ops)[0].font).toBe('12px system-ui, sans-serif');
  });

  it.each([['left', -18], ['center', 0], ['right', 18]] as const)('aligns marker rows %s inside the measured block', (textAlign, offset) => {
    const h = markerFixture(), c = recorder(); h.primitive.setMarkers([marker({ fontSize: 18, textAlign })]);
    h.primitive.draw(c.ctx, h.rc);
    expect(texts(c.rec.ops).map(op => op.args[0])).toEqual([h.rc.timeScale.indexToX(0) + offset, h.rc.timeScale.indexToX(0) + offset]);
  });

  it('uses actual font and size at fractional DPR and restores SVG context', () => {
    const h = markerFixture(1.5), c = recorder();
    h.primitive.setMarkers([marker({ shape: 'labelUp', fontSize: 18, italic: true, textColor: '#abcdef' })]); h.primitive.draw(c.ctx, h.rc);
    expect(texts(c.rec.ops).every(op => op.font === 'italic 600 27px system-ui, sans-serif')).toBe(true);
    const svg = new SvgContext(600, 450, { strict: true }); svg.font = '13px serif';
    h.primitive.draw(svg.asCanvasContext(), h.rc);
    expect(svg.toString()).toContain('font-size="27"'); expect(svg.toString()).toContain('font-style="italic"');
    expect(svg.toString()).toContain('fill="#abcdef"'); expect(svg.font).toBe('13px serif');
  });

  it('clips styled marker ink and rejects hits outside its plot', () => {
    const h = markerFixture(), c = recorder();
    h.rc.plotWidth = h.rc.timeScale.indexToX(0) + 2;
    h.primitive.setMarkers([marker({ position: 'paneTop', fontSize: 40, textColor: '#abcdef' })]);
    h.primitive.draw(c.ctx, h.rc);
    expect(c.rec.ops.some(op => op.type === 'clip')).toBe(true);
    expect(h.primitive.hitTest(h.rc.timeScale.indexToX(0) + 7, 10)).toBeNull();
  });

  it.each(['replace', 'detach'] as const)('clears marker hits immediately on %s', action => {
    const h = markerFixture(), c = recorder(); h.primitive.setMarkers([marker({ fontSize: 20 })]); h.primitive.draw(c.ctx, h.rc);
    const x = h.rc.timeScale.indexToX(0), y = h.rc.priceScale.priceToY(10);
    expect(h.primitive.hitTest(x, y)?.externalId).toBe('event');
    if (action === 'replace') h.primitive.setMarkers([]); else h.primitive.detached();
    expect(h.primitive.hitTest(x, y)).toBeNull();
  });

  it('keeps the glyph anchor and shape size independent of text size', () => {
    const h = markerFixture(), normal = recorder(), large = recorder();
    h.primitive.setMarkers([marker()]); h.primitive.draw(normal.ctx, h.rc);
    h.primitive.setMarkers([marker({ fontSize: 30 })]); h.primitive.draw(large.ctx, h.rc);
    expect(large.rec.ops.filter(op => op.type === 'arc')).toEqual(normal.rec.ops.filter(op => op.type === 'arc'));
    expect(texts(large.rec.ops)[0].font).toBe('30px system-ui, sans-serif');
  });

  it('rejects malformed new text properties before replacing accepted markers', () => {
    const h = markerFixture(), c = recorder(); h.primitive.setMarkers([marker({ text: 'Old' })]);
    expect(() => h.primitive.setMarkers([marker({ text: 'Bad', fontFamily: '  ' })])).toThrow();
    h.primitive.draw(c.ctx, h.rc); expect(texts(c.rec.ops).map(op => op.text)).toEqual(['Old']);
  });

  it.each([undefined, 'Text'])('keeps the glyph and hit when only text size overflows (%s)', text => {
    const h = markerFixture(2), expected = recorder(), actual = recorder();
    h.primitive.setMarkers([marker({ text: undefined })]); h.primitive.draw(expected.ctx, h.rc);
    h.primitive.setMarkers([marker({ fontSize: 1e308, text })]); h.primitive.draw(actual.ctx, h.rc);
    expect(actual.rec.ops.filter(op => op.type === 'arc')).toEqual(expected.rec.ops.filter(op => op.type === 'arc'));
    expect(texts(actual.rec.ops)).toHaveLength(0);
    expect(h.primitive.hitTest(h.rc.timeScale.indexToX(0), h.rc.priceScale.priceToY(10))?.externalId).toBe('event');
  });

  it('keeps a glyph when finite text size produces nonfinite measured bounds', () => {
    const h = markerFixture(), c = recorder();
    h.primitive.setMarkers([marker({ fontSize: 1e308 })]); h.primitive.draw(c.ctx, h.rc);
    expect(c.rec.ops.filter(op => op.type === 'arc')).toHaveLength(1);
    expect(texts(c.rec.ops)).toHaveLength(0);
    expect(h.primitive.hitTest(h.rc.timeScale.indexToX(0), h.rc.priceScale.priceToY(10))?.externalId).toBe('event');
  });
});
