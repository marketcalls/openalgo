/**
 * Trade-layer data model (ARCHITECTURE.md §9). Broker-agnostic shapes a broker
 * adapter produces; the chart depends only on these, not on OpenAlgo's REST.
 */
// Declared once, in the base's feed types, and named here too so the tier
// exports them. Imported by path, not from 'openalgo-charts': the base's
// OpenAlgo adapter imports this module, and going through the entry would
// close an import loop.
import type { OrderSide, OrderType } from '../feed/types';

export type { OrderSide, OrderType };

/** Lifecycle states (§9.5): the trade controller reconciles them from book snapshots, and the order engine moves them as it writes. */
export type OrderStatus =
  | 'pending'   // submitted, not yet acknowledged
  | 'working'   // live in the book
  | 'partial'   // partially filled
  | 'filled'    // fully filled (terminal)
  | 'cancelled' // cancelled (terminal)
  | 'rejected'; // rejected (terminal)

export type OrderRole = 'entry' | 'sl' | 'tp';

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  type: OrderType;
  qty: number;
  filledQty: number;
  price: number;
  triggerPrice?: number | undefined;
  status: OrderStatus;
  /** Links SL/TP child orders to their position/entry. */
  parentId?: string;
  role?: OrderRole | undefined;
}

export interface Position {
  symbol: string;
  /** Net signed quantity: positive = long, negative = short, 0 = flat. */
  netQty: number;
  avgPrice: number;
  /** The account holding it, when the provider says. `AccountManager.positions()` drops a row naming another account. */
  accountId?: string;
}

/** A working order is one still live in the book (not terminal). */
export function isWorking(o: Order): boolean {
  return o.status === 'pending' || o.status === 'working' || o.status === 'partial';
}
