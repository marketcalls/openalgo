/**
 * Delete and Backspace over the chart.
 *
 * The feature is small and the order is the whole of it. A drawing, a
 * half-placed drawing, a selection and an alert can all be true at the same
 * moment, and pressing Delete again does not undo having deleted the wrong one.
 *
 * An alert's line runs the width of the pane, so it is under the pointer far
 * more often than any shape is. That is why it comes last, and why most of
 * these tests are about something else winning.
 */
import type { AlertController, Bar, Chart, SeriesApi } from 'openalgo-charts'
import type { DrawingController } from 'openalgo-charts/draw'
import 'openalgo-charts/indicators'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'

type State = {
  chart: Chart
  price: SeriesApi
  draw: DrawingController
  alerts: AlertController
  chartToolsReady: Promise<void>
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  buildChart(): void
  loadIndicators(): Promise<void>
}

const bar = (time: number, close: number): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
})

const terminals: TradingTerminal[] = []

beforeEach(() => {
  localStorage.clear()
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
  vi.restoreAllMocks()
})

async function mount() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container,
    legendEl: document.createElement('div'),
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast() {},
      onContextMenu() {},
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
  state.loadIndicators = async () => {}
  state.sym = {
    symbol: 'NIFTY29SEP26FUT',
    exchange: 'NFO',
    name: 'Nifty Futures',
    lotsize: 65,
    lots: true,
    tick: 0.05,
    freezeQty: 1800,
    quoteOnly: false,
    productOptions: ['MIS', 'NRML'],
    product: 'MIS',
  }
  state.interval = '1m'
  state.rawBars = [bar(60, 100), bar(120, 100), bar(180, 100), bar(240, 100)]
  state.buildChart()
  await state.chartToolsReady
  // Forces the drawing tier to load and attach, which is what gives the
  // terminal a `draw` controller to consult.
  await terminal.setDrawTool(null)
  return { terminal, state, container }
}

/** What is under the pointer, as the two controllers would report it. */
function pointingAt(
  state: State,
  what: {
    tool?: string | null
    selection?: string[]
    drawing?: string | null
    alert?: string | undefined
  }
) {
  vi.spyOn(state.draw, 'activeTool').mockReturnValue(what.tool ?? null)
  vi.spyOn(state.draw, 'selection').mockReturnValue(what.selection ?? [])
  vi.spyOn(state.draw, 'hovered').mockReturnValue(what.drawing ?? null)
  vi.spyOn(state.alerts, 'hovered').mockReturnValue(what.alert)
  return {
    cancel: vi.spyOn(state.draw, 'cancel').mockReturnValue(true),
    removeMany: vi.spyOn(state.draw, 'removeMany').mockImplementation(() => {}),
    removeAlert: vi.spyOn(state.alerts, 'remove').mockImplementation(() => true as never),
  }
}

function hover(container: HTMLElement) {
  container.dispatchEvent(new Event('pointerenter'))
}

/**
 * A keystroke with nothing focused, which a browser delivers to the body and
 * bubbles to the document. Dispatching straight at the document instead would
 * hand the handler a target that is not an element, which is a case worth
 * covering but not the ordinary one.
 */
function press(key = 'Delete', init: KeyboardEventInit = {}) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  document.body.dispatchEvent(event)
  return event
}

describe('what Delete removes, and in what order', () => {
  it('removes the alert under the pointer when nothing else claims the key', async () => {
    const { state, container } = await mount()
    const spies = pointingAt(state, { alert: 'alert-1' })
    hover(container)

    press()

    expect(spies.removeAlert).toHaveBeenCalledWith('alert-1')
  })

  it('removes a selected drawing rather than the alert under the pointer', async () => {
    // An alert line spans the pane, so it is under the pointer during most
    // drawing work. A selection is deliberate and visible; it wins.
    const { state, container } = await mount()
    const spies = pointingAt(state, { selection: ['draw-1'], alert: 'alert-1' })
    hover(container)

    press()

    expect(spies.removeMany).toHaveBeenCalledWith(['draw-1'])
    expect(spies.removeAlert).not.toHaveBeenCalled()
  })

  it('removes a hovered drawing rather than the alert under the pointer', async () => {
    const { state, container } = await mount()
    const spies = pointingAt(state, { drawing: 'draw-1', alert: 'alert-1' })
    hover(container)

    press()

    expect(spies.removeMany).toHaveBeenCalledWith(['draw-1'])
    expect(spies.removeAlert).not.toHaveBeenCalled()
  })

  it('cancels a drawing being placed instead of deleting anything', async () => {
    // Half a trend line is what the key is being pressed about. Deleting an
    // alert here would answer a question nobody asked.
    const { state, container } = await mount()
    const spies = pointingAt(state, {
      tool: 'trendline',
      selection: ['draw-1'],
      alert: 'alert-1',
    })
    hover(container)

    press()

    expect(spies.cancel).toHaveBeenCalled()
    expect(spies.removeMany).not.toHaveBeenCalled()
    expect(spies.removeAlert).not.toHaveBeenCalled()
  })

  it('takes Backspace as well as Delete', async () => {
    const { state, container } = await mount()
    const spies = pointingAt(state, { alert: 'alert-1' })
    hover(container)

    press('Backspace')

    expect(spies.removeAlert).toHaveBeenCalledWith('alert-1')
  })
})

describe('when the key is not the chart’s to take', () => {
  it('ignores a key pressed while the pointer is elsewhere', async () => {
    // Four panes in a workspace, and the key belongs to the one being pointed
    // at. Without this every chart on screen would answer at once.
    const { state } = await mount()
    const spies = pointingAt(state, { alert: 'alert-1' })

    press()

    expect(spies.removeAlert).not.toHaveBeenCalled()
  })

  it('stops answering once the pointer leaves', async () => {
    const { state, container } = await mount()
    const spies = pointingAt(state, { alert: 'alert-1' })
    hover(container)
    container.dispatchEvent(new Event('pointerleave'))

    press()

    expect(spies.removeAlert).not.toHaveBeenCalled()
  })

  it('leaves Backspace alone while something is being typed', async () => {
    // The dialog can sit over the chart, so the pointer being inside says
    // nothing about who owns the key. Erasing a character must not erase a
    // drawing.
    const { state, container } = await mount()
    const spies = pointingAt(state, { alert: 'alert-1', drawing: 'draw-1' })
    hover(container)

    const input = document.createElement('input')
    container.appendChild(input)
    input.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Backspace', bubbles: true, cancelable: true })
    )

    expect(spies.removeMany).not.toHaveBeenCalled()
    expect(spies.removeAlert).not.toHaveBeenCalled()
  })

  it('leaves a key with a modifier alone', async () => {
    // Cmd+Backspace is a text gesture, and Ctrl+Delete is somebody else's
    // shortcut.
    const { state, container } = await mount()
    const spies = pointingAt(state, { alert: 'alert-1' })
    hover(container)

    press('Backspace', { metaKey: true })
    press('Delete', { ctrlKey: true })

    expect(spies.removeAlert).not.toHaveBeenCalled()
  })

  it('leaves the key to the browser when it removed nothing', async () => {
    // A Backspace over an empty chart is still the browser's to interpret.
    const { state, container } = await mount()
    pointingAt(state, {})
    hover(container)

    expect(press().defaultPrevented).toBe(false)
  })

  it('claims the key only when something was actually removed', async () => {
    const { state, container } = await mount()
    pointingAt(state, { alert: 'alert-1' })
    hover(container)

    expect(press().defaultPrevented).toBe(true)
  })

  it('survives a keystroke delivered to the document rather than an element', async () => {
    // With nothing focused a browser can hand the handler a target that is not
    // an element, and it is exactly the press made without clicking first.
    // Assuming an element there throws on the most ordinary case there is.
    const { state, container } = await mount()
    const spies = pointingAt(state, { alert: 'alert-1' })
    hover(container)

    expect(() =>
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Delete', bubbles: true, cancelable: true })
      )
    ).not.toThrow()
    expect(spies.removeAlert).toHaveBeenCalledWith('alert-1')
  })

  it('takes its document listener away when the terminal is destroyed', async () => {
    // The listener is on the document rather than on the container, so nothing
    // collects it when the chart goes. A workspace opened and re-laid-out all
    // day would accumulate one per pane per rebuild, each holding a destroyed
    // terminal alive.
    //
    // Asserted on the listener itself, not on behaviour: a destroyed terminal
    // has no alert controller either, so "pressing Delete does nothing" is true
    // whether or not the listener was ever removed.
    const added = vi.spyOn(document, 'addEventListener')
    const removed = vi.spyOn(document, 'removeEventListener')

    const { terminal } = await mount()
    const registered = added.mock.calls.filter(([type]) => type === 'keydown').map(([, fn]) => fn)
    expect(registered).not.toHaveLength(0)

    terminal.destroy()

    const released = removed.mock.calls.filter(([type]) => type === 'keydown').map(([, fn]) => fn)
    for (const handler of registered) expect(released).toContain(handler)
  })
})
