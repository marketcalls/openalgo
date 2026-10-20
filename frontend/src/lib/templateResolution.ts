import type { OptionType } from './strategyMath'
import { normalizeExpiryCode, resolveListedOptionData } from './strategyContracts'
import type { OptionData, OptionStrike } from '@/types/option-chain'

export { normalizeExpiryCode }

export interface StrikeTopologyLeg {
  strikeOffset: number
  resolvedStrike: number | null
}

function uniqueSorted(values: number[]): number[] {
  return Array.from(new Set(values.filter(Number.isFinite))).sort((a, b) => a - b)
}

export function canReuseChainContract(editedExpiry: string, loadedExpiry: string): boolean {
  return normalizeExpiryCode(editedExpiry) === normalizeExpiryCode(loadedExpiry)
}

export function resolveListedContract(
  chain: OptionStrike[],
  strike: number,
  optionType: OptionType
): OptionData | null {
  return resolveListedOptionData(chain, optionType, strike)
}

export function resolveStrikeOffset(
  strikes: number[],
  atmStrike: number,
  strikeOffset: number
): number | null {
  const listed = uniqueSorted(strikes)
  const atmIndex = listed.indexOf(atmStrike)
  if (atmIndex < 0) return null
  return listed[atmIndex + strikeOffset] ?? null
}

function expiryTime(expiry: string): number {
  const match = /^(\d{1,2})([A-Z]{3})(\d{2})$/.exec(normalizeExpiryCode(expiry))
  if (!match) return Number.NaN
  const months = [
    'JAN',
    'FEB',
    'MAR',
    'APR',
    'MAY',
    'JUN',
    'JUL',
    'AUG',
    'SEP',
    'OCT',
    'NOV',
    'DEC',
  ]
  const month = months.indexOf(match[2])
  if (month < 0) return Number.NaN
  const year = 2000 + Number(match[3])
  return Date.UTC(year, month, Number(match[1]))
}

export function resolveExpiryOffset(
  expiries: string[],
  baseExpiry: string,
  expiryOffset: number
): string | null {
  const ordered = Array.from(new Set(expiries))
    .map((expiry) => ({ expiry, time: expiryTime(expiry) }))
    .filter((item) => Number.isFinite(item.time))
    .sort((a, b) => a.time - b.time)
  const baseIndex = ordered.findIndex((item) => item.expiry === baseExpiry)
  if (baseIndex < 0) return null
  return ordered[baseIndex + expiryOffset]?.expiry ?? null
}

export function validateTemplateStrikeTopology(legs: StrikeTopologyLeg[]): string[] {
  if (legs.some((leg) => leg.resolvedStrike === null)) {
    return ['One or more template strikes are outside the loaded option chain.']
  }

  const strikeByOffset = new Map<number, number>()
  for (const leg of legs) {
    const strike = leg.resolvedStrike as number
    const existing = strikeByOffset.get(leg.strikeOffset)
    if (existing !== undefined && existing !== strike) {
      return ['Legs with the same offset must resolve to the same strike.']
    }
    strikeByOffset.set(leg.strikeOffset, strike)
  }

  const ordered = Array.from(strikeByOffset.entries()).sort(([left], [right]) => left - right)
  for (let index = 1; index < ordered.length; index++) {
    if (ordered[index - 1][1] >= ordered[index][1]) {
      return ['Distinct template offsets must resolve to distinct, ordered strikes.']
    }
  }
  return []
}
