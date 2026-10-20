/**
 * Money, percentages and moments in a backtest's charts, written the way a
 * trader reads them.
 *
 * A bare `100800.00` on an axis makes the reader count digits. Rupees are
 * grouped the Indian way (1,00,800) and, on a crowded axis, compacted to lakh
 * and crore (1.01L, 2.50Cr), which is how the amounts are said aloud. Other
 * currencies (crypto runs report USD) use the international grouping and K/M.
 */

const LAKH = 1e5
const CRORE = 1e7

function signOf(value: number): string {
  return value < 0 ? '-' : ''
}

function symbolFor(currency: string): string {
  if (currency === 'INR') return '₹'
  if (currency === 'USD') return '$'
  return `${currency} `
}

/**
 * An amount of money in full: `₹1,00,800`, `-₹500.50`, `$12,450`.
 *
 * Whole amounts drop their paise or cents, so a capital of `1,00,000` does not
 * read as `1,00,000.00`.
 */
export function moneyText(value: number, currency = 'INR'): string {
  if (!Number.isFinite(value)) return '-'
  const abs = Math.abs(value)
  const locale = currency === 'INR' ? 'en-IN' : 'en-US'
  // Paise and cents only where they matter: on small amounts, and never on
  // whole ones. `₹1,10,967` reads faster than `₹1,10,967.63`.
  const digits = abs >= 1000 || abs % 1 === 0 ? 0 : 2
  const body = abs.toLocaleString(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return `${signOf(value)}${symbolFor(currency)}${body}`
}

/**
 * An amount short enough for a price axis: `₹1.01L`, `₹2.5Cr`, `₹85,000`,
 * `$12.4K`. Below a lakh rupees are written in full, because `₹85K` is not how
 * an Indian reader says it.
 */
export function compactMoney(value: number, currency = 'INR'): string {
  if (!Number.isFinite(value)) return '-'
  const abs = Math.abs(value)
  const sign = signOf(value)
  const symbol = symbolFor(currency)
  const trim = (n: number) => n.toFixed(2).replace(/\.?0+$/, '')
  if (currency === 'INR') {
    if (abs >= CRORE) return `${sign}${symbol}${trim(abs / CRORE)}Cr`
    if (abs >= LAKH) return `${sign}${symbol}${trim(abs / LAKH)}L`
    return moneyText(value, currency)
  }
  if (abs >= 1e6) return `${sign}${symbol}${trim(abs / 1e6)}M`
  if (abs >= 1e3) return `${sign}${symbol}${trim(abs / 1e3)}K`
  return moneyText(value, currency)
}

/** A percentage with its sign: `+0.80%`, `-12.40%`, `0.00%`. */
export function signedPercent(value: number): string {
  if (!Number.isFinite(value)) return '-'
  const fixed = value.toFixed(2)
  return value > 0 ? `+${fixed}%` : `${fixed}%`
}

/** A change in money with its sign: `+₹800`, `-₹500`. */
export function signedMoney(value: number, currency = 'INR'): string {
  if (!Number.isFinite(value)) return '-'
  return value > 0 ? `+${moneyText(value, currency)}` : moneyText(value, currency)
}

/** A moment as `15 Sep 2026, 09:01` in the run's own zone. */
export function momentText(seconds: number, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat('en-IN', {
      timeZone,
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(seconds * 1000))
  } catch {
    return new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ')
  }
}
