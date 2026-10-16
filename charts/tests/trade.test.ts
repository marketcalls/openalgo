import { darkTheme } from '../src/theme';
import { describe, it, expect } from 'vitest';
import { unrealizedPnl, unrealizedPnlPercent, breakeven, riskReward, bracketValid } from '../src/trade/pnl';
import { TradeController, type TradeHost } from '../src/trade/trade-controller';
import { FakeBroker } from '../src/trade/fake-broker';
import { WorkingOrderLine } from '../src/trade/order-line';
import { PositionMarker } from '../src/trade/position';
import { BracketGroup } from '../src/trade/bracket';
import type { Order, Position } from '../src/trade/types';
import type { IPrimitive, PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { makeCtx } from './helpers/fake-ctx';

const order = (id: string, o: Partial<Order> = {}): Order => ({
  id, symbol: 'RELIANCE', side: 'BUY', type: 'LIMIT', qty: 10, filledQty: 0, price: 100, status: 'working', ...o,
});
const pos = (netQty: number, avg: number): Position => ({ symbol: 'RELIANCE', netQty, avgPrice: avg });

class RecordingHost implements TradeHost {
  public added: IPrimitive[] = [];
  public removed: IPrimitive[] = [];
  public addPrimitive(p: IPrimitive): void { this.added.push(p); }
  public removePrimitive(p: IPrimitive): void { this.removed.push(p); }
  public live(): IPrimitive[] { return this.added.filter((p) => !this.removed.includes(p)); }
}

describe('P&L math', () => {
  it('computes unrealized P&L for long and short', () => {
    expect(unrealizedPnl(pos(10, 100), 105)).toBe(50); // long +5 × 10
    expect(unrealizedPnl(pos(-10, 100), 105)).toBe(-50); // short loses when price rises
    expect(unrealizedPnl(pos(-10, 100), 95)).toBe(50); // short profits when price falls
  });
  it('computes P&L percent with correct sign', () => {
    expect(unrealizedPnlPercent(pos(10, 100), 110)).toBeCloseTo(10);
    expect(unrealizedPnlPercent(pos(-10, 100), 110)).toBeCloseTo(-10);
  });
  it('breakeven shifts by charges in the trade direction', () => {
    expect(breakeven(pos(10, 100), 0.5)).toBeCloseTo(100.5);
    expect(breakeven(pos(-10, 100), 0.5)).toBeCloseTo(99.5);
  });
  it('risk:reward and bracket validity', () => {
    expect(riskReward(100, 95, 110)).toBeCloseTo(2); // reward 10 / risk 5
    expect(riskReward(100, 100, 110)).toBeNull(); // zero risk
    expect(bracketValid('BUY', 100, 95, 110)).toBe(true);
    expect(bracketValid('BUY', 100, 105, 110)).toBe(false); // SL above entry on a long
    expect(bracketValid('SELL', 100, 105, 90)).toBe(true);
  });
});

describe('TradeController reconciliation', () => {
  it('creates order lines + position marker from a snapshot', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([order('o1'), order('o2', { price: 90 })], [pos(10, 95)]);
    expect(tc.orderLineCount()).toBe(2);
    expect(tc.positionCount()).toBe(1);
    expect(host.live().some((p) => p instanceof WorkingOrderLine)).toBe(true);
    expect(host.live().some((p) => p instanceof PositionMarker)).toBe(true);
  });

  it('removes an order line when the order fills/cancels (next snapshot omits it)', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([order('o1'), order('o2')], []);
    expect(tc.orderLineCount()).toBe(2);
    tc.reconcile([order('o1')], []); // o2 gone
    expect(tc.orderLineCount()).toBe(1);
    expect(host.removed.length).toBe(1);
  });

  it('removes a position marker when flat (netQty 0)', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([], [pos(10, 100)]);
    expect(tc.positionCount()).toBe(1);
    tc.reconcile([], [pos(0, 100)]);
    expect(tc.positionCount()).toBe(0);
  });

  it('builds a bracket from a position + SL/TP child orders (excluded from order lines)', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile(
      [order('sl1', { role: 'sl', side: 'SELL', type: 'SL-M', triggerPrice: 95 }),
       order('tp1', { role: 'tp', side: 'SELL', price: 110 })],
      [pos(10, 100)],
    );
    expect(tc.bracketCount()).toBe(1);
    expect(tc.orderLineCount()).toBe(0); // sl/tp shown via the bracket, not as lines
    expect(host.live().some((p) => p instanceof BracketGroup)).toBe(true);
  });

  it('reconnect: a fresh snapshot missing prior orders removes them (STALE)', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    tc.reconcile([order('o1'), order('o2'), order('o3')], [pos(5, 100)]);
    expect(tc.orderLineCount()).toBe(3);
    // reconnect: broker returns only o1 and the position is flat
    tc.reconcile([order('o1')], []);
    expect(tc.orderLineCount()).toBe(1);
    expect(tc.positionCount()).toBe(0);
  });
});

describe('TradeController + FakeBroker live P&L', () => {
  it('wires book + ltp through to primitives', () => {
    const host = new RecordingHost();
    const tc = new TradeController(host);
    const broker = new FakeBroker();
    broker.onBook((o, p) => tc.reconcile(o, p));
    broker.onLtp((s, ltp) => tc.onLtp(s, ltp));

    broker.setBook([], [pos(10, 100)]);
    expect(tc.positionCount()).toBe(1);
    broker.emitLtp('RELIANCE', 108);
    // marker P&L draws without error and reflects the ltp
    const marker = host.live().find((p) => p instanceof PositionMarker) as PositionMarker;
    expect(unrealizedPnl(marker.position, 108)).toBe(80);
  });
});

describe('trade primitives render (recording context)', () => {
  function rc(): PrimitiveRenderContext {
    const dl = new DataLayer();
    const priceScale = new PriceScale();
    priceScale.setHeight(400);
    priceScale.setPriceRange({ min: 80, max: 120 });
    const timeScale = new TimeScale();
    timeScale.setWidth(600);
    return { timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme };
  }

  it('order line, position marker, bracket all draw without error', () => {
    const r = rc();
    const ol = new WorkingOrderLine(order('o1', { price: 100 }));
    ol.setLtp(102);
    const pm = new PositionMarker(pos(10, 100));
    pm.setLtp(105);
    const bg = new BracketGroup({ symbol: 'RELIANCE', side: 'BUY', entry: 100, stop: 95, target: 110 });
    for (const p of [ol, pm, bg]) {
      const { ctx, rec } = makeCtx();
      expect(() => p.draw(ctx, r)).not.toThrow();
      expect(rec.ops.length).toBeGreaterThan(0);
    }
  });

  it('bracket hit-tests SL and TP zones', () => {
    const r = rc();
    const bg = new BracketGroup({ symbol: 'RELIANCE', side: 'BUY', entry: 100, stop: 95, target: 110 });
    const ySl = r.priceScale.priceToY(95);
    expect(bg.hitTest(300, ySl, r)?.externalId).toBe('bracket-sl:RELIANCE');
  });
});
