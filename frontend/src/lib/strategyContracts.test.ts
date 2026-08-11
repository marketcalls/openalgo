import { describe, expect, it } from 'vitest'
import type { OptionChainResponse } from '@/types/option-chain'
import {
  chainIdentity,
  chainMatches,
  contractPriceKey,
  parseFinitePrice,
  resolveOptionContract,
} from './strategyContracts'

const chain18Aug = {
  status: 'success',
  exchange: 'NFO',
  underlying: 'NIFTY',
  underlying_symbol: 'NIFTY',
  underlying_exchange: 'NSE_INDEX',
  underlying_ltp: 24_612.5,
  underlying_prev_close: 24_500,
  expiry_date: '18AUG26',
  expiry_ts: 1_787_020_800,
  forward_price: 24_625.5,
  atm_strike: 24_600,
  chain: [
    {
      strike: 24_600,
      ce: {
        symbol: 'NIFTY18AUG2624600CE',
        label: 'NIFTY 18 AUG 26 24600 CE',
        ltp: 210.5,
        bid: 210,
        ask: 211,
        bid_qty: 50,
        ask_qty: 25,
        open: 200,
        high: 220,
        low: 190,
        prev_close: 205,
        volume: 1_000,
        oi: 2_000,
        lotsize: 50,
        tick_size: 0.05,
        implied_volatility: 14.2,
      },
      pe: null,
    },
  ],
} satisfies OptionChainResponse & { exchange: string }

describe('strategy contract resolution', () => {
  it('matches a chain only when exchange, underlying, and expiry all match', () => {
    expect(chainIdentity('NFO', 'NIFTY', '18-AUG-2026')).toBe('NFO:NIFTY:18AUG26')
    expect(chainMatches(chain18Aug, { exchange: 'NFO', underlying: 'NIFTY', expiry: '18AUG26' })).toBe(
      true
    )
    expect(chainMatches(chain18Aug, { exchange: 'NFO', underlying: 'NIFTY', expiry: '25AUG26' })).toBe(
      false
    )
  })

  it('returns only the canonical listed symbol and its market snapshot', () => {
    expect(resolveOptionContract(chain18Aug, 'CE', 24_600)).toEqual({
      exchange: 'NFO',
      symbol: 'NIFTY18AUG2624600CE',
      expiry: '18AUG26',
      expiryTs: 1_787_020_800,
      lotSize: 50,
      tickSize: 0.05,
      contractValid: true,
      marketPrice: 210.5,
      iv: 14.2,
      forwardPrice: 24_625.5,
      referenceUnderlying: 24_612.5,
      greeks: {
        delta: null,
        gamma: null,
        theta: null,
        vega: null,
      },
    })
  })

  it('rejects an option side that is not listed instead of synthesizing a symbol', () => {
    expect(resolveOptionContract(chain18Aug, 'PE', 24_600)).toBeNull()
  })

  it.each([
    ['missing lot size', undefined, 0.05],
    ['zero lot size', 0, 0.05],
    ['fractional lot size', 12.5, 0.05],
    ['missing tick size', 50, undefined],
    ['zero tick size', 50, 0],
    ['non-finite tick size', 50, Number.POSITIVE_INFINITY],
  ])('rejects listed rows with %s', (_label, lotSize, tickSize) => {
    const response = {
      ...chain18Aug,
      chain: [
        {
          ...chain18Aug.chain[0],
          ce: {
            ...chain18Aug.chain[0].ce,
            lotsize: lotSize,
            tick_size: tickSize,
          },
        },
      ],
    } as unknown as typeof chain18Aug

    expect(resolveOptionContract(response, 'CE', 24_600)).toBeNull()
  })

  it('keys live prices by canonical exchange and symbol', () => {
    expect(contractPriceKey('NFO', 'NIFTY18AUG2624600CE')).toBe('NFO:NIFTY18AUG2624600CE')
  })

  it.each([
    ['210.5', { value: 210.5, error: null }],
    ['0', { value: 0, error: null }],
    ['-1', { value: null, error: 'Price must be zero or greater' }],
    ['Infinity', { value: null, error: 'Enter a finite price' }],
    ['', { value: null, error: 'Enter a price' }],
  ])('parses price %s with explicit validation', (raw, expected) => {
    expect(parseFinitePrice(raw)).toEqual(expected)
  })
})
