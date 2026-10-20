/**
 * What the backtest panel tells a trader about a run that did not go the whole way.
 *
 * The run itself is replaced here, because what is under test is the panel's
 * reading of an outcome, not the engine. `backtestSession.test.ts` holds the
 * engine to producing these outcomes for real.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { BacktestOutcome } from '@/lib/trading/backtestRun'
import { act, cleanup, render, screen } from '@/test/test-utils'

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
vi.mock('./BacktestChart', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./BacktestChart')>()),
  BacktestChart: () => null,
}))

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

describe('the marks a run puts on the chart', () => {
  beforeEach(() => localStorage.clear())

  function markedRun(): BacktestOutcome {
    return stoppedRun({
      stopped: undefined,
      markers: [{ time: Date.UTC(2026, 8, 15, 9, 0), kind: 'entry', side: 'buy', units: 1, price: 100 }],
    } as Partial<BacktestOutcome>)
  }

  function openWithMarks(onMarkChart: ReturnType<typeof vi.fn>) {
    return render(
      <BacktestPanel
        apiKey="key"
        getChartContext={() => ({ symbol: 'AAA', exchange: 'XX', interval: '30m' })}
        onMarkChart={onMarkChart}
      />
    )
  }

  it('ties the marks to the strategy, and clears them from the button', async () => {
    runBacktest.mockResolvedValue(markedRun())
    const onMarkChart = vi.fn(() => true)
    openWithMarks(onMarkChart)

    const clear = await screen.findByRole('button', { name: /Clear marks/ })
    const [marks, owner] = onMarkChart.mock.calls[0] as unknown as [unknown[], { file: string }]
    expect(marks.length).toBeGreaterThan(0)
    expect(owner.file).toBe('probe.oscript')

    await act(async () => clear.click())
    expect(onMarkChart).toHaveBeenLastCalledWith([])
    expect(screen.queryByRole('button', { name: /Clear marks/ })).toBeNull()
  })

  it('stops counting the marks once removing the strategy took them down', async () => {
    runBacktest.mockResolvedValue(markedRun())
    const onMarkChart = vi.fn(() => true)
    openWithMarks(onMarkChart)
    await screen.findByRole('button', { name: /Clear marks/ })

    const [, owner] = onMarkChart.mock.calls[0] as unknown as [unknown[], { onCleared(): void }]
    await act(async () => owner.onCleared())
    expect(screen.queryByText(/fills marked on the chart/)).toBeNull()
  })

  it('shows the count on the button beside Run backtest', async () => {
    runBacktest.mockResolvedValue(markedRun())
    openWithMarks(vi.fn(() => true))
    expect(await screen.findByRole('button', { name: 'Clear marks (1)' })).toBeInTheDocument()
  })

  it('draws nothing on the chart with the switch off, and remembers it', async () => {
    runBacktest.mockResolvedValue(markedRun())
    const onMarkChart = vi.fn(() => true)
    const first = openWithMarks(onMarkChart)
    await screen.findByRole('button', { name: /Clear marks/ })

    const toggle = screen.getByRole('checkbox', { name: 'Show trades on chart' })
    await act(async () => toggle.click())
    expect(onMarkChart).toHaveBeenLastCalledWith([])
    expect(screen.queryByRole('button', { name: /Clear marks/ })).toBeNull()
    first.unmount()

    // The next panel, and its automatic run, keep the chart clean.
    onMarkChart.mockClear()
    openWithMarks(onMarkChart)
    expect(await screen.findByRole('checkbox', { name: 'Show trades on chart' })).not.toBeChecked()
    await screen.findByText(/bars, /)
    expect(onMarkChart.mock.calls.every(([marks]) => (marks as unknown[]).length === 0)).toBe(true)
  })

  it('puts the marks back when the switch is turned on, without running again', async () => {
    localStorage.setItem('trading.panel.backtest.marks', 'off')
    runBacktest.mockResolvedValue(markedRun())
    const onMarkChart = vi.fn(() => true)
    openWithMarks(onMarkChart)
    await screen.findByText(/bars, /)
    const runs = runBacktest.mock.calls.length

    await act(async () => screen.getByRole('checkbox', { name: 'Show trades on chart' }).click())
    const [marks] = onMarkChart.mock.calls.at(-1) as unknown as [unknown[]]
    expect(marks.length).toBe(1)
    expect(runBacktest.mock.calls.length).toBe(runs)
    expect(await screen.findByRole('button', { name: 'Clear marks (1)' })).toBeInTheDocument()
  })

  it('takes its marks off the chart when the panel closes', async () => {
    runBacktest.mockResolvedValue(markedRun())
    const onMarkChart = vi.fn(() => true)
    const view = openWithMarks(onMarkChart)
    await screen.findByRole('button', { name: /Clear marks/ })

    view.unmount()
    expect(onMarkChart).toHaveBeenLastCalledWith([])
  })
})
