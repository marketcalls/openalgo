/**
 * Pre-trade validation (ARCHITECTURE.md §9.5). Pure guards run client-side so a
 * bad order is blocked and explained rather than round-tripping to a broker
 * rejection. Tick-size rounding, price-band, quantity and freeze-quantity checks.
 *
 * ADVISORY ONLY. The broker RMS is authoritative for every rule here. A check
 * that a user can bypass by editing the call in devtools is a UX affordance, not
 * a risk control: it exists to explain a mistake before the round trip, never to
 * be the thing that stops a bad order. Anything that must actually hold has to
 * live in the feed (see the OpenAlgo compatibility note: the production terminal
 * calls `trade.place` directly and never constructs `OrderEngine`).
 */
import type { TickSchedule } from 'openalgo-charts';
import { roundToTick } from '../helpers/math';

export interface PriceBand {
  lower: number;
  upper: number;
}

/**
 * Machine-readable rejection code. Three of these (`QTY_STEP`,
 * `QTY_FREEZE_LIMIT`, `PRICE_OUT_OF_BAND`) are spelled exactly as the planned v2
 * broker contract's `RejectCode` members, so a mapping to it would be
 * identity; `QTY_INVALID` and `PRICE_INVALID` are local, and would fold into
 * its `CONTRACT_VIOLATION`. Every member is emitted by a branch below: a code
 * nothing can produce would be a label with nothing behind it.
 */
export type ValidationCode =
  | 'QTY_INVALID'
  | 'QTY_STEP'
  | 'QTY_FREEZE_LIMIT'
  | 'PRICE_INVALID'
  | 'PRICE_OUT_OF_BAND';

export interface ValidationResult {
  ok: boolean;
  reason?: string;
  /** Machine-readable form of `reason`; present on every rejection. */
  code?: ValidationCode;
  /** Price after tick-size snapping (when applicable). */
  price?: number;
}

export interface OrderConstraints {
  tickSize: number;
  /**
   * Price-dependent ticks. When set it decides every snap and `tickSize` is
   * only read by older code, so give it the schedule's `minMove`. Absent or
   * null, the constant `tickSize` snaps exactly as it always has.
   */
  tickSchedule?: TickSchedule | null;
  priceBand?: PriceBand;
  /** Max quantity per single order (exchange freeze limit). */
  freezeQty?: number;
  /**
   * Contract lot size. When set, quantity must be a whole multiple of it: 100 on
   * a 75-lot future is rejected here rather than by the exchange.
   */
  lotSize?: number;
  /**
   * Set true only for a venue that genuinely trades fractions, such as crypto.
   * Absent means whole quantities, which is every Indian equity and F&O contract
   * and the reason fractional quantities are rejected by default: a fractional
   * quantity reaching those brokers is a defect, not a preference. A `lotSize`
   * grid still applies when this is true.
   */
  allowFractionalQty?: boolean;
}

/** True if `price` lies within the inclusive band. */
export function withinPriceBand(price: number, band: PriceBand): boolean {
  return price >= band.lower && price <= band.upper;
}

/**
 * Decimal division needs rounding slack, but quantity growth must never turn
 * half a lot into rounding noise. Cap slack in grid units and reject counts
 * whose neighboring integers cannot be represented safely.
 */
function offGrid(value: number, step: number): boolean {
  if (!Number.isFinite(step) || step <= 0) return false;
  const units = value / step;
  const nearest = Math.round(units);
  if (!Number.isSafeInteger(nearest) || nearest < 1) return true;
  // Large valid decimal multiples can divide imprecisely yet round-trip exactly.
  if (nearest * step === value) return false;
  const tolerance = Math.min(1e-7, 8 * Number.EPSILON * Math.max(1, Math.abs(units)));
  return Math.abs(units - nearest) > tolerance;
}

/**
 * Validate a quantity on its own. Split out from `validateOrder` because a
 * market order has no price, and the freeze and lot limits must still apply to
 * it: routing quantity checks through the price path left them unreachable for
 * exactly the orders that are hardest to take back.
 */
export function validateQuantity(qty: number, c: OrderConstraints): ValidationResult {
  if (!Number.isFinite(qty)) {
    return { ok: false, code: 'QTY_INVALID', reason: 'quantity must be a finite number' };
  }
  if (qty <= 0) return { ok: false, code: 'QTY_INVALID', reason: 'quantity must be positive' };

  // A lot grid subsumes the whole-number check when lotSize is itself whole.
  const step = c.lotSize ?? (c.allowFractionalQty === true ? undefined : 1);
  if (step !== undefined && offGrid(qty, step)) {
    return {
      ok: false,
      code: 'QTY_STEP',
      reason: c.lotSize !== undefined
        ? `quantity ${qty} is not a multiple of lot size ${c.lotSize}`
        : `quantity ${qty} must be a whole number`,
    };
  }

  if (c.freezeQty !== undefined && qty > c.freezeQty) {
    return { ok: false, code: 'QTY_FREEZE_LIMIT', reason: `quantity ${qty} exceeds freeze limit ${c.freezeQty}` };
  }
  return { ok: true };
}

/**
 * Validate a price on its own, returning the tick-snapped value. Snapping is
 * unchanged; the only addition is rejecting a non-finite price, which otherwise
 * snaps to NaN and then passes an absent band as if it were a real level.
 */
export function validatePrice(price: number, c: OrderConstraints): ValidationResult {
  if (!Number.isFinite(price)) {
    return { ok: false, code: 'PRICE_INVALID', reason: 'price must be a finite number' };
  }
  const ticks = c.tickSchedule;
  // A band list pasted in place of a schedule would round nothing and pass.
  // Null means none, as it does for chart.trading.setTickSchedule.
  if (ticks != null && typeof ticks.round !== 'function') {
    throw new TypeError('OrderConstraints.tickSchedule must be built with new TickSchedule(bands)');
  }
  const snapped = ticks ? ticks.round(price) : roundToTick(price, c.tickSize);
  if (c.priceBand && !withinPriceBand(snapped, c.priceBand)) {
    return {
      ok: false,
      code: 'PRICE_OUT_OF_BAND',
      reason: `price ${snapped} outside band ${c.priceBand.lower} to ${c.priceBand.upper}`,
    };
  }
  return { ok: true, price: snapped };
}

/**
 * Validate a price + qty against constraints. Snaps price to the tick size and
 * returns the snapped value; rejects out-of-band prices and bad quantities.
 *
 * `price` may be omitted for an order that has none (market), in which case only
 * the quantity is checked and no `price` comes back. Quantity is checked first,
 * so a request wrong in both ways reports the quantity, as it always has.
 */
export function validateOrder(price: number | undefined, qty: number, c: OrderConstraints): ValidationResult {
  const q = validateQuantity(qty, c);
  if (!q.ok) return q;
  if (price === undefined) return { ok: true };
  return validatePrice(price, c);
}
