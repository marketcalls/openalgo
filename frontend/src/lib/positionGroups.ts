import { parseExpiryDate } from './strategyMath'

// Group keys built by the Positions page: "Equity (...)", "UNDERLYING - DDMMMYY" or "UNDERLYING".
const EXPIRY_KEY = /^(.+) - (\d{1,2}[A-Z]{3}\d{2})$/i

function expiryOf(key: string): { underlying: string; time: number } | null {
  const match = EXPIRY_KEY.exec(key)
  if (!match) return null
  const date = parseExpiryDate(match[2].toUpperCase())
  return date ? { underlying: match[1], time: date.getTime() } : null
}

/**
 * Order for Positions page group keys: the Equity groups first, then groups with an
 * expiry by underlying and expiry date, then everything else alphabetically.
 */
export function compareGroupKeys(a: string, b: string): number {
  const aEquity = a.startsWith('Equity')
  const bEquity = b.startsWith('Equity')
  if (aEquity !== bEquity) return aEquity ? -1 : 1

  const aExpiry = expiryOf(a)
  const bExpiry = expiryOf(b)
  if (aExpiry && bExpiry) {
    return (
      aExpiry.underlying.localeCompare(bExpiry.underlying) ||
      aExpiry.time - bExpiry.time ||
      a.localeCompare(b)
    )
  }
  if (aExpiry || bExpiry) return aExpiry ? -1 : 1

  return a.localeCompare(b)
}
