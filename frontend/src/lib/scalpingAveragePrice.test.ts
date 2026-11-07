import { describe, expect, it } from 'vitest'
import { openAveragePrice } from './scalpingAveragePrice'

const CE = 'NIFTY10NOV2626000CE'

describe('openAveragePrice', () => {
  it('returns the average and quantity of the open position', () => {
    const positions = [
      { symbol: CE, exchange: 'NFO', product: 'NRML', quantity: 75, average_price: 112.35 },
    ]
    expect(openAveragePrice(positions, CE, 'NFO', 'NRML')).toEqual({ price: 112.35, quantity: 75 })
  })

  it('keeps the sign of a short position', () => {
    const positions = [
      { symbol: CE, exchange: 'NFO', product: 'NRML', quantity: -75, average_price: 98.2 },
    ]
    expect(openAveragePrice(positions, CE, 'NFO', 'NRML')).toEqual({ price: 98.2, quantity: -75 })
  })

  it('reads quantities and prices sent as strings', () => {
    const positions = [
      { symbol: CE, exchange: 'NFO', product: 'NRML', quantity: '150', average_price: '101.05' },
    ]
    expect(openAveragePrice(positions, CE, 'NFO', 'NRML')).toEqual({ price: 101.05, quantity: 150 })
  })

  it('has no line for a closed position', () => {
    const positions = [
      { symbol: CE, exchange: 'NFO', product: 'NRML', quantity: 0, average_price: 0 },
      { symbol: CE, exchange: 'NFO', product: 'MIS', quantity: '0', average_price: 120 },
    ]
    expect(openAveragePrice(positions, CE, 'NFO', 'NRML')).toBeNull()
  })

  it('prefers the product the terminal is trading', () => {
    const positions = [
      { symbol: CE, exchange: 'NFO', product: 'MIS', quantity: 75, average_price: 100 },
      { symbol: CE, exchange: 'NFO', product: 'NRML', quantity: 150, average_price: 110 },
    ]
    expect(openAveragePrice(positions, CE, 'NFO', 'NRML')?.price).toBe(110)
    expect(openAveragePrice(positions, CE, 'NFO', 'MIS')?.price).toBe(100)
  })

  it('falls back to another open product', () => {
    const positions = [
      { symbol: CE, exchange: 'NFO', product: 'MIS', quantity: 75, average_price: 100 },
    ]
    expect(openAveragePrice(positions, CE, 'NFO', 'NRML')?.price).toBe(100)
  })

  it('ignores other symbols and exchanges', () => {
    const positions = [
      { symbol: CE, exchange: 'BFO', product: 'NRML', quantity: 75, average_price: 100 },
      {
        symbol: 'NIFTY10NOV2626000PE',
        exchange: 'NFO',
        product: 'NRML',
        quantity: 75,
        average_price: 90,
      },
    ]
    expect(openAveragePrice(positions, CE, 'NFO', 'NRML')).toBeNull()
  })
})
