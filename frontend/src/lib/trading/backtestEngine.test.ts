/**
 * The panel's settings against a real engine, with nothing mocked.
 *
 * **Why this file exists.** Every other test around the backtest replaces
 * `openalgo-script` with a mock, which is right for testing the panel's own
 * decisions and useless for testing what the engine accepts: a mock takes any
 * shape handed to it. The settings map was built in the language's tagged form
 * for months, every unit test agreed with it, and a real engine refused every
 * run that carried one. The tests were the reason nobody noticed.
 *
 * So this compiles a real script, runs a real backtest, and asserts on what
 * came back. It is slower than the rest and there is deliberately little of it:
 * one case per thing an engine can reject a host's settings for.
 */

import { describe, expect, it } from 'vitest'
import { inputsOf, settingsFromForm } from './backtestInputs'

/** A strategy whose slow leg is an input, so a setting visibly changes the run. */
const SOURCE = `//@version=1
len = input(8, "Slow", min = 2, max = 50)
strategy("engine probe", qty = 2)
fast = ema(close, 3)
slow = ema(close, len)
if crossUp(fast, slow)
    buy(tag = "long")
if crossDown(fast, slow)
    close(tag = "long")
`

/** A wave, so the two averages cross repeatedly and trades actually happen. */
function bars(count = 200) {
  const start = 1_700_000_000_000
  return Array.from({ length: count }, (_, at) => {
    const price = 100 + Math.sin(at / 4) * 8
    return {
      time: start + at * 60_000,
      open: price,
      high: price + 0.5,
      low: price - 0.5,
      close: price,
      volume: 10,
      oi: null,
    }
  })
}

async function engine() {
  return await import('openalgo-script')
}

async function compiled() {
  const { sourceFile, lex, parseTokens, check, emit, DiagnosticBag } = await engine()
  const bag = new DiagnosticBag()
  const handle = sourceFile('probe.oscript', SOURCE)
  const checked = check(handle, parseTokens(handle, lex(handle, bag), bag), bag)
  const program = emit(handle, checked, bag, {}).program
  if (program === undefined) {
    throw new Error(
      `the probe script did not compile: ${bag
        .ordered()
        .map((one) => `${one.code} ${one.message}`)
        .join('; ')}`
    )
  }
  return program
}

async function runWith(inputs: Record<string, unknown>) {
  const { backtest, settingsFor } = await engine()
  const base = settingsFor({
    currency: 'INR',
    symbol: 'AAA',
    exchange: 'XX',
    tickSize: 0.05,
    lotSize: 1,
    pointValue: 1,
    digits: 2,
  })
  return backtest(
    await compiled(),
    bars() as never,
    { ...base, inputs: inputs as typeof base.inputs },
    {}
  )
}

/** The declarations as the panel reads them off a real compiled program. */
async function declarations() {
  return inputsOf(await compiled())
}

describe('the settings the panel builds, against a real engine', () => {
  it('runs what the form produced rather than refusing it', async () => {
    // THE DEFECT. `settingsFromForm` produced the language's tagged value, which
    // an engine refuses with OS6019 because it validates a supplied setting
    // against a declaration that already states the kind. Every run carrying an
    // input a trader had typed was refused, and no mock could see it.
    const sent = settingsFromForm(await declarations(), { len: '20' })
    const out = await runWith(sent)

    expect(out.ok).toBe(true)
  })

  it('actually applies the value, so a setting is not quietly ignored', async () => {
    // Half of the above and the half a weaker test would miss: a run that
    // accepted the map and resolved every declaration's default would answer
    // ok and report the script's own numbers. Two different values have to
    // produce two different runs for the setting to have been read at all.
    const declared = await declarations()
    const slow = await runWith(settingsFromForm(declared, { len: '40' }))
    const quick = await runWith(settingsFromForm(declared, { len: '4' }))

    expect(slow.ok && quick.ok).toBe(true)
    if (!slow.ok || !quick.ok) return
    expect(slow.record.report.trades.length).not.toBe(quick.record.report.trades.length)
  })

  it('leaves an untouched input on the script default', async () => {
    const declared = await declarations()
    const untouched = await runWith(settingsFromForm(declared, {}))
    const stated = await runWith(settingsFromForm(declared, { len: '8' }))

    expect(untouched.ok && stated.ok).toBe(true)
    if (!untouched.ok || !stated.ok) return
    expect(untouched.record.report.trades.length).toBe(stated.record.report.trades.length)
  })

  it('never sends a value the script declared out of bounds', async () => {
    // The panel drops it, so what reaches the engine is a run on the default
    // rather than a refusal. A trader who typed past the maximum sees the field
    // not take it, not a run that would not start.
    const sent = settingsFromForm(await declarations(), { len: '500' })

    expect(sent).toEqual({})
    expect((await runWith(sent)).ok).toBe(true)
  })
})

describe('what a report says about a position still open', () => {
  it('marks the trade it has not closed, which is what live tracking reads', async () => {
    // The open position is not a separate channel: it is the last trade with
    // `isOpen` set. A panel that tracked a position by re-deriving it from the
    // fills would be a second opinion about what the engine already decided.
    const out = await runWith({})
    expect(out.ok).toBe(true)
    if (!out.ok) return

    const report = out.record.report
    const open = report.trades.filter((one) => one.isOpen)

    expect(open.length).toBe(report.summary.openTradeCount)
    for (const trade of open) {
      expect(trade.units).toBeGreaterThan(0)
      expect(Number.isFinite(trade.entryPrice)).toBe(true)
    }
  })
})
