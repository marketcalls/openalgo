import type { MarginData } from '@/types/trading'

export interface FundsSummary {
  available: number | null
  utilised: number | null
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
 * Available balance and utilised margin from a /funds response. Each field is
 * null when missing or unusable, so the header shows a placeholder for that
 * field instead of a real-looking 0.
 */
export function summarizeFunds(data: Partial<MarginData> | null | undefined): FundsSummary {
  return {
    available: toAmount(data?.availablecash),
    utilised: toAmount(data?.utiliseddebits),
  }
}

/** Full rupee amount with Indian digit grouping, e.g. 1,23,456.70; '-' when unknown. */
export function formatFundsAmount(value: number | null): string {
  if (value === null) return '-'
  return value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
