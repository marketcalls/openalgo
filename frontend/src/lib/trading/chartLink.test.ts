import { describe, expect, it } from 'vitest'
import { chartHref, hasChartRequest, readChartRequest, withoutChartRequest } from './chartLink'

const params = (href: string) => new URL(href, 'http://host.invalid').searchParams

describe('chart links', () => {
  it('round-trips an option symbol and its exchange', () => {
    const href = chartHref('NIFTY28MAR2420800CE', 'NFO')
    expect(href.startsWith('/trading?')).toBe(true)
    expect(readChartRequest(params(href))).toEqual({
      symbol: 'NIFTY28MAR2420800CE',
      exchange: 'NFO',
    })
  })

  it('keeps characters a symbol may carry intact', () => {
    const href = chartHref('M&M', 'NSE')
    expect(readChartRequest(params(href))).toEqual({ symbol: 'M&M', exchange: 'NSE' })
  })

  it('asks for nothing without both parts', () => {
    expect(readChartRequest(params('/trading?symbol=SBIN'))).toBeNull()
    expect(readChartRequest(params('/trading?exchange=NSE'))).toBeNull()
    expect(readChartRequest(params('/trading?symbol=%20&exchange=NSE'))).toBeNull()
    expect(hasChartRequest(params('/trading?symbol=SBIN'))).toBe(true)
    expect(hasChartRequest(params('/trading'))).toBe(false)
  })

  it('normalises the exchange to the platform spelling', () => {
    expect(readChartRequest(params('/trading?symbol=SBIN&exchange=nse'))?.exchange).toBe('NSE')
  })

  it('drops only its own parameters', () => {
    const rest = withoutChartRequest(params('/trading?symbol=SBIN&exchange=NSE&other=1'))
    expect(rest.toString()).toBe('other=1')
  })
})
