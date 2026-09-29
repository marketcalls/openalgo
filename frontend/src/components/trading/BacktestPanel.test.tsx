/**
 * What the backtest panel tells a trader about a run that did not go the whole way.
 *
 * The run itself is replaced here, because what is under test is the panel's
 * reading of an outcome, not the engine. `backtestSession.test.ts` holds the
 * engine to producing these outcomes for real.
 */

import { describe, expect, it, vi } from 'vitest'
import type { BacktestOutcome } from '@/lib/trading/backtestRun'
import { cleanup, render, screen } from '@/test/test-utils'

const runBacktest = vi.fn()
vi.mock('@/lib/trading/backtestRun', () => ({
  MAX_BARS: 100000,
  runBacktest: (...args: unknown[]) => runBacktest(...args),
}))

vi.mock('@/lib/trading/openscriptFiles', () => ({
  listScripts: async () => [{ file: 'probe.oscript', mtime: 1, bytes: 1 }],
  readScript: async () => 'version 1\nstrategy("probe")\n',
  kindOf: async () => 'strategy',
  compileSource: async () => ({ ok: false, diagnostics: [] }),
}))

vi.mock('@/hooks/useLivePrice', () => ({
  useLivePrice: () => ({ data: [], isLive: false }),
}))

// A canvas chart, which has nothing to say about either of these.
vi.mock('./BacktestChart', () => ({ BacktestChart: () => null }))

const { BacktestPanel } = await import('./BacktestPanel')

/** A run that reached bar 18 of 85 and was stopped there by a refused entry. */
function stoppedRun(extra: Partial<BacktestOutcome> = {}): BacktestOutcome {
  return {
    ok: true,
    summary: { netProfit: 0, returnPercent: 0, tradeCount: 1, openTradeCount: 1 },
    trades: [],
    equity: [],
    markers: [],
    barCount: 85,
    ranMs: 3,
    contract: {
      currency: 'INR',
      symbol: 'AAA',
      exchange: 'XX',
      tickSize: 0.05,
      lotSize: 1,
      pointValue: 1,
      digits: 2,
      usedFallback: false,
    },
    instrument: {
      interval: '30m',
      timezone: 'UTC',
      session: { start: '09:00', end: '17:30', days: [1, 2, 3, 4, 5] },
      hasVolume: true,
    },
    stopped: {
      code: 'OS7008',
      title: 'The entry was refused by pyramiding',
      fix: 'Raise pyramiding in the declaration, or test pos.size before entering again.',
      line: 4,
      column: 5,
      barIndex: 17,
      barTime: Date.UTC(2026, 8, 15, 9, 0),
    },
    ...extra,
  }
}

function openPanel() {
  render(
    <BacktestPanel
      apiKey="key"
      getChartContext={() => ({ symbol: 'AAA', exchange: 'XX', interval: '30m' })}
    />
  )
}

describe('a run the script stopped part way', () => {
  it('says where it stopped, why, and what to do about it', async () => {
    // THE SILENT STOP. The record said which order was refused and on which
    // bar, and the panel showed a report of fewer trades with no word about
    // it, which reads as a strategy that found little to do.
    runBacktest.mockResolvedValue(stoppedRun())

    openPanel()

    const heading = await screen.findByText(/This run stopped on bar 18 of 85/)
    // The bar's own time, in the zone the run read its clock in.
    expect(heading.textContent).toMatch(/09:00/)
    expect(heading.textContent).toMatch(/2026/)
    expect(
      screen.getByText(
        'The entry was refused by pyramiding. Raise pyramiding in the declaration, or test pos.size before entering again.'
      )
    ).toBeInTheDocument()
    expect(screen.getByText('4:5 OS7008')).toBeInTheDocument()
    expect(screen.getByText(/are of the run up to that bar/)).toBeInTheDocument()
  })
})

describe('a run with no trading hours', () => {
  it('says the session was empty, and only when it was', async () => {
    // A session strategy with no hours to read never trades, and its report is
    // indistinguishable from one that found nothing to do.
    runBacktest.mockResolvedValue(
      stoppedRun({ stopped: undefined, instrument: { interval: '30m' } })
    )
    openPanel()
    expect(await screen.findByText(/No trading hours were available/)).toBeInTheDocument()
    cleanup()

    runBacktest.mockResolvedValue(stoppedRun({ stopped: undefined }))
    openPanel()
    await screen.findByText(/85 bars/)
    expect(screen.queryByText(/No trading hours were available/)).not.toBeInTheDocument()
    expect(screen.queryByText(/This run stopped/)).not.toBeInTheDocument()
  })
})
