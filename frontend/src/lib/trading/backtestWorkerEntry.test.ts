/**
 * The worker's own handler, driven the way the browser drives it.
 *
 * The page cannot see what the worker hands the engine: it posts a message and
 * reads a reply. So a worker that dropped a field from the message would answer
 * a normal looking report for a different run, and nothing on the page could
 * tell. This calls the handler the module installs and looks at the engine call
 * it made.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BacktestMessage } from './backtestWorkerProtocol'

const backtest = vi.fn()
const settingsFor = vi.fn((contract: unknown) => ({ contract, inputs: {} }))
vi.mock('openalgo-script', () => ({
  backtest: (...args: unknown[]) => backtest(...args),
  settingsFor: (contract: unknown) => settingsFor(contract),
  isDiagnosticCode: () => false,
}))

// Installs `self.onmessage`, as it does in a real worker.
await import('./backtestWorkerEntry')

const MESSAGE: BacktestMessage = {
  program: { openscript: {} },
  bars: [{ time: 1_700_000_000_000, open: 1, high: 1, low: 1, close: 1, volume: 1, oi: null }],
  contract: {
    currency: 'INR',
    symbol: 'AAA',
    exchange: 'XX',
    tickSize: 0.05,
    lotSize: 1,
    pointValue: 1,
    digits: 2,
  },
  inputs: {},
  instrument: {
    interval: '1D',
    timezone: 'Asia/Kolkata',
    session: { start: '09:00', end: '17:00', days: [1, 2, 3, 4, 5] },
    hasVolume: true,
  },
}

const report = { summary: { netProfit: 1 }, trades: [], equity: [], markers: [] }

let posted: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
  posted = vi.fn()
  vi.spyOn(self, 'postMessage').mockImplementation(posted as never)
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function deliver(message: BacktestMessage): Promise<void> {
  const handler = self.onmessage as unknown as (event: { data: BacktestMessage }) => Promise<void>
  await handler({ data: message })
}

describe('the worker', () => {
  it('hands the engine the instrument facts from the message', async () => {
    // THE DEFECT. The worker called the engine with empty options, so a run on
    // a worker had no interval, zone or session whatever the page had read.
    backtest.mockReturnValue({ ok: true, record: { report, diagnostics: [] } })

    await deliver(MESSAGE)

    expect(backtest).toHaveBeenCalledTimes(1)
    expect(backtest.mock.calls[0][3]).toEqual({ instrument: MESSAGE.instrument })
  })

  it('answers the report and says the run was not stopped', async () => {
    backtest.mockReturnValue({ ok: true, record: { report, diagnostics: [] } })

    await deliver(MESSAGE)

    expect(posted).toHaveBeenCalledWith(
      expect.objectContaining({ ok: true, stopped: null, report: expect.any(Object) })
    )
  })
})
