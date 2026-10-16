/**
 * Hardening: what the trade controller is allowed to leave off the chart.
 *
 * Two display defects, both trading defects rather than cosmetic ones on a chart
 * that also carries Buy and Sell buttons:
 *   1. a working stop was skipped by the order lines and, whenever no bracket
 *      formed, drew nothing at all. A trader who cannot see a stop believes
 *      there is none.
 *   2. a one-sided bracket filled the missing leg with the position average, so
 *      a take-profit line appeared at a price where no order rested.
 */
import { describe, it, expect } from 'vitest';
import { TradeController, type TradeHost } from '../src/trade/trade-controller';
import { WorkingOrderLine } from '../src/trade/order-line';
import { PositionMarker } from '../src/trade/position';
import { BracketGroup } from '../src/trade/bracket';
import type { Order, Position } from '../src/trade/types';
import type { IPrimitive, PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';
import { makeCtx, type Op } from './helpers/fake-ctx';

const SYMBOL = 'RELIANCE';

const order = (id: string, o: Partial<Order> = {}): Order => ({
  id, symbol: SYMBOL, side: 'BUY', type: 'LIMIT', qty: 10, filledQty: 0, price: 100, status: 'working', ...o,
});
const stopOrder = (id = 'sl1', trigger = 95): Order =>
  order(id, { role: 'sl', side: 'SELL', type: 'SL-M', price: 0, triggerPrice: trigger });
const targetOrder = (id = 'tp1', price = 110): Order =>
  order(id, { role: 'tp', side: 'SELL', type: 'LIMIT', price });
const pos = (netQty: number, avgPrice: number): Position => ({ symbol: SYMBOL, netQty, avgPrice });

class RecordingHost implements TradeHost {
  public added: IPrimitive[] = [];
  public removed: IPrimitive[] = [];
  public addPrimitive(p: IPrimitive): void { this.added.push(p); }
  public removePrimitive(p: IPrimitive): void { this.removed.push(p); }
  public live(): IPrimitive[] { return this.added.filter((p) => !this.removed.includes(p)); }
  public lines(): WorkingOrderLine[] { return this.live().filter((p): p is WorkingOrderLine => p instanceof WorkingOrderLine); }
  public brackets(): BracketGroup[] { return this.live().filter((p): p is BracketGroup => p instanceof BracketGroup); }
}

function renderContext(): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 80, max: 120 }); // measured: without this every y is 0
  const timeScale = new TimeScale();
  timeScale.setWidth(600);
  return {
    timeScale, priceScale, dataLayer: new DataLayer(),
    plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme,
  };
}

/** Every op every live primitive paints in one frame, so "invisible" is assertable. */
function paint(host: RecordingHost, rc: PrimitiveRenderContext) {
  const ops: Op[] = [];
  for (const p of host.live()) {
    const { ctx, rec } = makeCtx();
    p.draw(ctx, rc);
    ops.push(...rec.ops);
  }
  return {
    ops,
    texts: ops.filter((o) => o.text !== undefined).map((o) => o.text as string),
    /** True when some primitive strokes a horizontal line through `price`. */
    lineAt(price: number): boolean {
      const y = rc.priceScale.priceToY(price);
      return ops.some((o) => (o.type === 'lineTo' || o.type === 'moveTo') && Math.abs(o.args[1] - y) <= 1);
    },
  };
}

describe('invisible stop loss', () => {
  it('draws a working stop that no bracket covers (position, but no target)', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95)], [pos(10, 100)]);

    expect(tc.orderLineCount()).toBe(1);
    expect(host.lines().map((l) => l.order.id)).toEqual(['sl1']);
    expect(host.lines()[0].autoscaleInfo()).toEqual({ min: 95, max: 95 }); // the trigger, not price 0
  });

  it('draws a working stop when the position is not in the snapshot at all', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95)], []);

    expect(tc.orderLineCount()).toBe(1);
    const rc = renderContext();
    const painted = paint(host, rc);
    expect(painted.ops.length).toBeGreaterThan(0); // it used to paint nothing whatsoever
    expect(painted.lineAt(95)).toBe(true);
    expect(painted.texts.some((t) => t.includes(rc.priceScale.format(95)))).toBe(true);
  });

  it('promotes the stop to its own line when the target is cancelled', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95), targetOrder('tp1', 110)], [pos(10, 100)]);
    expect(tc.bracketCount()).toBe(1);
    expect(tc.orderLineCount()).toBe(0);

    tc.reconcile([stopOrder('sl1', 95)], [pos(10, 100)]); // tp1 filled or cancelled
    expect(tc.bracketCount()).toBe(0);
    expect(host.brackets()).toHaveLength(0);
    expect(host.lines().map((l) => l.order.id)).toEqual(['sl1']);
  });

  it('gives a second stop on the same symbol its own line instead of hiding it', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    // Two stops rest on one position; the bracket can only draw one of them.
    tc.reconcile([stopOrder('slA', 95), stopOrder('slB', 92), targetOrder('tp1', 110)], [pos(10, 100)]);

    expect(tc.bracketCount()).toBe(1);
    const drawn = new Set([
      ...host.lines().map((l) => l.order.id),
      ...host.brackets().flatMap((b) => (b.state.stop === 95 ? ['slA'] : ['slB'])),
    ]);
    expect(drawn.has('slA')).toBe(true);
    expect(drawn.has('slB')).toBe(true);
  });

  it('keeps pushing LTP into a standalone stop line', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95)], [pos(10, 100)]);
    tc.onLtp(SYMBOL, 98);

    // The line labels its distance to the LTP only once an LTP has reached it.
    const rc = renderContext();
    const painted = paint(host, rc);
    expect(painted.texts.some((t) => t.includes(rc.priceScale.format(95 - 98)))).toBe(true);
  });
});

describe('phantom bracket line', () => {
  it('draws no take-profit when only a stop exists', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95)], [pos(10, 100)]);

    expect(tc.bracketCount()).toBe(0);
    expect(host.brackets()).toHaveLength(0);
    const painted = paint(host, renderContext());
    expect(painted.texts.some((t) => t.startsWith('TP'))).toBe(false); // no TP at the average price
  });

  it('draws no stop when only a take-profit exists', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([targetOrder('tp1', 110)], [pos(10, 100)]);

    expect(tc.bracketCount()).toBe(0);
    expect(host.lines().map((l) => l.order.id)).toEqual(['tp1']);
    const painted = paint(host, renderContext());
    expect(painted.texts.some((t) => t.startsWith('SL '))).toBe(false); // no phantom stop at 100
  });

  it('a one-sided bracket never reports a leg at the position average', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95)], [pos(-10, 100)]); // short, stop above is irrelevant here
    for (const b of host.brackets()) {
      expect(b.state.target).not.toBe(100);
      expect(b.state.stop).not.toBe(100);
    }
    expect(host.brackets()).toHaveLength(0);
  });

  it('still builds a real two-sided bracket from the orders, not from the average', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95), targetOrder('tp1', 110)], [pos(10, 100)]);

    expect(tc.bracketCount()).toBe(1);
    expect(tc.orderLineCount()).toBe(0); // both legs belong to the bracket
    expect(host.brackets()[0].state).toEqual({ symbol: SYMBOL, side: 'BUY', entry: 100, stop: 95, target: 110 });
  });

  it('drops the bracket and both lines when the position goes flat', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([stopOrder('sl1', 95), targetOrder('tp1', 110)], [pos(10, 100)]);
    tc.reconcile([], [pos(0, 100)]);

    expect(tc.bracketCount()).toBe(0);
    expect(tc.orderLineCount()).toBe(0);
    expect(tc.positionCount()).toBe(0);
    expect(host.live()).toHaveLength(0);
  });

  it('leaves an ordinary entry order untouched alongside a bracket', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile(
      [order('lim1', { price: 98 }), stopOrder('sl1', 95), targetOrder('tp1', 110)],
      [pos(10, 100)],
    );

    expect(host.lines().map((l) => l.order.id)).toEqual(['lim1']);
    expect(tc.bracketCount()).toBe(1);
    expect(host.live().some((p) => p instanceof PositionMarker)).toBe(true);
  });

  it('ignores terminal stops: a filled stop draws no line and no bracket', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile(
      [order('sl1', { role: 'sl', side: 'SELL', type: 'SL-M', triggerPrice: 95, status: 'filled' })],
      [pos(10, 100)],
    );

    expect(tc.orderLineCount()).toBe(0);
    expect(tc.bracketCount()).toBe(0);
  });
});
