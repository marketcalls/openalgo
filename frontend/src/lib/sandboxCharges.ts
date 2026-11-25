// Wording and layout shared by the sandbox charges pages
// (/sandbox/commissions and /sandbox/calculator).
//
// Presentation only. Every figure these pages show is worked out by the
// server (sandbox/charges.py); nothing here computes a charge.

import type { ChargeBreakdown, ChargeMarket } from '@/api/sandbox-charges'

export type Money = (value: number) => string

export interface ChargeLine {
  key: keyof ChargeBreakdown
  label: string
  short: string
}

/** The lines of a charge breakdown, in the order a contract note lists them. */
export const CHARGE_LINES: ChargeLine[] = [
  { key: 'brokerage', label: 'Brokerage', short: 'Brokerage' },
  { key: 'stt', label: 'STT / CTT', short: 'STT / CTT' },
  { key: 'exchange_charges', label: 'Exchange transaction charges', short: 'Exchange' },
  { key: 'sebi_charges', label: 'SEBI charges', short: 'SEBI' },
  { key: 'stamp_duty', label: 'Stamp duty', short: 'Stamp duty' },
  { key: 'gst', label: 'GST', short: 'GST' },
]

/** A crypto trade pays the venue fee and nothing else, so it has one line. */
const CRYPTO_LINES: ChargeLine[] = [{ key: 'brokerage', label: 'Venue fee', short: 'Fee' }]

/**
 * The lines a market's trades are broken into. A trader on a crypto venue is
 * not shown STT, SEBI charges or stamp duty: they are charges of the Indian
 * exchanges, and columns of zeros for them say the wrong market.
 */
export function chargeLinesFor(market: ChargeMarket): ChargeLine[] {
  return market === 'crypto' ? CRYPTO_LINES : CHARGE_LINES
}

/**
 * What each market calls its own things. An Indian broker charges brokerage
 * under a plan; a crypto venue charges a fee.
 */
export const CHARGE_WORDS: Record<
  ChargeMarket,
  { calculator: string; plan: string; fee: string; none: string }
> = {
  indian: {
    calculator: 'Brokerage Calculator',
    plan: 'Brokerage Plan',
    fee: 'Brokerage',
    none: 'No brokerage',
  },
  crypto: {
    calculator: 'Fee Calculator',
    plan: 'Venue Fee',
    fee: 'Venue fee',
    none: 'No fee',
  },
}

/** Whether a typed value is a number the brokerage plan can hold. */
export function isAmount(value: string): boolean {
  if (value.trim() === '') return false
  const number = Number(value)
  return Number.isFinite(number) && number >= 0
}

/**
 * A segment's brokerage in one sentence, as a pricing page would put it.
 *
 * Wording only. Which of the two is lower on a given trade is worked out by
 * the server when the trade fills.
 */
export function describePlan(
  flat: string,
  percent: string,
  money: Money,
  none = CHARGE_WORDS.indian.none
): string {
  if (!isAmount(flat) || !isAmount(percent)) return 'Enter a number, 0 or above'
  const amount = Number(flat)
  const share = Number(percent)
  if (amount > 0 && share > 0) {
    return `${money(amount)} per executed order or ${share}% of the trade value, whichever is lower`
  }
  if (amount > 0) return `${money(amount)} per executed order`
  if (share > 0) return `${share}% of the trade value`
  return none
}

/** The text colour for a profit, a loss, or neither. */
export function pnlColor(value: number): string {
  if (value > 0) return 'text-green-500'
  if (value < 0) return 'text-red-500'
  return ''
}
