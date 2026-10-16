/**
 * P&L and risk math (ARCHITECTURE.md §9.1). Pure functions: the hot path on
 * every LTP tick, and the part most worth unit-testing.
 */
import type { Position } from './types';

/** Unrealized P&L for a position at the given last price. */
export function unrealizedPnl(position: Position, ltp: number): number {
  return (ltp - position.avgPrice) * position.netQty;
}

/** Unrealized P&L as a percentage of the entry notional. */
export function unrealizedPnlPercent(position: Position, ltp: number): number {
  if (position.avgPrice === 0 || position.netQty === 0) return 0;
  const sign = position.netQty > 0 ? 1 : -1;
  return ((ltp - position.avgPrice) / position.avgPrice) * 100 * sign;
}

/** Breakeven price (entry ± per-unit charges; charges default 0). */
export function breakeven(position: Position, chargesPerUnit = 0): number {
  if (position.netQty === 0) return position.avgPrice;
  const dir = position.netQty > 0 ? 1 : -1;
  return position.avgPrice + dir * chargesPerUnit;
}

/** Risk:reward for a bracket relative to entry. Returns null if risk is zero. */
export function riskReward(entry: number, stop: number, target: number): number | null {
  const risk = Math.abs(entry - stop);
  if (risk === 0) return null;
  return Math.abs(target - entry) / risk;
}

/** True if a stop/target is correctly placed for the side (long: SL<entry<TP). */
export function bracketValid(side: 'BUY' | 'SELL', entry: number, stop: number, target: number): boolean {
  return side === 'BUY' ? stop < entry && target > entry : stop > entry && target < entry;
}
