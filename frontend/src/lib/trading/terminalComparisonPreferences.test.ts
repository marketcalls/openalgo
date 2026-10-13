import { type Bar, type BarsRequest, comparisonController, createChart } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TradingTerminal } from './terminal'

const storageKey = 'comparison-preferences-test'
const savedItem = { id: 'saved', symbol: 'SAVED', exchange: 'NSE', visible: true }
const bars: Bar[] = [
  { time: 60, open: 100, high: 101, low: 99, close: 100 },
  { time: 120, open: 100, high: 102, low: 99, close: 101 },
]
const terminals: TradingTerminal[] = []

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  vi.stubGlobal(
    'WebSocket',
    class {
      readyState = 0
      send() {}
      close() {
        this.readyState = 3
      }
    }
  )
  const context = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
      getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  )
})

afterEach(() => {
  for (const terminal of terminals.splice(0)) terminal.destroy()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function mount(saved: unknown) {
  localStorage.setItem(`${storageKey}-comparisons`, JSON.stringify(saved))
  const onToast = vi.fn()
  const container = document.createElement('div')
  const terminal = new TradingTerminal({
    apiKey: 'fixture',
    wsUrl: 'ws://test.invalid',
    container,
    legendEl: document.createElement('div'),
    storageKey,
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast,
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
    },
  })
  terminals.push(terminal)
  const chart = createChart(container, { shortcuts: false, timeNavigator: false })
  chart.applySize(800, 600)
  const price = chart.addSeries('candlestick')
  price.setData(bars)
  const getBars = vi.fn(async (_request: BarsRequest) => bars)
  Object.assign(terminal, {
    chart,
    price,
    interval: '1m',
    rawBars: bars,
    rest: { getBars },
  })
  return { terminal, chart, getBars, onToast }
}

describe('saved comparison preference recovery', () => {
  it.each([
    ['null definition', [null]],
    ['missing identity', [{}]],
    ['missing visibility', [{ id: 'saved', symbol: 'SAVED', exchange: 'NSE' }]],
    ['invalid visibility', [{ ...savedItem, visible: 'false' }]],
    ['invalid color', [{ ...savedItem, color: 123 }]],
    ['blank exchange', [{ ...savedItem, exchange: ' ' }]],
    ['duplicate ID', [savedItem, { ...savedItem, symbol: 'SECOND' }]],
    ['duplicate source', [savedItem, { ...savedItem, id: 'second' }]],
    [
      'too many definitions',
      Array.from({ length: 33 }, (_, index) => ({
        ...savedItem,
        id: String(index),
        symbol: `SAVED${index}`,
      })),
    ],
  ])('loads a new comparison after rejecting %s', async (_label, items) => {
    const { terminal, chart, getBars, onToast } = mount({ items, mode: 'price' })

    await terminal.addComparison('VALID', 'NSE')

    expect(getBars).toHaveBeenCalledOnce()
    expect(getBars.mock.calls[0][0]).toMatchObject({ symbol: 'VALID', exchange: 'NSE' })
    expect(terminal.comparisonState()).toMatchObject({
      mode: 'percent',
      items: [{ symbol: 'VALID', exchange: 'NSE', status: 'ready' }],
    })
    expect(comparisonController(chart).list()).toHaveLength(1)
    expect(onToast).toHaveBeenCalledOnce()
    expect(onToast).toHaveBeenCalledWith(expect.stringMatching(/saved comparisons/i), 'err')
    expect(JSON.parse(localStorage.getItem(`${storageKey}-comparisons`)!)).toMatchObject({
      mode: 'percent',
      items: [{ symbol: 'VALID', visible: true }],
    })
  })

  it('keeps the existing default when the saved mode is invalid', async () => {
    const { terminal, getBars, onToast } = mount({ items: [savedItem], mode: 'percentage' })
    await terminal.addComparison('VALID', 'NSE')
    expect(getBars).toHaveBeenCalledOnce()
    expect(terminal.comparisonState()).toMatchObject({
      mode: 'percent',
      items: [{ symbol: 'VALID', status: 'ready' }],
    })
    expect(onToast).toHaveBeenCalledOnce()
  })

  it('retains valid saved definitions, visibility, color and the saved price mode as Own scale', async () => {
    const item = { ...savedItem, visible: false, color: '#4f8cff' }
    const { terminal, chart, getBars, onToast } = mount({ items: [item], mode: 'price' })
    await terminal.addComparison('VALID', 'NSE')
    expect(getBars).toHaveBeenCalledTimes(2)
    // A chart saved before the four scales recorded `price` for a line on its
    // own scale, so that is what it opens as.
    expect(terminal.comparisonState()).toMatchObject({
      mode: 'own',
      items: [
        { id: item.id, symbol: item.symbol, color: item.color, status: 'ready' },
        { symbol: 'VALID', status: 'ready' },
      ],
    })
    expect(comparisonController(chart).list()).toHaveLength(2)
    expect(JSON.parse(localStorage.getItem(`${storageKey}-comparisons`)!).items[0]).toEqual(item)
    expect(onToast).not.toHaveBeenCalled()
  })
})

describe('the comparison scale a chart remembers', () => {
  it('keeps a newer scale beside the old field, so an older build still reads its mode', async () => {
    const { terminal } = mount({ items: [savedItem], mode: 'price' })
    await terminal.addComparison('VALID', 'NSE')
    terminal.setComparisonMode('indexed')
    expect(JSON.parse(localStorage.getItem(`${storageKey}-comparisons`)!)).toMatchObject({
      mode: 'percent',
      scale: 'indexed',
    })
    terminal.setComparisonMode('price')
    expect(JSON.parse(localStorage.getItem(`${storageKey}-comparisons`)!)).toMatchObject({
      mode: 'price',
      scale: 'price',
    })
  })

  it('reopens each saved scale as it was chosen', async () => {
    for (const [saved, expected] of [
      [{ mode: 'percent', scale: 'indexed' }, 'indexed'],
      [{ mode: 'price', scale: 'price' }, 'price'],
      [{ mode: 'price' }, 'own'],
      [{ mode: 'percent' }, 'percent'],
      // A scale that disagrees with the old field is not trusted over it.
      [{ mode: 'price', scale: 'indexed' }, 'own'],
    ] as const) {
      const { terminal } = mount({ items: [savedItem], ...saved })
      await terminal.addComparison('VALID', 'NSE')
      expect(terminal.comparisonState().mode).toBe(expected)
    }
  })

  it('shows and hides one line and says so in its state', async () => {
    const { terminal } = mount({ items: [savedItem], mode: 'percent' })
    await terminal.addComparison('VALID', 'NSE')
    terminal.setComparisonVisible('saved', false)
    expect(terminal.comparisonState().items[0]).toMatchObject({ id: 'saved', visible: false })
    expect(JSON.parse(localStorage.getItem(`${storageKey}-comparisons`)!).items[0].visible).toBe(
      false
    )
  })
})
