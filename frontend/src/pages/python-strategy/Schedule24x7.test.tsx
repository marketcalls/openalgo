import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { pythonStrategyApi } from '@/api/python-strategy'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import type { PythonStrategy, StrategyExchangeList } from '@/types/python-strategy'
import NewPythonStrategy from './NewPythonStrategy'
import SchedulePythonStrategy from './SchedulePythonStrategy'

vi.mock('@/api/python-strategy', () => ({
  pythonStrategyApi: {
    getExchanges: vi.fn(),
    getStrategy: vi.fn(),
    scheduleStrategy: vi.fn(),
    uploadStrategy: vi.fn(),
  },
}))
vi.mock('@/utils/toast', () => ({ showToast: { success: vi.fn(), error: vi.fn() } }))

const api = vi.mocked(pythonStrategyApi)
const EVERY_DAY = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

const cryptoBroker: StrategyExchangeList = {
  exchanges: [
    {
      value: 'CRYPTO',
      label: 'CRYPTO 24/7',
      description: null,
      start_time: null,
      end_time: null,
      window: '24/7',
      is_24x7: true,
    },
  ],
  default: 'CRYPTO',
}

const strategy = (overrides: Partial<PythonStrategy>): PythonStrategy =>
  ({
    id: 'c1',
    name: 'Crypto bot',
    status: 'scheduled',
    exchange: 'CRYPTO',
    schedule_start_time: '00:00',
    schedule_stop_time: '23:59',
    schedule_days: EVERY_DAY,
    ...overrides,
  }) as PythonStrategy

function renderAt(path: string, routePath: string, page: ReactElement) {
  window.history.pushState(null, '', path)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Routes>
        <Route path={routePath} element={page} />
        <Route path="/python" element={<p>strategy list</p>} />
      </Routes>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getExchanges.mockResolvedValue(cryptoBroker)
  api.scheduleStrategy.mockResolvedValue({ status: 'success', message: 'ok' })
  api.uploadStrategy.mockResolvedValue({ status: 'success', message: 'ok' })
})
afterEach(() => window.history.pushState(null, '', '/'))

describe('a crypto strategy on /python can run 24/7', () => {
  it('never shows CRYPTO in the dropdown while the form is still on another exchange', async () => {
    // The race behind a CI failure: the broker list (CRYPTO only) arrived, the
    // dropdown fell back to its only option and read CRYPTO, while the form
    // was still on NSE for one commit and had no Run 24/7 switch. A test (or a
    // trader) looking at that moment saw a crypto dropdown with stock fields.
    const mismatches: string[] = []
    const view = renderAt('/python/new', '/python/new', <NewPythonStrategy />)
    const check = () => {
      const select = view.container.querySelector<HTMLSelectElement>('#exchange')
      if (select?.value === 'CRYPTO' && !view.container.querySelector('#run_24x7')) {
        mismatches.push('dropdown on CRYPTO without the 24/7 switch')
      }
    }
    const observer = new MutationObserver(check)
    observer.observe(view.container, { subtree: true, childList: true, attributes: true })
    try {
      await screen.findByRole('switch', { name: 'Run 24/7' })
    } finally {
      observer.disconnect()
    }
    expect(mismatches).toEqual([])
  })

  it('starts a new strategy on the broker exchange, running 24/7 with no stop time', async () => {
    const user = userEvent.setup()
    renderAt('/python/new', '/python/new', <NewPythonStrategy />)

    // A crypto broker offers CRYPTO alone, and the form moves onto it. Waited
    // on the switch, which only the form's own state renders, not on the
    // dropdown's value.
    expect(await screen.findByRole('switch', { name: 'Run 24/7' })).toBeChecked()
    expect(screen.getByLabelText('Exchange')).toHaveValue('CRYPTO')
    expect(screen.queryByLabelText('Stop Time (IST)')).toBeNull()

    await user.type(screen.getByLabelText('Strategy Name'), 'Crypto bot')
    const file = new File(['print(1)'], 'bot.py', { type: 'text/x-python' })
    await user.upload(screen.getByLabelText('Python Script'), file)
    await user.click(screen.getByRole('button', { name: 'Upload Strategy' }))

    await waitFor(() => expect(api.uploadStrategy).toHaveBeenCalledOnce())
    expect(api.uploadStrategy.mock.calls[0][2]).toEqual({
      start_time: '00:00',
      stop_time: null,
      days: EVERY_DAY,
      exchange: 'CRYPTO',
    })
  })

  it('reads a crypto strategy with no stop time as 24/7 and saves it the same way', async () => {
    const user = userEvent.setup()
    api.getStrategy.mockResolvedValue(strategy({ schedule_stop_time: null }))
    renderAt('/python/c1/schedule', '/python/:strategyId/schedule', <SchedulePythonStrategy />)

    const toggle = await screen.findByRole('switch', { name: 'Run 24/7' })
    expect(toggle).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Save Schedule' }))

    await waitFor(() => expect(api.scheduleStrategy).toHaveBeenCalledOnce())
    expect(api.scheduleStrategy).toHaveBeenCalledWith('c1', {
      start_time: '00:00',
      stop_time: null,
      days: EVERY_DAY,
      exchange: 'CRYPTO',
    })
  })

  it('keeps an existing 00:00 - 23:59 schedule until the trader turns 24/7 on', async () => {
    const user = userEvent.setup()
    api.getStrategy.mockResolvedValue(strategy({}))
    renderAt('/python/c1/schedule', '/python/:strategyId/schedule', <SchedulePythonStrategy />)

    const toggle = await screen.findByRole('switch', { name: 'Run 24/7' })
    expect(toggle).not.toBeChecked()
    expect(screen.getByLabelText(/Stop Time/)).toHaveValue('23:59')

    await user.click(toggle)
    await user.click(screen.getByRole('button', { name: 'Save Schedule' }))
    await waitFor(() =>
      expect(api.scheduleStrategy).toHaveBeenCalledWith(
        'c1',
        expect.objectContaining({ stop_time: null })
      )
    )
  })

  it('refuses a start time equal to the stop time instead of saving an empty window', async () => {
    const user = userEvent.setup()
    api.getStrategy.mockResolvedValue(strategy({ schedule_stop_time: '00:00' }))
    renderAt('/python/c1/schedule', '/python/:strategyId/schedule', <SchedulePythonStrategy />)

    await screen.findByRole('switch', { name: 'Run 24/7' })
    await user.click(screen.getByRole('button', { name: 'Save Schedule' }))

    const { showToast } = await import('@/utils/toast')
    expect(showToast.error).toHaveBeenCalledWith(
      'Stop time cannot be the same as the start time. To never stop, turn on Run 24/7.',
      'pythonStrategy'
    )
    expect(api.scheduleStrategy).not.toHaveBeenCalled()
  })

  it('keeps the exchange a strategy was saved with even when the broker list lacks it', async () => {
    api.getStrategy.mockResolvedValue(
      strategy({ exchange: 'NSE', schedule_start_time: '09:15', schedule_stop_time: '15:30' })
    )
    renderAt('/python/c1/schedule', '/python/:strategyId/schedule', <SchedulePythonStrategy />)

    await waitFor(() => expect(screen.getByLabelText('Exchange')).toHaveValue('NSE'))
    expect(screen.queryByRole('switch', { name: 'Run 24/7' })).toBeNull()
  })
})

const stockBroker: StrategyExchangeList = {
  exchanges: [
    {
      value: 'NSE',
      label: 'NSE Equity',
      description: 'Equity',
      start_time: '09:15',
      end_time: '15:30',
      window: '09:15-15:30',
      is_24x7: false,
    },
    {
      value: 'NFO',
      label: 'NFO F&O',
      description: 'NSE F&O',
      start_time: '09:15',
      end_time: '15:40',
      window: '09:15-15:40',
      is_24x7: false,
    },
  ],
  default: 'NSE',
}

describe('Indian exchanges keep their schedule as before', () => {
  it('starts a new strategy on NSE with a start and stop time and no 24/7 switch', async () => {
    const user = userEvent.setup()
    api.getExchanges.mockResolvedValue(stockBroker)
    renderAt('/python/new', '/python/new', <NewPythonStrategy />)

    await waitFor(() => expect(screen.getByRole('option', { name: 'NFO F&O' })).toBeInTheDocument())
    expect(screen.getByLabelText('Exchange')).toHaveValue('NSE')
    expect(screen.queryByRole('switch', { name: 'Run 24/7' })).toBeNull()

    await user.type(screen.getByLabelText('Strategy Name'), 'Nifty bot')
    await user.upload(
      screen.getByLabelText('Python Script'),
      new File(['print(1)'], 'bot.py', { type: 'text/x-python' })
    )
    await user.click(screen.getByRole('button', { name: 'Upload Strategy' }))

    await waitFor(() => expect(api.uploadStrategy).toHaveBeenCalledOnce())
    expect(api.uploadStrategy.mock.calls[0][2]).toEqual({
      start_time: '09:00',
      stop_time: '16:00',
      days: ['mon', 'tue', 'wed', 'thu', 'fri'],
      exchange: 'NSE',
    })
  })

  it('saves an NSE schedule unchanged, with no crypto-only refusal', async () => {
    const user = userEvent.setup()
    api.getExchanges.mockResolvedValue(stockBroker)
    api.getStrategy.mockResolvedValue(
      strategy({
        exchange: 'NSE',
        schedule_start_time: '09:15',
        schedule_stop_time: '09:15',
        schedule_days: ['mon', 'tue', 'wed', 'thu', 'fri'],
      })
    )
    renderAt('/python/c1/schedule', '/python/:strategyId/schedule', <SchedulePythonStrategy />)

    await waitFor(() => expect(screen.getByLabelText(/Stop Time/)).toHaveValue('09:15'))
    expect(screen.queryByRole('switch', { name: 'Run 24/7' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save Schedule' }))

    await waitFor(() =>
      expect(api.scheduleStrategy).toHaveBeenCalledWith('c1', {
        start_time: '09:15',
        stop_time: '09:15',
        days: ['mon', 'tue', 'wed', 'thu', 'fri'],
        exchange: 'NSE',
      })
    )
  })
})
