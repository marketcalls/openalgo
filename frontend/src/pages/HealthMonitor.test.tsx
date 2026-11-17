/**
 * What this pins about the health monitor's two history charts.
 *
 * The engine is stubbed, not the wiring around it: the real theme bridge runs,
 * and only `createChart` and the health API are stubs, because the assertions
 * are about what the page asks the engine to do.
 *
 * The time base matters most. The history arrives with a +05:30 offset in each
 * timestamp, so parsing it already gives real UTC, and the engine labels UTC
 * in IST by itself. A page that shifted the times again, or passed a formatter
 * that added the offset, would label every point 5h30m late without failing.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useThemeStore } from '@/stores/themeStore'

interface SeriesStub {
  type: string
  options: {
    style?: Record<string, unknown>
    priceFormat?: { type: string; precision?: number; formatter?: (v: number) => string }
  }
  setData: ReturnType<typeof vi.fn>
}

interface ChartStub {
  host: HTMLElement
  options: Record<string, unknown>
  series: SeriesStub[]
  setTheme: ReturnType<typeof vi.fn>
  destroyed: number
}

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((host: HTMLElement, options: Record<string, unknown>) => {
    // The engine draws into its host; a canvas stands in so the cleanup has
    // something to clear.
    host.appendChild(document.createElement('canvas'))
    const chart: ChartStub & Record<string, unknown> = {
      host,
      options,
      series: [],
      setTheme: vi.fn(),
      destroyed: 0,
      addSeries: (type: string, opts?: SeriesStub['options']) => {
        const series: SeriesStub = { type, options: opts ?? {}, setData: vi.fn() }
        chart.series.push(series)
        return series
      },
      destroy: () => {
        chart.destroyed += 1
      },
    }
    charts.push(chart)
    return chart
  })
  const api = {
    getCurrentMetrics: vi.fn(),
    getMetricsHistory: vi.fn(),
    getHealthStats: vi.fn(),
    getActiveAlerts: vi.fn(),
  }
  return { charts, createChart, api }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  lightTheme: {},
  darkTheme: {},
}))

vi.mock('@/api/health', () => ({
  getCurrentMetrics: harness.api.getCurrentMetrics,
  getMetricsHistory: harness.api.getMetricsHistory,
  getHealthStats: harness.api.getHealthStats,
  getActiveAlerts: harness.api.getActiveAlerts,
  acknowledgeAlert: vi.fn(),
  exportMetricsCSV: vi.fn(() => '/health/export?hours=24'),
}))

vi.mock('@/utils/toast', () => ({ showToast: { success: vi.fn(), error: vi.fn() } }))

import HealthMonitor from './HealthMonitor'

// 09:15:00 and 09:15:10 IST, as the backend sends them.
const HISTORY = [
  {
    timestamp: '2026-10-27T09:15:00+05:30',
    fd_count: 120,
    memory_rss_mb: 245.5,
    db_connections: 4,
    ws_connections: 1,
    threads: 20,
    overall_status: 'pass',
  },
  {
    timestamp: '2026-10-27T09:15:10+05:30',
    fd_count: 124,
    memory_rss_mb: 247.25,
    db_connections: 4,
    ws_connections: 1,
    threads: 21,
    overall_status: 'pass',
  },
]
// The same two instants in real UTC seconds: 03:45:00 and 03:45:10 UTC.
const UTC_0 = Date.UTC(2026, 9, 27, 3, 45, 0) / 1000
const UTC_1 = UTC_0 + 10

const CURRENT = {
  timestamp: '2026-10-27T09:15:10+05:30',
  fd: { count: 124, limit: 1024, usage_percent: 12.1, status: 'pass' },
  memory: {
    rss_mb: 247.25,
    vms_mb: 900,
    percent: 3.1,
    available_mb: 8000,
    swap_mb: 0,
    status: 'pass',
  },
  database: { total: 4, connections: {}, status: 'pass' },
  websocket: { total: 1, connections: {}, total_symbols: 5, status: 'pass' },
  threads: { count: 21, stuck: 0, status: 'pass' },
  processes: [],
  overall_status: 'pass',
}

const fdChart = () => harness.charts[0]
const memoryChart = () => harness.charts[1]

async function renderWithCharts() {
  const page = render(<HealthMonitor />)
  await waitFor(() => expect(harness.charts).toHaveLength(2))
  return page
}

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
  harness.api.getCurrentMetrics.mockResolvedValue(CURRENT)
  harness.api.getMetricsHistory.mockResolvedValue(HISTORY)
  harness.api.getHealthStats.mockResolvedValue(null)
  harness.api.getActiveAlerts.mockResolvedValue([])
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
  document.documentElement.classList.remove('dark', 'analyzer')
})

describe('HealthMonitor charts', () => {
  it('hands the engine real UTC seconds and leaves the IST labels to it', async () => {
    await renderWithCharts()

    expect(fdChart().series[0].setData).toHaveBeenLastCalledWith([
      { time: UTC_0, value: 120 },
      { time: UTC_1, value: 124 },
    ])
    expect(memoryChart().series[0].setData).toHaveBeenLastCalledWith([
      { time: UTC_0, value: 245.5 },
      { time: UTC_1, value: 247.25 },
    ])
    // No formatter of its own and no zone override: the engine's default zone
    // is IST, and a formatter here is how an offset gets added twice.
    for (const chart of harness.charts) {
      expect(chart.options.timeFormatter).toBeUndefined()
      expect(chart.options.timezone).toBeUndefined()
    }
  })

  it('draws one line per chart in its own colour, with the page keyboard left alone', async () => {
    await renderWithCharts()

    for (const chart of harness.charts) {
      expect(chart.options.shortcuts).toBe(false)
      // The corner mark would sit on the line in a chart this small.
      expect(chart.options.branding).toBe(false)
      expect(chart.options.grid).toEqual({ vertLines: false, horzLines: false })
      expect(chart.series).toHaveLength(1)
      expect(chart.series[0].type).toBe('line')
    }

    const fd = fdChart().series[0].options
    expect(fd.style).toMatchObject({ color: '#3b82f6', lineWidth: 2, priceLineVisible: false })
    // A file descriptor count reads as a whole number on the axis.
    expect(fd.priceFormat?.type).toBe('custom')
    expect(fd.priceFormat?.formatter?.(122.6)).toBe('123')

    const memory = memoryChart().series[0].options
    expect(memory.style).toMatchObject({ color: '#10b981', lineWidth: 2, priceLineVisible: false })
    expect(memory.priceFormat).toEqual({ type: 'price', precision: 2, minMove: 0.01 })

    // The current-value tag wears the line's colour, not the up and down pair.
    const theme = fdChart().options.theme as Record<string, string>
    expect(theme.lastPriceUp).toBe('#3b82f6')
    expect(theme.lastPriceDown).toBe('#3b82f6')
    // The chart sits in a card, so it takes the card's ground, not the page's.
    // jsdom has no canvas to resolve the token with, so it comes back as named.
    expect(theme.background).toContain('--card')
  })

  it('redraws the same charts on a refresh instead of building new ones', async () => {
    await renderWithCharts()
    const later = [
      ...HISTORY,
      { ...HISTORY[1], timestamp: '2026-10-27T09:15:20+05:30', fd_count: 130 },
    ]
    harness.api.getMetricsHistory.mockResolvedValue(later)

    fireEvent.click(screen.getByRole('button', { name: /Refresh/ }))

    await waitFor(() => expect(fdChart().series[0].setData.mock.lastCall?.[0]).toHaveLength(3))
    expect(fdChart().series[0].setData.mock.lastCall?.[0][2]).toEqual({
      time: UTC_1 + 10,
      value: 130,
    })
    expect(harness.createChart).toHaveBeenCalledTimes(2)
  })

  it('re-themes both charts in place for dark and for the analyzer', async () => {
    await renderWithCharts()

    act(() => useThemeStore.getState().setMode('dark'))
    expect(fdChart().setTheme).toHaveBeenCalledTimes(1)
    expect(memoryChart().setTheme).toHaveBeenCalledTimes(1)

    act(() => useThemeStore.getState().setAppMode('analyzer'))
    expect(fdChart().setTheme).toHaveBeenCalledTimes(2)
    expect(memoryChart().setTheme).toHaveBeenCalledTimes(2)
    // Each keeps its own line colour on the tag through the switch.
    expect(fdChart().setTheme.mock.lastCall?.[0]).toMatchObject({ lastPriceUp: '#3b82f6' })
    expect(memoryChart().setTheme.mock.lastCall?.[0]).toMatchObject({ lastPriceUp: '#10b981' })

    expect(harness.createChart).toHaveBeenCalledTimes(2)
  })

  it('destroys both charts and empties their hosts when the page unmounts', async () => {
    const { unmount } = await renderWithCharts()
    const [fd, memory] = harness.charts
    expect(fd.host.childElementCount).toBe(1)

    unmount()

    expect(fd.destroyed).toBe(1)
    expect(memory.destroyed).toBe(1)
    expect(fd.host.innerHTML).toBe('')
    expect(memory.host.innerHTML).toBe('')
  })
})
