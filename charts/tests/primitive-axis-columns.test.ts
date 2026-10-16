import { describe, expect, it } from 'vitest';
import { DataLayer } from '../src/model/data-layer';
import { PriceLine } from '../src/primitives/price-line';
import { PriceLevels } from '../src/primitives/price-levels';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { SvgContext } from '../src/render/svg-export';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import { RecordingContext } from './helpers/fake-ctx';

type ColumnContext = PrimitiveRenderContext & { priceAxisOffset?: number };

class FontContext extends RecordingContext {
  public override measureText(text: string) {
    return { width: text.length * Number(this.font.split(' ').find(part => part.endsWith('px'))?.slice(0, -2) ?? 10) * 0.6 };
  }
}

function context(patch: Partial<ColumnContext> = {}): ColumnContext {
  const dataLayer = new DataLayer(), timeScale = new TimeScale(), priceScale = new PriceScale();
  const bars = [{ time: 100, open: 20, high: 30, low: 10, close: 25 }];
  dataLayer.setSeriesData(dataLayer.createSeries(), bars);
  timeScale.setWidth(600);
  timeScale.setBaseIndex(0);
  priceScale.setOptions({ marginTop: 0, marginBottom: 0 });
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 0, max: 100 });
  return { dataLayer, timeScale, priceScale, bars: () => bars, dpr: 1, theme: darkTheme,
    plotWidth: 600, plotHeight: 400, priceAxisWidth: 60, ...patch };
}

function primitive(kind: 'line' | 'levels', label = 'Outer column level') {
  return kind === 'line'
    ? new PriceLine({ id: 'level', price: 25, color: '#cc4477', label, cursor: 'ns-resize' })
    : new PriceLevels({ levels: {
      previousClose: { line: false, label: false },
      lastPrice: { line: true, label: true, text: label, color: '#cc4477' },
    } });
}

describe.each(['line', 'levels'] as const)('%s primitive axis columns', kind => {
  it.each([
    ['left', -60, -120, -60, 1], ['right', 660, 660, 720, 1],
    ['left', -60, -180, -90, 1.5], ['right', 660, 990, 1080, 1.5],
    ['left', -60, -240, -120, 2], ['right', 660, 1320, 1440, 2],
  ] as const)('fits the outer %s column at offset %s inside [%s, %s] at dpr %s', (side, offset, low, high, dpr) => {
    const rc = context({ priceAxisSide: side, priceAxisOffset: offset, dpr });
    const rec = new FontContext();
    primitive(kind).draw(rec as unknown as CanvasRenderingContext2D, rc);

    const tag = rec.ops.find(op => op.type === 'fillRect')!;
    expect(tag).toBeDefined();
    expect(tag.args[0]).toBeGreaterThanOrEqual(low);
    expect(tag.args[0] + tag.args[2]).toBeLessThanOrEqual(high);
    const text = rec.ops.find(op => op.text === 'Outer column level')!;
    const size = Number(/([\d.]+)px/.exec(text.font!)?.[1]);
    expect(text.args[0]).toBeGreaterThanOrEqual(low);
    expect(text.args[0] + text.text!.length * size * 0.6).toBeLessThanOrEqual(high);
    expect(rec.ops.some(op => op.type === 'rect' && op.args.join(',') === [low, 0, high - low, 400 * dpr].join(','))).toBe(true);
    expect(rec.ops.find(op => op.type === 'moveTo')?.args).toEqual([0, 300 * dpr + 0.5]);
    expect(rec.ops.find(op => op.type === 'lineTo')?.args).toEqual([600 * dpr, 300 * dpr + 0.5]);
    expect(rec.count('translate')).toBe(0);
  });

  it.each([['hidden', 60], ['left', 0], ['right', 0]] as const)('omits %s labels with width %s while retaining the plot stroke', (side, width) => {
    const rec = new FontContext();
    primitive(kind).draw(rec as unknown as CanvasRenderingContext2D,
      context({ priceAxisSide: side, priceAxisWidth: width, priceAxisOffset: 660 }));
    expect(rec.ops.some(op => op.text === 'Outer column level')).toBe(false);
    expect(rec.count('fillRect')).toBe(0);
    expect(rec.ops.find(op => op.type === 'moveTo')?.args).toEqual([0, 300.5]);
    expect(rec.ops.find(op => op.type === 'lineTo')?.args).toEqual([600, 300.5]);
  });

  it('retains legacy right geometry when the optional offset is absent', () => {
    const rec = new FontContext();
    primitive(kind, '25').draw(rec as unknown as CanvasRenderingContext2D, context());
    expect(rec.ops.find(op => op.type === 'fillRect')?.args).toEqual(kind === 'line'
      ? [601, 291.5, 25.2, 18] : [601, 292.5, 25.2, 16]);
    expect(rec.ops.find(op => op.text === '25')?.args).toEqual([607, 300.5]);
    expect(rec.count('clip')).toBe(0);
  });

  it('uses rounded column endpoints at a fractional outer-left origin', () => {
    const rec = new FontContext();
    primitive(kind).draw(rec as unknown as CanvasRenderingContext2D,
      context({ priceAxisSide: 'left', priceAxisOffset: -60.2, priceAxisWidth: 60.4, dpr: 1.5 }));
    expect(rec.ops.find(op => op.type === 'rect')?.args).toEqual([-181, 0, 91, 600]);
    const tag = rec.ops.find(op => op.type === 'fillRect')!;
    expect(tag.args[0]).toBeGreaterThanOrEqual(-181);
    expect(tag.args[0] + tag.args[2]).toBeLessThanOrEqual(-90);
  });

  it.each([['left', -60, -120], ['right', 660, 660]] as const)('serializes the outer %s column through strict SVG and restores context state', (side, offset, low) => {
    const svg = new SvgContext(840, 400, { strict: true });
    const canvas = svg.asCanvasContext();
    canvas.font = '17px serif';
    canvas.fillStyle = '#123456';
    canvas.save();
    canvas.translate(120, 0);
    primitive(kind).draw(canvas, context({ priceAxisSide: side, priceAxisOffset: offset }));
    expect(canvas.font).toBe('17px serif');
    expect(canvas.fillStyle).toBe('#123456');
    canvas.restore();
    const output = svg.toString();
    expect(svg.unsupported).toEqual([]);
    expect(output).toContain('Outer column level');
    expect(output).toContain(`<path d="M${low} 0h60v400h-60Z"/>`);
    expect(output).toContain('clip-path=');
  });
});

it('moves only the PriceLine axis tag while retaining plot labels and hit coordinates', () => {
  const line = new PriceLine({ id: 'level', price: 25, color: '#cc4477', label: 'AXIS', leftLabel: 'PLOT', cursor: 'ns-resize' });
  const plain = context(), moved = context({ priceAxisSide: 'right', priceAxisOffset: 660 });
  const first = new FontContext(), second = new FontContext();
  line.draw(first as unknown as CanvasRenderingContext2D, plain);
  const hit = line.hitTest(200, 300, plain);
  line.draw(second as unknown as CanvasRenderingContext2D, moved);
  expect(second.ops.find(op => op.text === 'PLOT')).toEqual(first.ops.find(op => op.text === 'PLOT'));
  expect(line.hitTest(200, 300, moved)).toEqual(hit);
  expect(hit?.externalId).toBe('level');
  expect(line.hitTest(680, 300, moved)).toBeNull();
});

it('preserves omitted-offset left fitting at a half-pixel column width', () => {
  const rec = new FontContext();
  primitive('line').draw(rec as unknown as CanvasRenderingContext2D,
    context({ priceAxisSide: 'left', priceAxisWidth: 60.5 }));
  expect(rec.ops.find(op => op.type === 'fillRect')?.args).toEqual([-61, 291.5, 60, 18]);
  expect(rec.count('clip')).toBe(0);
});
