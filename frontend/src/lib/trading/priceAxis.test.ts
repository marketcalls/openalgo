import {
  ALT_PRESET,
  type Bar,
  type ContextMenuEvent,
  createChart,
  DEFAULT_KEYMAP,
  PriceLevels,
} from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AXIS_SIDE_KEY,
  HOST_LEVELS,
  isPriceAxisSetting,
  keyboardOwnedElsewhere,
  levelKey,
  levelPatch,
  levelShow,
  PRICE_AXIS_DEFAULTS,
  PriceAxisController,
  pinOnceMeasured,
  priceAxisPatch,
  priceAxisSettingsView,
  priceAxisShortcuts,
} from './priceAxis'
import type { ChartSettingsRequest } from './terminal'

/** Monday 21 September 2026, 09:15 IST. */
const MONDAY = Date.UTC(2026, 8, 21, 3, 45) / 1000
const DAY = 86_400

function minutes(start: number, closes: number[]): Bar[] {
  return closes.map((close, i) => ({
    time: start + i * 60,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
  }))
}

/** Two sessions: Monday closes at 103, Tuesday trades 110 to 112. */
const TWO_SESSIONS = [
  ...minutes(MONDAY, [100, 101, 103]),
  ...minutes(MONDAY + DAY, [110, 112, 111]),
]

function chartOf(bars: Bar[]) {
  const container = document.createElement('div')
  const chart = createChart(container, {
    shortcuts: false,
    timeNavigator: false,
    raf: {
      schedule: (cb) => {
        cb()
        return 1
      },
      cancel() {},
    },
  })
  chart.applySize(800, 600)
  chart.setDataContext({ symbol: 'SBIN', exchange: 'NSE', interval: '1m' })
  const price = chart.addSeries('candlestick')
  price.setData(bars)
  return { chart, container }
}

beforeEach(() => {
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
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('saved price scale settings', () => {
  it('has every new level off and the scale on the right by default', () => {
    for (const kind of HOST_LEVELS) expect(PRICE_AXIS_DEFAULTS[levelKey(kind)]).toBe('off')
    expect(PRICE_AXIS_DEFAULTS[AXIS_SIDE_KEY]).toBe('right')
  })

  it('owns only its own keys, never an engine setting', () => {
    expect(isPriceAxisSetting('levels.bid')).toBe(true)
    expect(isPriceAxisSetting(AXIS_SIDE_KEY)).toBe(true)
    expect(isPriceAxisSetting('scales.mode')).toBe(false)
    expect(isPriceAxisSetting('symbol.priceLineVisible')).toBe(false)
  })

  it('reads anything it does not recognise as off', () => {
    expect(levelShow({}, 'bid')).toBe('off')
    expect(levelShow({ 'levels.bid': 'sideways' }, 'bid')).toBe('off')
    expect(levelShow({ 'levels.bid': true }, 'bid')).toBe('off')
    expect(levelShow({ 'levels.bid': 'tag' }, 'bid')).toBe('tag')
  })

  it('switches the line and the tag of a level independently', () => {
    expect(levelPatch({}, 'previousClose', 'line', true)).toEqual({
      'levels.previousClose': 'line',
    })
    expect(levelPatch({ 'levels.previousClose': 'line' }, 'previousClose', 'tag', true)).toEqual({
      'levels.previousClose': 'both',
    })
    expect(levelPatch({ 'levels.previousClose': 'both' }, 'previousClose', 'line', false)).toEqual({
      'levels.previousClose': 'tag',
    })
    expect(levelPatch({ 'levels.previousClose': 'tag' }, 'previousClose', 'tag', false)).toEqual({
      'levels.previousClose': 'off',
    })
  })
})

describe('the settings dialog', () => {
  const view = (tabs: ChartSettingsRequest['tabs']): ChartSettingsRequest => ({
    tabs,
    values: { 'scales.mode': 'linear' },
    defaults: { 'scales.mode': 'linear' },
  })

  it('adds the scale position and the levels to the Axes tab', () => {
    const out = priceAxisSettingsView(
      view([
        {
          id: 'axes',
          label: 'Axes',
          inputs: [{ key: 'scales.mode', type: 'select', label: 'Scale' }],
        },
      ]),
      { 'levels.sessionHigh': 'both', [AXIS_SIDE_KEY]: 'left' }
    )
    const keys = out.tabs[0].inputs.map((input) => input.key)
    expect(keys[0]).toBe('scales.mode')
    expect(keys).toContain(AXIS_SIDE_KEY)
    for (const kind of HOST_LEVELS) expect(keys).toContain(levelKey(kind))
    expect(out.values['levels.sessionHigh']).toBe('both')
    expect(out.values['levels.bid']).toBe('off')
    expect(out.values[AXIS_SIDE_KEY]).toBe('left')
    expect(out.defaults['levels.sessionHigh']).toBe('off')
    expect(out.defaults['scales.mode']).toBe('linear')
  })

  it('makes an Axes tab when the engine has none', () => {
    const out = priceAxisSettingsView(view([{ id: 'price', label: 'Price', inputs: [] }]), {})
    expect(out.tabs.map((tab) => tab.id)).toEqual(['price', 'axes'])
  })
})

describe('keyboard chords', () => {
  const combos = () => priceAxisShortcuts(() => {}).flatMap((s) => [s.combos].flat())

  it('binds the six chords by key position', () => {
    expect(combos().sort()).toEqual(
      ['Alt+Digit1', 'Alt+KeyA', 'Alt+KeyI', 'Alt+KeyL', 'Alt+KeyP', 'Alt+KeyR'].sort()
    )
  })

  it('takes no chord the chart, its alternate preset or a drawing tool already uses', () => {
    const taken = new Set([
      ...DEFAULT_KEYMAP.flatMap((entry) => entry.combos),
      ...Object.values(ALT_PRESET).flat(),
      // The drawing tools' own chords, which the draw tier answers.
      ...['Alt+KeyC', 'Alt+KeyH', 'Alt+KeyJ', 'Alt+KeyT', 'Alt+KeyV'],
    ])
    for (const combo of combos()) expect(taken.has(combo)).toBe(false)
  })

  it('does nothing while a field, a dialog or the order ticket has the keyboard', () => {
    const run = vi.fn()
    const [autoFit] = priceAxisShortcuts(run)
    autoFit.onTrigger()
    expect(run).toHaveBeenCalledTimes(1)

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    expect(keyboardOwnedElsewhere(document)).toBe(true)
    autoFit.onTrigger()
    expect(run).toHaveBeenCalledTimes(1)
    input.remove()

    const ticket = document.createElement('div')
    ticket.setAttribute('role', 'dialog')
    ticket.setAttribute('data-state', 'open')
    document.body.appendChild(ticket)
    autoFit.onTrigger()
    expect(run).toHaveBeenCalledTimes(1)
    ticket.remove()

    const settings = document.createElement('div')
    settings.dataset.tradingDialogOpen = 'true'
    document.body.appendChild(settings)
    expect(keyboardOwnedElsewhere(document)).toBe(true)
    settings.remove()

    expect(keyboardOwnedElsewhere(document)).toBe(false)
  })
})

describe('commands as settings patches', () => {
  it('toggles a mode from the keyboard and goes back to linear on a second press', () => {
    const { chart } = chartOf(TWO_SESSIONS)
    expect(priceAxisPatch({ type: 'toggleMode', mode: 'logarithmic' }, chart, {})).toEqual({
      'scales.mode': 'logarithmic',
    })
    chart.setPriceScaleOptions({ mode: 'logarithmic' })
    expect(priceAxisPatch({ type: 'toggleMode', mode: 'logarithmic' }, chart, {})).toEqual({
      'scales.mode': 'linear',
    })
    chart.destroy()
  })

  it('resets to a linear scale, the right way up, fitted to the data', () => {
    const { chart } = chartOf(TWO_SESSIONS)
    expect(priceAxisPatch({ type: 'reset' }, chart, {})).toEqual({
      'scales.mode': 'linear',
      'scales.inverted': false,
      'scales.autoScale': true,
    })
    expect(priceAxisPatch({ type: 'invert' }, chart, {})).toEqual({ 'scales.inverted': true })
    expect(priceAxisPatch({ type: 'autoFit' }, chart, {})).toEqual({ 'scales.autoScale': false })
    chart.destroy()
  })

  it('writes the last price to the series pair the chart already keeps', () => {
    const { chart } = chartOf(TWO_SESSIONS)
    expect(
      priceAxisPatch({ type: 'level', kind: 'lastPrice', half: 'line', on: false }, chart, {})
    ).toEqual({ 'symbol.priceLineVisible': false, 'symbol.lastValueVisible': true })
    expect(
      priceAxisPatch({ type: 'level', kind: 'bid', half: 'tag', on: true }, chart, {})
    ).toEqual({ 'levels.bid': 'tag' })
    chart.destroy()
  })
})

describe('the levels on a chart', () => {
  it('attaches the levels only while one is on', () => {
    const { chart } = chartOf(TWO_SESSIONS)
    const add = vi.spyOn(chart, 'addPrimitive')
    const remove = vi.spyOn(chart, 'removePrimitive')
    const axis = new PriceAxisController()

    axis.sync(chart, {})
    expect(add).not.toHaveBeenCalled()

    axis.sync(chart, { 'levels.previousClose': 'both' })
    expect(add).toHaveBeenCalledTimes(1)
    const levels = add.mock.calls[0][0] as PriceLevels
    expect(levels).toBeInstanceOf(PriceLevels)
    expect(levels.level('previousClose')).toMatchObject({ line: true, label: true })
    // Nothing the host did not ask for: the engine's own default would draw
    // the previous close, and the pre and post market levels stay off.
    expect(levels.level('sessionHigh')).toMatchObject({ line: false, label: false })
    expect(levels.level('preMarketOpen')).toMatchObject({ line: false, label: false })
    expect(levels.level('lastPrice')).toMatchObject({ line: false, label: false })

    axis.sync(chart, { 'levels.previousClose': 'tag' })
    expect(add).toHaveBeenCalledTimes(1)
    expect(levels.level('previousClose')).toMatchObject({ line: false, label: true })

    axis.sync(chart, {})
    expect(remove).toHaveBeenCalledWith(levels)
    chart.destroy()
  })

  it('reads the levels as the menu shows them, greyed where there is no data', () => {
    const { chart } = chartOf(TWO_SESSIONS)
    const axis = new PriceAxisController()
    const byKind = () =>
      Object.fromEntries(axis.menu(chart, {}).levels.map((level) => [level.kind, level]))

    let levels = byKind()
    expect(levels.lastPrice).toMatchObject({ available: true, line: true, tag: true })
    expect(levels.previousClose.available).toBe(true)
    expect(levels.sessionHigh.available).toBe(true)
    // No order book yet: the bid and ask say so instead of drawing a guess.
    expect(levels.bid.available).toBe(false)
    expect(levels.ask.available).toBe(false)

    axis.setQuote(110.5, 110.6)
    levels = byKind()
    expect(levels.bid.available).toBe(true)
    expect(levels.ask.available).toBe(true)

    // A side the book does not quote is no data, never a line at zero.
    axis.setQuote(0, 110.6)
    levels = byKind()
    expect(levels.bid.available).toBe(false)
    expect(levels.ask.available).toBe(true)
    chart.destroy()
  })

  it('has no previous close when only one session is loaded', () => {
    const { chart } = chartOf(minutes(MONDAY, [100, 101, 102]))
    const axis = new PriceAxisController()
    const previous = axis.menu(chart, {}).levels.find((level) => level.kind === 'previousClose')
    expect(previous?.available).toBe(false)
    chart.destroy()
  })

  it('draws no bid or ask while the chart is not showing the live market', () => {
    const { chart } = chartOf(TWO_SESSIONS)
    let live = true
    const axis = new PriceAxisController(() => live)
    axis.setQuote(110.5, 110.6)
    const bid = () => axis.menu(chart, {}).levels.find((level) => level.kind === 'bid')
    expect(bid()?.available).toBe(true)
    live = false
    expect(bid()?.available).toBe(false)
    chart.destroy()
  })

  it('moves the price scale to the side saved, and back', () => {
    const { chart } = chartOf(TWO_SESSIONS)
    const axis = new PriceAxisController()
    axis.sync(chart, { [AXIS_SIDE_KEY]: 'left' })
    expect(chart.priceAxisPlacement(chart.primaryPaneIndex(), 'right')?.side).toBe('left')
    expect(axis.menu(chart, { [AXIS_SIDE_KEY]: 'left' }).side).toBe('left')
    axis.sync(chart, {})
    expect(chart.priceAxisPlacement(chart.primaryPaneIndex(), 'right')?.side).toBe('right')
    chart.destroy()
  })
})

describe('right-clicking the price scale', () => {
  it('is reported by the chart as the price scale, so the scale menu opens', () => {
    const { chart, container } = chartOf(TWO_SESSIONS)
    const seen: ContextMenuEvent[] = []
    chart.on('contextmenu', (event) => {
      const e = event as ContextMenuEvent
      e.preventDefault()
      seen.push(e)
    })
    const right = chart.priceAxisLayout(0).find((slot) => slot.side === 'right')
    expect(right).toBeDefined()
    container.dispatchEvent(
      new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        clientX: (right?.x ?? 790) + 5,
        clientY: 300,
      })
    )
    expect(seen).toHaveLength(1)
    expect(seen[0].target.kind).toBe('price-scale')
    chart.destroy()
  })
})

describe('auto-fit off, restored', () => {
  it('waits for a measured scale before pinning it, so the chart is never blank', () => {
    let scaled = false
    const setAutoScale = vi.fn()
    const chart = {
      primaryPaneIndex: () => 0,
      priceAxisState: () =>
        ({ scaled }) as ReturnType<Parameters<typeof pinOnceMeasured>[0]['priceAxisState']>,
      setAutoScale,
    }
    const frames: (() => void)[] = []
    pinOnceMeasured(
      chart,
      () => true,
      (cb) => frames.push(cb)
    )
    expect(setAutoScale).not.toHaveBeenCalled()
    frames.shift()?.()
    expect(setAutoScale).not.toHaveBeenCalled()
    scaled = true
    frames.shift()?.()
    expect(setAutoScale).toHaveBeenCalledWith(false)
    expect(frames).toHaveLength(0)
  })

  it('gives up if the chart goes first', () => {
    const setAutoScale = vi.fn()
    const chart = {
      primaryPaneIndex: () => 0,
      priceAxisState: () => null,
      setAutoScale,
    }
    let alive = true
    const frames: (() => void)[] = []
    pinOnceMeasured(
      chart,
      () => alive,
      (cb) => frames.push(cb)
    )
    alive = false
    frames.shift()?.()
    expect(frames).toHaveLength(0)
    expect(setAutoScale).not.toHaveBeenCalled()
  })
})
