import type { MarginData } from '@/types/trading'

export interface FundsSummary {
  available: number
  utilised: number
}

// Brokers report funds as numbers or as numeric strings ("12345.60"), so both
// are accepted. A field that is missing or not a number reads as unknown.
function toAmount(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value.replace(/,/g, ''))
    return Number.isFinite(n) ? n : null
  }
  return null
}

/**
 * Available balance and utilised margin from a /funds response, or null when
 * the response carries neither, so the header shows a placeholder instead of 0.
 */
export function summarizeFunds(data: Partial<MarginData> | null | undefined): FundsSummary | null {
  if (!data) return null
  const available = toAmount(data.availablecash)
  const utilised = toAmount(data.utiliseddebits)
  if (available === null && utilised === null) return null
  return { available: available ?? 0, utilised: utilised ?? 0 }
}

/** Full rupee amount with Indian digit grouping, e.g. 1,23,456.70. */
export function formatFundsAmount(value: number): string {
  return value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
