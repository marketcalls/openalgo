/**
 * A working order's and a position's price tag follow the price axis the
 * way a PriceLine's does: into the column the scale is bound to, left or
 * right, confined to that column, and left out when the scale has no axis.
 * A context that says nothing of placement keeps the right-edge tag both
 * always drew.
 */
import { describe, expect, it } from 'vitest';
import { DataLayer } from '../src/model/data-layer';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import { PositionMarker } from '../src/trade/position';
import { WorkingOrderLine } from '../src/trade/order-line';
import type { Order, Position } from '../src/trade/types';
import { RecordingContext } from './helpers/fake-ctx';

class FontContext extends RecordingContext {
  public override measureText(text: string) {
    return { width: text.length * Number(this.font.split(' ').find(part => part.endsWith('px'))?.slice(0, -2) ?? 10) * 0.6 };
  }
}

function context(patch: Partial<PrimitiveRenderContext> = {}): PrimitiveRenderContext {
  const dataLayer = new DataLayer(), timeScale = new TimeScale(), priceScale = new PriceScale();
  timeScale.setWidth(600);
  priceScale.setOptions({ marginTop: 0, marginBottom: 0 });
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 0, max: 100 });
  return { dataLayer, timeScale, priceScale, dpr: 1, theme: darkTheme, plotWidth: 600, plotHeight: 400, priceAxisWidth: 60, ...patch };
}

const order: Order = { id: 'o1', symbol: 'INFY', side: 'BUY', type: 'LIMIT', qty: 10, filledQty: 0, price: 25, status: 'working' };
const position: Position = { symbol: 'INFY', netQty: 10, avgPrice: 25 };

/** The price tag: the fill behind the price and the price written on it. */
function tag(kind: 'order' | 'position', rc: PrimitiveRenderContext): { rect?: number[]; text?: number[] } {
  const rec = new FontContext();
  (kind === 'order' ? new WorkingOrderLine(order) : new PositionMarker(position)).draw(rec as unknown as CanvasRenderingContext2D, rc);
  const label = rc.priceScale.format(25);
  return { rect: rec.ops.find(op => op.type === 'fillRect')?.args, text: rec.ops.find(op => op.type === 'fillText' && op.text === label)?.args };
}

describe.each(['order', 'position'] as const)('the %s price tag', kind => {
  it.each([
    ['left', -60, -120, -60, 1], ['right', 660, 660, 720, 1],
    ['left', -60, -180, -90, 1.5], ['right', 660, 990, 1080, 1.5],
  ] as const)('sits in the outer %s column at offset %s, inside [%s, %s] at dpr %s', (side, offset, low, high, dpr) => {
    const { rect, text } = tag(kind, context({ priceAxisSide: side, priceAxisOffset: offset, dpr }));
    expect(rect).toBeDefined();
    expect(rect![0]).toBeGreaterThanOrEqual(low);
    expect(rect![0]! + rect![2]!).toBeLessThanOrEqual(high);
    expect(text![0]).toBeGreaterThanOrEqual(low);
  });

  it('sits in a left axis with no offset, against the plot edge', () => {
    const { rect, text } = tag(kind, context({ priceAxisSide: 'left', priceAxisWidth: 60 }));
    expect(rect![0]! + rect![2]!).toBeLessThanOrEqual(-1);
    expect(rect![0]).toBeGreaterThanOrEqual(-60);
    expect(text![0]).toBeLessThan(0);
  });

  it('is left out when the scale has no axis column', () => {
    expect(tag(kind, context({ priceAxisSide: 'hidden', priceAxisWidth: 0 }))).toEqual({ rect: undefined, text: undefined });
  });

  it('keeps the right-edge tag on a context that says nothing of placement', () => {
    const { rect, text } = tag(kind, context());
    expect(rect).toEqual([601, 291.5, 25.2, 18]);
    expect(text).toEqual([607, 300.5]);
  });
});
