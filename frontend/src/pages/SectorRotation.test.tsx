/**
 * What this pins.
 *
 * The API module is stubbed, the store and the page are real. Three things a
 * trader relies on: the map asks for the list they built (or the default
 * sectors when they built none), a symbol picked from search joins that list
 * and survives a reload, and the ranking reads the numbers the server sent.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RotationRequest, RotationResult } from '@/api/sector-rotation'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useAuthStore } from '@/stores/authStore'
import { useSectorRotationStore } from '@/stores/sectorRotationStore'
import SectorRotation from './SectorRotation'

const harness = vi.hoisted(() => ({
  getSectorRotation: vi.fn(),
  getRotationOptions: vi.fn(),
}))

vi.mock('@/api/sector-rotation', () => ({
  getSectorRotation: harness.getSectorRotation,
  getRotationOptions: harness.getRotationOptions,
}))

const OPTIONS = {
  benchmarks: [
    { symbol: 'NIFTY', exchange: 'NSE_INDEX', label: 'Nifty 50' },
    { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', label: 'Bank Nifty' },
  ],
  timeframes: ['daily', 'weekly'],
  exchanges: ['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX'],
  max_instruments: 40,
  sectors: [
    { symbol: 'NIFTYIT', exchange: 'NSE_INDEX', label: 'IT' },
    { symbol: 'NIFTYAUTO', exchange: 'NSE_INDEX', label: 'Auto' },
  ],
  max_tail: 30,
}

function entry(symbol: string, exchange: string, label: string, rs: number, mom: number) {
  return {
    symbol,
    exchange,
    label,
    quadrant:
      rs >= 100 ? (mom >= 100 ? 'leading' : 'weakening') : mom >= 100 ? 'improving' : 'lagging',
    rs_ratio: rs,
    rs_momentum: mom,
    bars_in_quadrant: 4,
    tail: [
      { date: '2026-10-26', rs_ratio: rs - 0.2, rs_momentum: mom - 0.2 },
      { date: '2026-10-27', rs_ratio: rs, rs_momentum: mom },
    ],
  }
}

function resultFor(request: RotationRequest): RotationResult {
  const list = request.instruments.length > 0 ? request.instruments : OPTIONS.sectors
  return {
    benchmark: request.benchmark,
    benchmark_exchange: 'NSE_INDEX',
    benchmark_label: 'Nifty 50',
    timeframe: request.timeframe,
    source: request.source,
    as_of: '2026-10-27',
    max_tail: 30,
    instruments: list.map((i, n) =>
      entry(i.symbol, i.exchange, i.label ?? i.symbol, 105.41 - n * 7, 104.32 - n * 4)
    ),
    unavailable: [],
  } as RotationResult
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <SectorRotation />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  localStorage.clear()
  useSectorRotationStore.setState({
    benchmark: 'NIFTY',
    timeframe: 'daily',
    source: 'db',
    tailStep: 2,
    zoomStep: 0,
    instruments: null,
    hidden: [],
  })
  useAuthStore.setState({ apiKey: 'test-key' } as never)
  harness.getRotationOptions.mockResolvedValue(OPTIONS)
  harness.getSectorRotation.mockImplementation(async (r: RotationRequest) => resultFor(r))
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      json: async () => ({
        results: [{ symbol: 'RELIANCE', name: 'RELIANCE INDUSTRIES', exchange: 'NSE', token: '1' }],
      }),
    }))
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('SectorRotation', () => {
  it('asks for the default sector set and ranks what the server sent', async () => {
    renderPage()
    await waitFor(() => expect(harness.getSectorRotation).toHaveBeenCalled())
    const request = harness.getSectorRotation.mock.calls[0][0] as RotationRequest
    expect(request).toMatchObject({ benchmark: 'NIFTY', timeframe: 'daily', source: 'db' })
    expect(request.instruments).toEqual([])

    expect(await screen.findByText('105.4')).toBeInTheDocument()
    expect(screen.getByText('104.3')).toBeInTheDocument()
    expect(screen.getAllByText('Leading').length).toBeGreaterThan(0)
  })

  it('adds a searched stock, sends it, and keeps it for the next visit', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderPage()
    await screen.findByText('105.4')

    fireEvent.change(screen.getByLabelText('Search symbol'), { target: { value: 'RELI' } })
    await act(async () => {
      vi.advanceTimersByTime(350)
    })
    fireEvent.click(await screen.findByText('RELIANCE INDUSTRIES'))
    vi.useRealTimers()

    await waitFor(() => {
      const last = harness.getSectorRotation.mock.lastCall?.[0] as RotationRequest
      expect(last.instruments.map((i) => i.symbol)).toEqual(['NIFTYIT', 'NIFTYAUTO', 'RELIANCE'])
    })

    const saved = JSON.parse(localStorage.getItem('openalgo-sector-rotation') ?? '{}')
    expect(saved.state.instruments.map((i: { symbol: string }) => i.symbol)).toEqual([
      'NIFTYIT',
      'NIFTYAUTO',
      'RELIANCE',
    ])
  })

  it('removing a sector stops asking for it, and reset returns to the defaults', async () => {
    renderPage()
    await screen.findByText('105.4')

    fireEvent.click(screen.getByLabelText('Remove Auto'))
    await waitFor(() => {
      const last = harness.getSectorRotation.mock.lastCall?.[0] as RotationRequest
      expect(last.instruments.map((i) => i.symbol)).toEqual(['NIFTYIT'])
    })
    await waitFor(() => expect(screen.queryByLabelText('Remove Auto')).not.toBeInTheDocument())

    // The default map is still cached, so reset is served without a new request.
    fireEvent.click(screen.getByText('Reset to sectors'))
    expect(await screen.findByLabelText('Remove Auto')).toBeInTheDocument()
    expect(useSectorRotationStore.getState().instruments).toBeNull()
  })

  it('an emptied list is never sent, since empty means every default sector', async () => {
    useSectorRotationStore.setState({
      instruments: [{ symbol: 'NIFTYIT', exchange: 'NSE_INDEX', label: 'IT', color: '#6366f1' }],
    })
    renderPage()
    await screen.findByText('105.4')

    fireEvent.click(screen.getByLabelText('Remove IT'))

    expect(await screen.findByText(/No symbols on the map/)).toBeInTheDocument()
    for (const [request] of harness.getSectorRotation.mock.calls) {
      expect((request as RotationRequest).instruments).not.toEqual([])
    }
  })
})
