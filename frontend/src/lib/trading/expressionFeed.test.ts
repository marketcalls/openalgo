import type { Bar, BarsRequest, DataFeed } from 'openalgo-charts'
import { describe, expect, it, vi } from 'vitest'
import { ExpressionFeed, isChartExpression, resolveLeg } from './expressionFeed'

const bar = (time: number, close: number): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
})

function inner(answers: Record<string, Bar[]>) {
  const requests: BarsRequest[] = []
  const feed: DataFeed = {
    getBars: async (req) => {
      requests.push(req)
      return answers[`${req.exchange}:${req.symbol}`] ?? []
    },
    getCachedBars: vi.fn(async () => undefined),
  }
  return { feed, requests }
}

describe('ExpressionFeed', () => {
  it('retains combined leg activity for straddles, spreads and repeated symbols', async () => {
    const { feed } = inner({
      'NFO:CE': [{ ...bar(60, 100), volume: 20 }],
      'NFO:PE': [{ ...bar(60, 200), volume: 30 }],
    })
    const expression = new ExpressionFeed(feed, () => 'NFO')
    for (const symbol of ['CE+PE', 'CE-PE', '2*CE+PE', 'CE+CE+PE']) {
      // No exchange: a computed chart is several instruments and has none.
      const bars = await expression.getBars({ symbol, exchange: '', interval: '1m' })
      expect(bars[0].volume).toBe(50)
    }
  })

  it('fetches every leg through the inner feed with the pane exchange and folds them', async () => {
    const { feed, requests } = inner({
      'NFO:CE': [bar(60, 100), bar(120, 101)],
      'NFO:PE': [bar(60, 200), bar(120, 202)],
    })
    const expression = new ExpressionFeed(feed, () => 'NFO')
    const bars = await expression.getBars({
      symbol: 'CE+PE',
      exchange: '',
      interval: '1m',
      from: 0,
      to: 130,
    })
    expect(bars.map((b) => [b.time, b.close])).toEqual([
      [60, 300],
      [120, 303],
    ])
    expect(requests.map((r) => `${r.exchange}:${r.symbol}`)).toEqual(['NFO:CE', 'NFO:PE'])
    // The window and interval travel unchanged, so a repair or a page of the
    // combination is a repair or a page of every leg.
    expect(requests[0]).toMatchObject({ interval: '1m', from: 0, to: 130 })
    expect(Object.keys(expression.legBars)).toEqual(['CE', 'PE'])
  })

  it('keeps the exchange a leg names for itself', async () => {
    const { feed, requests } = inner({ 'NSE:RELIANCE': [bar(60, 10)], 'NFO:NIFTY': [bar(60, 20)] })
    await new ExpressionFeed(feed, () => 'NFO').getBars({
      symbol: 'NSE:RELIANCE+NIFTY',
      exchange: '',
      interval: '1m',
    })
    expect(requests.map((r) => `${r.exchange}:${r.symbol}`)).toEqual(['NSE:RELIANCE', 'NFO:NIFTY'])
  })

  it('refuses a combination with a missing leg rather than charting a gap', async () => {
    const { feed } = inner({ 'NFO:CE': [bar(60, 100)] })
    await expect(
      new ExpressionFeed(feed, () => 'NFO').getBars({
        symbol: 'CE+PE',
        exchange: '',
        interval: '1m',
      })
    ).rejects.toThrow('no bars for PE')
  })

  it('passes a hyphenated instrument through instead of folding it', async () => {
    // The reported failure, one layer below where it looked like it was. Every
    // load goes through this feed, and `BAJAJ-AUTO` is a subtraction to the
    // grammar, so the chart asked the history API for `BAJAJ` and `AUTO`:
    // two instruments that do not exist, and a 400 for a symbol the platform
    // resolves perfectly well.
    const { feed, requests } = inner({ 'NSE:BAJAJ-AUTO': [bar(60, 11577)] })
    const expression = new ExpressionFeed(feed, () => 'NSE')

    const bars = await expression.getBars({
      symbol: 'BAJAJ-AUTO',
      exchange: 'NSE',
      interval: '1h',
    })

    expect(bars).toHaveLength(1)
    expect(requests).toHaveLength(1)
    expect(requests[0]).toMatchObject({ symbol: 'BAJAJ-AUTO', exchange: 'NSE' })
  })

  it('keeps a hyphenated instrument out of the fold on the cache peek too', async () => {
    const { feed } = inner({ 'NSE:BAJAJ-AUTO': [bar(60, 11577)] })
    const expression = new ExpressionFeed(feed, () => 'NSE')

    await expression.getCachedBars({ symbol: 'BAJAJ-AUTO', exchange: 'NSE', interval: '1h' })

    expect(feed.getCachedBars).toHaveBeenCalledTimes(1)
  })

  it('still folds a computed chart, which carries no exchange of its own', async () => {
    // The capability this feed exists for, and the one the fix must not cost.
    const { feed } = inner({
      'NFO:CE': [{ ...bar(60, 100), volume: 20 }],
      'NFO:PE': [{ ...bar(60, 200), volume: 30 }],
    })
    const expression = new ExpressionFeed(feed, () => 'NFO')

    const bars = await expression.getBars({ symbol: 'CE-PE', exchange: '', interval: '1m' })

    expect(bars[0].close).toBe(-100)
  })

  it('passes a plain symbol straight through, cache peek included', async () => {
    const { feed, requests } = inner({ 'NFO:NIFTY29SEP26FUT': [bar(60, 23000)] })
    const expression = new ExpressionFeed(feed, () => 'NSE')
    const bars = await expression.getBars({
      symbol: 'NIFTY29SEP26FUT',
      exchange: 'NFO',
      interval: '1m',
    })
    expect(bars).toHaveLength(1)
    expect(requests).toHaveLength(1)
    await expression.getCachedBars({ symbol: 'NIFTY29SEP26FUT', exchange: 'NFO', interval: '1m' })
    expect(feed.getCachedBars).toHaveBeenCalledTimes(1)
    // A combination is always folded fresh.
    await expression.getCachedBars({ symbol: 'CE+PE', exchange: '', interval: '1m' })
    expect(feed.getCachedBars).toHaveBeenCalledTimes(1)
  })
})

describe('helpers', () => {
  it('resolveLeg honours a named exchange and falls back to the default', () => {
    expect(resolveLeg('NSE:RELIANCE', 'NFO')).toEqual({ exchange: 'NSE', symbol: 'RELIANCE' })
    expect(resolveLeg('NIFTY', 'NFO')).toEqual({ exchange: 'NFO', symbol: 'NIFTY' })
  })

  it('isChartExpression tells arithmetic from a symbol and a half-typed one from both', () => {
    expect(isChartExpression('CE+PE')).toBe(true)
    expect(isChartExpression('NIFTY29SEP26FUT')).toBe(false)
    expect(isChartExpression('NIFTY/')).toBe(false)
    expect(isChartExpression('')).toBe(false)
  })
})
