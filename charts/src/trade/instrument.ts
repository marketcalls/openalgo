import type { Instrument } from 'openalgo-charts';
import type { OrderConstraints } from './validation';

/** Use the adapter's quantity grid directly; this function never converts units or places orders. */
export function orderConstraintsForInstrument(instrument: Instrument): OrderConstraints {
  const { priceTick, quantityStep } = instrument.metadata, ticks = instrument.tickSchedule;
  // A constant tick returns the same three fields it always has.
  return { tickSize: priceTick, lotSize: quantityStep, allowFractionalQty: !Number.isInteger(quantityStep),
    ...(ticks ? { tickSchedule: ticks } : {}) };
}
