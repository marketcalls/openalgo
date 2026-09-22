/**
 * Which saved scripts reach the chart's indicator list, and which do not.
 *
 * The chart tier draws and does not trade. A program that needs `orders` is
 * refused by the engine at load with OS6006, a sentence about capability tags
 * shown to a trader who pressed a button in a list, so such a program must
 * never reach the list in the first place.
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
    expect(out.skipped).toEqual([])
    expect(registerIndicator).toHaveBeenCalledTimes(1)
  })

  it('does not register a program that needs orders', async () => {
    // THE ONE THAT MATTERS. Registered, the strategy appears in the indicator
    // list, a trader adds it, and the engine refuses at load with OS6006. The
    // button worked and the error is about capability tags.
    requires = ['core.1', 'orders']
    serving('a-strategy.oscript')

    const out = await loadOpenScriptStudies()

    expect(registerIndicator).not.toHaveBeenCalled()
    expect(out.loaded).toEqual([])
    expect(out.skipped).toEqual([{ file: 'a-strategy.oscript', needs: 'orders' }])
  })

  it('records the skip as a skip and never as an error', async () => {
    // Catches a strategy reported as a failure. Nothing went wrong: the trader
    // saved a strategy, and this is the chart asking which scripts it can draw.
    requires = ['core.1', 'orders']
    serving('a-strategy.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.errors).toEqual([])
  })

  it('reads the requirement off the program, not off the word in the source', async () => {
    // Catches a filter written against `strategy(` in the text. `requires` is
    // the same fact the engine tests, so a strategy placing no orders would be
    // drawable and this must follow the program rather than the keyword.
    requires = ['core.1']
    serving('declares-strategy-but-orders-nothing.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.loaded).toHaveLength(1)
    expect(out.skipped).toEqual([])
  })
})
