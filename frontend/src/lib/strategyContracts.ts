import type { OptionType } from './strategyMath'
import type { OptionChainResponse, OptionData, OptionStrike } from '@/types/option-chain'

export interface ChainIdentity {
  exchange: string
  underlying: string
  expiry: string
}

export interface ResolvedLegMarket {
  exchange: string
  symbol: string
  expiry: string
  expiryTs: number | null
  lotSize: number
  tickSize: number
  /** Resolution succeeded against the current canonical listing. */
  contractValid: true
  marketPrice: number
  iv: number
  forwardPrice: number | null
  referenceUnderlying: number
  greeks: {
    delta: number | null
    gamma: number | null
    theta: number | null
    vega: number | null
  }
}

/** A fetched option chain paired with the derivative exchange used to fetch it. */
export interface ListedOptionChainResponse extends OptionChainResponse {
  exchange: string
}

export function normalizeExpiryCode(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

export function chainIdentity(exchange: string, underlying: string, expiry: string): string {
  return `${exchange}:${underlying}:${normalizeExpiryCode(expiry)}`
}

export function chainMatches(response: ListedOptionChainResponse, identity: ChainIdentity): boolean {
  return (
    response.exchange === identity.exchange &&
    response.underlying === identity.underlying &&
    normalizeExpiryCode(response.expiry_date) === normalizeExpiryCode(identity.expiry)
  )
}

export function contractPriceKey(exchange: string, symbol: string): string {
  return `${exchange}:${symbol}`
}

export function resolveListedOptionData(
  chain: OptionStrike[],
  optionType: OptionType,
  strike: number
): OptionData | null {
  const row = chain.find((item) => item.strike === strike)
  return (optionType === 'CE' ? row?.ce : row?.pe) ?? null
}

export function resolveOptionContract(
  response: ListedOptionChainResponse,
  optionType: OptionType,
  strike: number
): ResolvedLegMarket | null {
  const contract = resolveListedOptionData(response.chain, optionType, strike)
  if (contract === null) return null
  if (
    !Number.isInteger(contract.lotsize) ||
    contract.lotsize <= 0 ||
    typeof contract.tick_size !== 'number' ||
    !Number.isFinite(contract.tick_size) ||
    contract.tick_size <= 0
  ) {
    return null
  }

  return {
    exchange: response.exchange,
    symbol: contract.symbol,
    expiry: normalizeExpiryCode(response.expiry_date),
    expiryTs: response.expiry_ts ?? null,
    lotSize: contract.lotsize,
    tickSize: contract.tick_size,
    contractValid: true,
    marketPrice: contract.ltp,
    iv: contract.implied_volatility ?? 0,
    forwardPrice: response.forward_price ?? null,
    referenceUnderlying: response.underlying_ltp,
    greeks: {
      delta: contract.delta ?? null,
      gamma: contract.gamma ?? null,
      theta: contract.theta ?? null,
      vega: contract.vega ?? null,
    },
  }
}

export function parseFinitePrice(raw: string | number): { value: number | null; error: string | null } {
  if (typeof raw === 'string' && raw.trim() === '') {
    return { value: null, error: 'Enter a price' }
  }

  const value = typeof raw === 'number' ? raw : Number(raw)
  if (!Number.isFinite(value)) return { value: null, error: 'Enter a finite price' }
  if (value < 0) return { value: null, error: 'Price must be zero or greater' }
  return { value, error: null }
}
