/**
 * The equity, drawdown and trades tabs under a backtest's figures.
 *
 * The chart itself is a canvas library, so it is replaced by a probe that says
 * which curve it was asked for; `BacktestChart.test.ts` holds what it is fed.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { BacktestOutcome } from '@/lib/trading/backtestRun'
import { render, screen, userEvent } from '@/test/test-utils'

vi.mock('./BacktestChart', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./BacktestChart')>()),
  BacktestChart: ({ show }: { show: string }) => <div data-testid="curve">{show}</div>,
}))

const { BacktestResultTabs } = await import('./BacktestResultTabs')

const money = (value: unknown) => Number(value).toFixed(2)

function outcome(extra: Partial<BacktestOutcome> = {}): BacktestOutcome {
  const at = (minute: number) => Date.UTC(2026, 8, 15, 9, minute)
  return {
    ok: true,
    equity: [
      { time: at(0), equity: 100000, drawdown: 0 },
      { time: at(1), equity: 99500, drawdown: -500 },
      { time: at(2), equity: 100800, drawdown: 0 },
    ],
    trades: [
      { index: 0, side: 'long', entryPrice: 100, exitPrice: 105, netProfit: 5 },
      { index: 1, side: 'short', entryPrice: 105, isOpen: true, netProfit: -2 },
    ],
    ...extra,
  } as BacktestOutcome
}

beforeEach(() => localStorage.clear())

describe('BacktestResultTabs', () => {
  it('opens on the equity curve, with drawdown and trades one click away', async () => {
    render(<BacktestResultTabs outcome={outcome()} money={money} />)
    expect(screen.getByRole('tab', { name: 'Equity' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('curve')).toHaveTextContent('equity')

    await userEvent.click(screen.getByRole('tab', { name: 'Drawdown' }))
    expect(screen.getByTestId('curve')).toHaveTextContent('drawdown')

    await userEvent.click(screen.getByRole('tab', { name: 'Trades (2)' }))
    expect(screen.queryByTestId('curve')).toBeNull()
    expect(screen.getByText('open')).toBeInTheDocument()
    expect(screen.getByText('5.00')).toBeInTheDocument()
  })

  it('remembers the tab last chosen for the next run', async () => {
    const first = render(<BacktestResultTabs outcome={outcome()} money={money} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Drawdown' }))
    first.unmount()

    render(<BacktestResultTabs outcome={outcome()} money={money} />)
    expect(screen.getByRole('tab', { name: 'Drawdown' })).toHaveAttribute('aria-selected', 'true')
  })

  it('says so when there is nothing to draw or list', async () => {
    render(<BacktestResultTabs outcome={outcome({ equity: [], trades: [] })} money={money} />)
    expect(screen.getByText('This run has too few bars to draw an equity curve.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Trades' }))
    expect(screen.getByText('This run took no trades.')).toBeInTheDocument()
  })
})
