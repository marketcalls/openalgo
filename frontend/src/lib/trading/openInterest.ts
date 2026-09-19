const DERIVATIVE_SEGMENTS = new Set(['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCO', 'NCDEX'])
const CASH_SEGMENTS = new Set(['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX'])
const DERIVATIVE_TYPES = new Set(['FUT', 'CE', 'PE', 'PERPFUT'])

/** Capability comes from instrument metadata, never from the history column's value. */
export function openInterestCapability(
  exchange: string,
  metadata: Record<string, unknown> = {}
): boolean | undefined {
  if (typeof metadata.hasOpenInterest === 'boolean') return metadata.hasOpenInterest
  const instrumentType = String(metadata.instrumenttype ?? '')
    .trim()
    .toUpperCase()
  if (instrumentType === 'SPOT' || instrumentType === 'EQ' || instrumentType === 'INDEX')
    return false
  if (DERIVATIVE_TYPES.has(instrumentType)) return true
  if (DERIVATIVE_SEGMENTS.has(exchange)) return true
  if (CASH_SEGMENTS.has(exchange)) return false
  return undefined
}
