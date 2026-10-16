import { describe, expect, it } from 'vitest';
import { Pane, type PaneRenderContext } from '../src/core/pane';
import { DataLayer } from '../src/model/data-layer';
import { createSeriesRecord, type PriceScaleId } from '../src/model/series';
import { PriceLine } from '../src/primitives/price-line';
import type { IPrimitive, PrimitiveRenderContext, ZOrder } from '../src/primitives/primitive';
import { SvgContext } from '../src/render/svg-export';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import { fakeDocument } from './helpers/fake-dom';
import { RecordingContext } from './helpers/fake-ctx';

const host = { requestUpdate() {} };

function fixture() {
  const pane = new Pane(fakeDocument()), dataLayer = new DataLayer(), timeScale = new TimeScale();
  pane.resize(730, 400, 1);
  timeScale.setWidth(600);
  const context: PaneRenderContext = { dataLayer, timeScale, dpr: 1, leftAxisWidth: 70, priceAxisWidth: 60,
    timeAxisHeight: 0, showTimeAxis: false, conflate: false, conflationFactor: 1, theme: darkTheme,
    showVertGrid: false, showHorzGrid: false };
  for (const [id, min, max] of [['right', 0, 100], ['left', 100, 200], ['', 200, 300], ['overlay:test', 1000, 2000]] as const) {
    const scale = pane.scaleFor(id);
    scale.setOptions({ marginTop: 0, marginBottom: 0 });
    scale.setAutoScale(false); scale.setPriceRange({ min, max }); scale.setHeight(400);
    scale.setPriceFormatter(value => `${id || 'hidden'}:${value}`);
  }
  return { pane, context };
}

class Probe implements IPrimitive {
  public seen: PrimitiveRenderContext[] = [];
  public attachments = 0;
  public detachments = 0;
  public get lastContext(): PrimitiveRenderContext | undefined { return this.seen[this.seen.length - 1]; }
  public constructor(private readonly layer: ZOrder = 'normal', public price = 125) {}
  public zOrder(): ZOrder { return this.layer; }
  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this.seen.push(rc); ctx.fillRect(10, rc.priceScale.priceToY(this.price), 5, 5);
  }
  public hitTest(_x: number, y: number, rc: PrimitiveRenderContext) {
    return Math.abs(y - rc.priceScale.priceToY(this.price)) < 1
      ? { externalId: 'probe', zOrder: this.layer, distance: 0 } : null;
  }
  public autoscaleInfo() { return { min: this.price, max: this.price + 10 }; }
  public attached(): void { this.attachments++; }
  public detached(): void { this.detachments++; }
}

function paint(pane: Pane, context: PaneRenderContext): RecordingContext {
  const recorder = new RecordingContext(), canvas = recorder as unknown as CanvasRenderingContext2D;
  pane.paintBase(context, canvas); pane.paintTop(null, context, canvas);
  return recorder;
}

describe('primitive scale binding', () => {
  it.each(['bottom', 'normal', 'top'] as const)('routes %s drawing, hit-testing and SVG through the bound scale', layer => {
    const { pane, context } = fixture(), primitive = new Probe(layer);
    pane.addPrimitive(primitive, host);
    expect(pane.bindPrimitiveScale(primitive, 'left')).toBe(true);
    const rec = paint(pane, context);
    expect(rec.ops.some(op => op.type === 'fillRect' && op.args.join(',') === '10,300,5,5')).toBe(true);
    expect(primitive.lastContext).toMatchObject({ priceScale: pane.scaleFor('left'), priceAxisSide: 'left', priceAxisWidth: 70 });
    expect(pane.hitTestPrimitives(10, 300, context)?.externalId).toBe('probe');
    expect(pane.hitTestPrimitives(10, pane.priceScale.priceToY(125), context)).toBeNull();
    const svg = new SvgContext(730, 400, { strict: true }), canvas = svg as unknown as CanvasRenderingContext2D;
    pane.paintBase(context, canvas); pane.paintTop(null, context, canvas);
    expect(svg.toString()).toContain('y="300"');
    expect(primitive.lastContext?.priceScale).toBe(pane.scaleFor('left'));
  });

  it.each(['', 'overlay:test'] as const)('binds hidden scale %s without an axis column', id => {
    const { pane, context } = fixture(), primitive = new Probe('normal', id === '' ? 250 : 1500);
    pane.addPrimitive(primitive, host); pane.bindPrimitiveScale(primitive, id);
    paint(pane, context);
    expect(primitive.lastContext).toMatchObject({ priceScale: pane.scaleFor(id), priceAxisSide: 'hidden', priceAxisWidth: 0 });
    expect(pane.hitTestPrimitives(10, 200, context)?.externalId).toBe('probe');
  });

  it('restores the original right-scale context when the explicit binding is removed', () => {
    const { pane, context } = fixture(), primitive = new Probe();
    pane.addPrimitive(primitive, host); paint(pane, context);
    const original = primitive.lastContext!;
    expect(original).toMatchObject({ priceScale: pane.priceScale, priceAxisSide: 'right', priceAxisWidth: 60 });
    pane.bindPrimitiveScale(primitive, 'left');
    expect(pane.bindPrimitiveScale(primitive, null)).toBe(true);
    paint(pane, context);
    expect(primitive.lastContext).toMatchObject({ priceScale: original.priceScale, priceAxisSide: 'right', priceAxisWidth: 60 });
    expect(pane.primitiveScaleId(primitive)).toBeNull();
  });

  it('validates binding ownership and identifiers without creating scales', () => {
    const { pane } = fixture(), primitive = new Probe(), foreign = new Probe();
    pane.addPrimitive(primitive, host);
    expect(pane.bindPrimitiveScale(foreign, 'overlay:new')).toBe(false);
    expect(pane.bindPrimitiveScale(primitive, null)).toBe(false);
    const before = pane.scales();
    for (const id of [undefined, 7, {}, 'unknown']) expect(pane.bindPrimitiveScale(primitive, id as PriceScaleId)).toBe(false);
    expect(pane.scales()).toEqual(before);
    expect(pane.bindPrimitiveScale(primitive, 'right')).toBe(true);
    expect(pane.bindPrimitiveScale(primitive, 'right')).toBe(false);
    expect(pane.primitiveScaleId(foreign)).toBeNull();
  });

  it('measures primitive-only left and hidden scales independently from unbound right primitives', () => {
    const { pane, context } = fixture();
    for (const scale of pane.scales()) scale.setAutoScale(true);
    for (const [id, price] of [[null, 10], ['left', 100], ['overlay:test', 1000], ['', 2000]] as const) {
      const primitive = new Probe('normal', price);
      pane.addPrimitive(primitive, host);
      if (id !== null) pane.bindPrimitiveScale(primitive, id);
    }
    pane.autoscale(context);
    for (const [id, min] of [['right', 10], ['left', 100], ['overlay:test', 1000], ['', 2000]] as const) {
      expect(pane.scaleFor(id).priceRange()).toEqual({ min, max: min + 10 });
    }
    expect(pane.hasLeftScale()).toBe(true);
    expect(pane.usesScale('left')).toBe(true);
    expect(pane.usesScale('right')).toBe(false);
  });

  it('keeps a configured named scale alive after its last series is removed while a primitive remains bound', () => {
    const { pane } = fixture(), primitive = new Probe();
    const record = createSeriesRecord(1, 'line', {}, 'overlay:test'), target = pane.scaleFor('overlay:test');
    pane.addSeries(record); pane.addPrimitive(primitive, host); pane.bindPrimitiveScale(primitive, 'overlay:test');
    pane.removeSeries(record);
    expect(pane.scaleFor('overlay:test')).toBe(target);
    expect(target.priceRange()).toEqual({ min: 1000, max: 2000 });
  });

  it('transfers bindings without detach and resolves the target pane configuration', () => {
    const { pane: source } = fixture(), { pane: target, context } = fixture(), primitive = new Probe();
    source.addPrimitive(primitive, host); source.bindPrimitiveScale(primitive, 'left');
    target.scaleFor('left').setPriceRange({ min: 0, max: 500 });
    expect(source.transferPrimitive(primitive, target)).toBe(true);
    expect(source.primitiveScaleId(primitive)).toBeNull();
    expect(target.primitiveScaleId(primitive)).toBe('left');
    expect(source.hasLeftScale()).toBe(false); expect(target.hasLeftScale()).toBe(true);
    paint(target, context);
    expect(primitive.lastContext?.priceScale).toBe(target.scaleFor('left'));
    expect(primitive.attachments).toBe(1); expect(primitive.detachments).toBe(0);
    expect(target.transferPrimitive(primitive, target)).toBe(false);
    source.destroy();
    expect(target.transferPrimitive(primitive, source)).toBe(false);
    expect(target.hasPrimitive(primitive)).toBe(true);
  });

  it('clears bindings on remove and destroy, before lifecycle callbacks run', () => {
    const { pane } = fixture(), primitive = new Probe();
    let detachedBinding: PriceScaleId | null | undefined;
    primitive.detached = () => { detachedBinding = pane.primitiveScaleId(primitive); };
    pane.addPrimitive(primitive, host); pane.bindPrimitiveScale(primitive, 'left');
    pane.removePrimitive(primitive);
    expect(detachedBinding).toBeNull(); expect(pane.bindPrimitiveScale(primitive, 'left')).toBe(false);
    pane.addPrimitive(primitive, host); expect(pane.primitiveScaleId(primitive)).toBeNull();
    pane.bindPrimitiveScale(primitive, 'left'); detachedBinding = undefined;
    pane.destroy(); expect(detachedBinding).toBeNull();
    expect(pane.primitiveScaleId(primitive)).toBeNull(); expect(pane.bindPrimitiveScale(primitive, 'left')).toBe(false);
  });

  it('moves explicit axis bindings with their scale and preserves unbound right behavior', () => {
    const { pane, context } = fixture(), bound = new Probe('normal', 25), unbound = new Probe('normal', 25);
    pane.addPrimitive(bound, host); pane.addPrimitive(unbound, host); pane.bindPrimitiveScale(bound, 'right');
    const moving = pane.priceScale;
    expect(pane.moveSeriesScale('right', 'left')).toBe(true);
    expect(pane.primitiveScaleId(bound)).toBe('left'); expect(pane.primitiveScaleId(unbound)).toBeNull();
    paint(pane, context);
    expect(bound.lastContext?.priceScale).toBe(moving); expect(unbound.lastContext?.priceScale).toBe(pane.priceScale);
    expect(pane.priceScale).not.toBe(moving);
  });

  it('rejects an axis move into a scale occupied by an explicitly bound primitive', () => {
    const { pane } = fixture(), first = new Probe(), second = new Probe();
    pane.addSeries(createSeriesRecord(1, 'line', {}, 'right'));
    pane.addPrimitive(first, host); pane.addPrimitive(second, host);
    pane.bindPrimitiveScale(first, 'right'); pane.bindPrimitiveScale(second, 'left');
    const right = pane.priceScale;
    expect(pane.moveSeriesScale('right', 'left')).toBe(false);
    expect(pane.priceScale).toBe(right); expect(pane.primitiveScaleId(first)).toBe('right');
  });
});

describe('price-line axis placement', () => {
  it.each([100, 200])('keeps a left pill inside the pane when its price is at edge %s', price => {
    const { pane, context } = fixture(), line = new PriceLine({ id: 'edge', price, color: '#cc4477' });
    const rc: PrimitiveRenderContext = { ...context, priceScale: pane.scaleFor('left'), priceAxisSide: 'left',
      priceAxisWidth: 70, plotWidth: 600, plotHeight: 400 };
    const recorder = new RecordingContext(); line.draw(recorder as unknown as CanvasRenderingContext2D, rc);
    const tag = recorder.ops.find(op => op.type === 'fillRect');
    expect(tag).toBeDefined();
    expect(tag!.args[1]).toBeGreaterThanOrEqual(0);
    expect(tag!.args[1] + tag!.args[3]).toBeLessThanOrEqual(400);
  });

  it.each([1, 2])('fits left price text within its column at dpr %s without changing the plot line or label', dpr => {
    const { pane, context } = fixture(), line = new PriceLine({ id: 'level', price: 125, color: '#cc4477', label: 'A long level label', leftLabel: 'LEVEL' });
    const rc: PrimitiveRenderContext = { ...context, priceScale: pane.scaleFor('left'), priceAxisSide: 'left',
      priceAxisWidth: 70, plotWidth: 600, plotHeight: 400, dpr };
    class FontContext extends RecordingContext {
      public override measureText(text: string) { return { width: text.length * Number(this.font.split(' ').find(part => part.endsWith('px'))?.slice(0, -2) ?? 10) * 0.6 }; }
    }
    const recorder = new FontContext(); line.draw(recorder as unknown as CanvasRenderingContext2D, rc);
    const tag = recorder.ops.find(op => op.type === 'fillRect')!;
    expect(tag.args[0]).toBeGreaterThanOrEqual(-70 * dpr);
    expect(tag.args[0] + tag.args[2]).toBeLessThanOrEqual(0);
    const text = recorder.ops.find(op => op.text === 'A long level label')!;
    const fontSize = Number(/([\d.]+)px/.exec(text.font!)?.[1]);
    expect(text.args[0]).toBeGreaterThanOrEqual(tag.args[0]);
    expect(text.args[0] + text.text!.length * fontSize * 0.6).toBeLessThanOrEqual(tag.args[0] + tag.args[2]);
    expect(recorder.ops.some(op => op.text === 'LEVEL')).toBe(true);
    expect(recorder.ops.find(op => op.type === 'moveTo')?.args).toEqual([0, 300 * dpr + 0.5]);
    expect(line.hitTest(200, 300, rc)?.externalId).toBe('level');
  });

  it('omits hidden and missing-column price pills while preserving the line and plot label', () => {
    const { pane, context } = fixture(), line = new PriceLine({ id: 'level', price: 125, color: '#cc4477', leftLabel: 'LEVEL' });
    for (const side of ['hidden', 'left'] as const) {
      const rc: PrimitiveRenderContext = { ...context, priceScale: pane.scaleFor('left'), priceAxisSide: side,
        priceAxisWidth: 0, plotWidth: 600, plotHeight: 400 };
      const recorder = new RecordingContext(); line.draw(recorder as unknown as CanvasRenderingContext2D, rc);
      expect(recorder.ops.filter(op => op.type === 'fillRect')).toEqual([]);
      expect(recorder.ops.some(op => op.text === 'LEVEL')).toBe(true);
      expect(recorder.ops.some(op => op.type === 'stroke')).toBe(true);
      expect(line.hitTest(200, 300, rc)?.externalId).toBe('level');
    }
  });

  it('keeps the right price pill identical when optional placement is omitted', () => {
    const { pane, context } = fixture(), line = new PriceLine({ id: 'level', price: 25, color: '#cc4477', leftLabel: 'LEVEL' });
    const rc: PrimitiveRenderContext = { ...context, priceScale: pane.priceScale, plotWidth: 600, plotHeight: 400 };
    const first = new RecordingContext(), second = new RecordingContext();
    line.draw(first as unknown as CanvasRenderingContext2D, rc);
    line.draw(second as unknown as CanvasRenderingContext2D, { ...rc, priceAxisSide: 'right' });
    expect(second.ops).toEqual(first.ops);
  });
});
