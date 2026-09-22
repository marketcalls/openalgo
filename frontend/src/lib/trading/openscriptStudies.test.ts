/**
 * Which saved scripts reach the chart's indicator list, and how.
 *
 * **Every saved script reaches it, including a strategy.** A strategy has
 * plots, a title and settings exactly as a study does, and a trader who saved
 * one should find it where they look for it. What differs is the destination:
 * a program needing `orders` is refused by the engine at load with OS6006
 * unless it is given one, so it is run against the language's own simulated
 * venue. Nothing here can place an order; the chart has no route to the
 * platform and is given none.
 *
 * Each test names the wrong implementation it catches.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const registerIndicator = vi.fn()
vi.mock('openalgo-charts', () => ({ registerIndicator }))

const descriptorFor = vi.fn(() => ({ id: 'probe', plots: [] }))
vi.mock('openalgo-script/adapters/charts', () => ({ descriptorFor }))

/** A compiled program carrying whatever capability tags a test needs. */
let requires: string[] = ['core.1']
vi.mock('openalgo-script', () => ({
  sourceFile: () => ({}),
  lex: () => [],
  parseTokens: () => ({}),
  check: () => ({}),
  emit: () => ({ program: { requires } }),
  DiagnosticBag: class {
    ordered() {
      return []
    }
  },
  renderDiagnostics: () => '',
}))

const { forgetOpenScriptStudies, loadOpenScriptStudies } = await import('./openscriptStudies')

/** The server: an index of one script, then its source. */
function serving(file: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      String(url).includes('index.json')
        ? { ok: true, json: async () => [{ file, mtime: 1 }] }
        : { ok: true, text: async () => 'version 1\nstudy("s")\n' }
    )
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  forgetOpenScriptStudies()
  requires = ['core.1']
})

describe('what reaches the chart', () => {
  it('registers a program the chart tier can run', async () => {
    requires = ['core.1', 'arrays', 'alerts']
    serving('a-study.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.loaded).toEqual(['a-study.oscript'])
    expect(out.errors).toEqual([])
    expect(registerIndicator).toHaveBeenCalledTimes(1)
  })

  it('registers a strategy, with a destination it can safely have', async () => {
    // THE ONE THAT MATTERS. A strategy has plots, a title and settings exactly
    // as a study does, and none of them reached the chart: a trader who saved
    // one could not find it in the indicator list, so its lines had to come
    // from a separate study kept in step by hand.
    //
    // `simulateOrders` is what makes registering it safe. Without it the engine
    // refuses a program that places orders (OS6006), and with a destination
    // that answered nothing it would run while never learning it holds a
    // position: every close closing nothing, and the plots wrong wherever they
    // read one.
    requires = ['core.1', 'orders']
    serving('a-strategy.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.loaded).toEqual(['a-strategy.oscript'])
    expect(registerIndicator).toHaveBeenCalledTimes(1)
    expect(descriptorFor.mock.calls[0][1]).toMatchObject({ simulateOrders: true })
  })

  it('never asks for a destination for a study', async () => {
    // Catches the option passed to everything. A study places no orders, so a
    // venue for it is a thing built and never used, and an option set where it
    // has no meaning is the next reader's question.
    requires = ['core.1']
    serving('a-study.oscript')

    await loadOpenScriptStudies()

    expect(descriptorFor.mock.calls[0][1].simulateOrders).toBeUndefined()
  })

  it('reports a strategy as loaded and never as an error', async () => {
    requires = ['core.1', 'orders']
    serving('a-strategy.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.errors).toEqual([])
    expect(out.loaded).toEqual(['a-strategy.oscript'])
  })

  it('reads the requirement off the program, not off the word in the source', async () => {
    // Catches a filter written against `strategy(` in the text. `requires` is
    // the same fact the engine tests, so a strategy placing no orders would be
    // drawable and this must follow the program rather than the keyword.
    requires = ['core.1']
    serving('declares-strategy-but-orders-nothing.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.loaded).toHaveLength(1)
    // The name says strategy and the program places nothing, so no venue is
    // built for it. A filter written against the text would get this backwards.
    expect(descriptorFor.mock.calls[0][1].simulateOrders).toBeUndefined()
  })
})
