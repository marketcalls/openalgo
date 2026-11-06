import { describe, expect, it } from 'vitest'
import { compareGroupKeys } from './positionGroups'

const sortKeys = (keys: string[]) => [...keys].sort(compareGroupKeys)

describe('compareGroupKeys', () => {
  it('orders expiries of the same underlying by date, not as text', () => {
    expect(sortKeys(['NIFTY - 02DEC25', 'NIFTY - 25NOV25'])).toEqual([
      'NIFTY - 25NOV25',
      'NIFTY - 02DEC25',
    ])
  })

  it('puts an earlier year first even when its month sorts later as text', () => {
    expect(sortKeys(['BANKNIFTY - 27JAN26', 'BANKNIFTY - 30DEC25'])).toEqual([
      'BANKNIFTY - 30DEC25',
      'BANKNIFTY - 27JAN26',
    ])
  })

  it('sorts by underlying first, then by expiry', () => {
    expect(
      sortKeys(['NIFTY - 02DEC25', 'BANKNIFTY - 30DEC25', 'NIFTY - 25NOV25', 'BANKNIFTY - 25NOV25'])
    ).toEqual(['BANKNIFTY - 25NOV25', 'BANKNIFTY - 30DEC25', 'NIFTY - 25NOV25', 'NIFTY - 02DEC25'])
  })

  it('keeps the Equity groups first and groups without an expiry last', () => {
    expect(
      sortKeys([
        'ABCUNPARSED',
        'NIFTY - 02DEC25',
        'Equity (Intraday)',
        'CRUDEOIL - 19DEC25',
        'Equity (Delivery)',
      ])
    ).toEqual([
      'Equity (Delivery)',
      'Equity (Intraday)',
      'CRUDEOIL - 19DEC25',
      'NIFTY - 02DEC25',
      'ABCUNPARSED',
    ])
  })

  it('falls back to alphabetical order when no group has an expiry', () => {
    expect(sortKeys(['RELIANCE', 'NIFTY', 'BANKNIFTY'])).toEqual(['BANKNIFTY', 'NIFTY', 'RELIANCE'])
  })
})
