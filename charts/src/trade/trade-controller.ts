/**
 * Trade controller (ARCHITECTURE.md §9.3), read-only by design: the order
 * engine owns the write path. The single
 * source of truth: it reconciles order/position book snapshots into on-chart
 * primitives (add/update/remove) and pushes LTP into them for live P&L. On a
 * reconnect, a fresh snapshot is diffed against current primitives, so vanished
 * orders are removed (STALE handling) with no special code path.
 */
import type { IPrimitive } from 'openalgo-charts';
import type { Order, Position } from './types';
import { isWorking } from './types';
import { WorkingOrderLine } from './order-line';
import { PositionMarker } from './position';
import { BracketGroup, type BracketState } from './bracket';

/** Where the controller attaches/detaches its primitives (the chart implements this). */
export interface TradeHost {
  addPrimitive(p: IPrimitive): void;
  removePrimitive(p: IPrimitive): void;
}

export class TradeController {
  private readonly _host: TradeHost;
  private readonly _orderLines = new Map<string, WorkingOrderLine>();
  private readonly _markers = new Map<string, PositionMarker>();
  private readonly _brackets = new Map<string, BracketGroup>();
  private readonly _ltp = new Map<string, number>();

  public constructor(host: TradeHost) {
    this._host = host;
  }

  /** Reconcile a full book snapshot. Idempotent: safe to call on every update or reconnect. */
  public reconcile(orders: readonly Order[], positions: readonly Position[]): void {
    // Brackets are planned before anything is drawn, because the order lines need
    // to know which stops and targets a bracket is going to draw for them. The
    // attach order is unchanged (lines, markers, then brackets) so relative
    // z-order within a band stays what it was.
    const plan = this._planBrackets(orders, positions);
    this._reconcileOrderLines(orders, plan.covered);
    this._reconcilePositions(positions);
    this._applyBrackets(plan.states);
  }

  private _reconcileOrderLines(orders: readonly Order[], bracketed: ReadonlySet<string>): void {
    const seen = new Set<string>();
    for (const o of orders) {
      // A stop or target is hidden only when a bracket really is drawing it.
      // Everything else gets its own line: a resting stop with no bracket used to
      // draw nothing at all, and a stop a trader cannot see reads as no stop.
      if (!isWorking(o) || bracketed.has(o.id)) continue;
      seen.add(o.id);
      const existing = this._orderLines.get(o.id);
      if (existing) {
        existing.update(o);
      } else {
        const line = new WorkingOrderLine(o);
        const ltp = this._ltp.get(o.symbol);
        if (ltp !== undefined) line.setLtp(ltp);
        this._orderLines.set(o.id, line);
        this._host.addPrimitive(line);
      }
    }
    for (const [id, line] of this._orderLines) {
      if (!seen.has(id)) {
        this._host.removePrimitive(line);
        this._orderLines.delete(id);
      }
    }
  }

  private _reconcilePositions(positions: readonly Position[]): void {
    const seen = new Set<string>();
    for (const p of positions) {
      if (p.netQty === 0) continue;
      seen.add(p.symbol);
      const existing = this._markers.get(p.symbol);
      if (existing) {
        existing.update(p);
      } else {
        const marker = new PositionMarker(p);
        const ltp = this._ltp.get(p.symbol);
        if (ltp !== undefined) marker.setLtp(ltp);
        this._markers.set(p.symbol, marker);
        this._host.addPrimitive(marker);
      }
    }
    for (const [symbol, marker] of this._markers) {
      if (!seen.has(symbol)) {
        this._host.removePrimitive(marker);
        this._markers.delete(symbol);
      }
    }
  }

  /**
   * Decide which brackets to draw, without touching the host. `covered` names the
   * exact orders those brackets account for; every other working order still
   * needs a line of its own.
   */
  private _planBrackets(
    orders: readonly Order[],
    positions: readonly Position[],
  ): { states: Map<string, BracketState>; covered: Set<string> } {
    const sl = new Map<string, Order>();
    const tp = new Map<string, Order>();
    for (const o of orders) {
      if (!isWorking(o)) continue;
      if (o.role === 'sl') sl.set(o.symbol, o);
      else if (o.role === 'tp') tp.set(o.symbol, o);
    }
    const posBySymbol = new Map(positions.map((p) => [p.symbol, p]));
    const states = new Map<string, BracketState>();
    const covered = new Set<string>();
    for (const symbol of new Set([...sl.keys(), ...tp.keys()])) {
      const stop = sl.get(symbol);
      const target = tp.get(symbol);
      // BracketGroup always paints both legs, so it may only stand in for a pair
      // that both exist. A one-sided bracket used to fall back to the position
      // average and drew a take-profit at a price where no order rested; the
      // surviving leg now falls through to its own order line instead. (v2's
      // PositionBrackets makes each leg optional. Until BracketGroup can render
      // one leg, "draw only what exists" means drawing no group here.)
      if (stop === undefined || target === undefined) continue;
      const pos = posBySymbol.get(symbol);
      if (pos === undefined || pos.netQty === 0) continue;
      states.set(symbol, {
        symbol,
        side: pos.netQty > 0 ? 'BUY' : 'SELL',
        entry: pos.avgPrice,
        stop: stop.triggerPrice ?? stop.price,
        target: target.price,
      });
      // Only the two orders the group actually draws. A second stop on the same
      // symbol is not one of them and keeps its own line.
      covered.add(stop.id);
      covered.add(target.id);
    }
    return { states, covered };
  }

  private _applyBrackets(states: ReadonlyMap<string, BracketState>): void {
    for (const [symbol, state] of states) {
      const existing = this._brackets.get(symbol);
      if (existing) existing.update(state);
      else {
        const bg = new BracketGroup(state);
        this._brackets.set(symbol, bg);
        this._host.addPrimitive(bg);
      }
    }
    for (const [symbol, bg] of this._brackets) {
      if (!states.has(symbol)) {
        this._host.removePrimitive(bg);
        this._brackets.delete(symbol);
      }
    }
  }

  /** Push a last price; updates the live P&L / distance on bound primitives. */
  public onLtp(symbol: string, ltp: number): void {
    this._ltp.set(symbol, ltp);
    for (const line of this._orderLines.values()) if (line.order.symbol === symbol) line.setLtp(ltp);
    const marker = this._markers.get(symbol);
    if (marker) marker.setLtp(ltp);
  }

  /** Test/introspection helpers. */
  public orderLineCount(): number { return this._orderLines.size; }
  public positionCount(): number { return this._markers.size; }
  public bracketCount(): number { return this._brackets.size; }
}
