import type { WorkspacePane } from 'openalgo-charts/workspace'
import { describe, expect, it } from 'vitest'
import {
  createWorkspacePanePreferences,
  parseTerminalWorkspacePane,
  validateWorkspacePaneSupport,
} from './workspaceState'

function pane(): WorkspacePane {
  return {
    id: 'p0',
    symbol: 'BHEL',
    exchange: 'NSE',
    interval: '15m',
    chartType: 'candlestick',
    chart: {
      version: 1,
      grid: { vertLines: false, horzLines: true },
      indicators: [
        { indicatorId: 'ema', settings: { period: 9 }, paneIndex: 0 },
        { indicatorId: 'ema', settings: { period: 9 }, paneIndex: 0 },
      ],
      drawings: { version: 2, drawings: [] },
    },
    settings: { 'volume.maPeriod': 20 },
    volume: false,
    magnet: 'weak',
    stay: true,
    comparisons: [],
    comparisonMode: 'price',
  }
}
const support = () => ({
  chartTypes: new Set(['candlestick', 'line']),
  intervals: new Set(['5m', '15m']),
  indicators: new Set(['ema', 'rsi']),
})

describe('prepared workspace configuration', () => {
  it('validates and detaches a complete pane before chart construction', () => {
    const input = pane()
    const result = parseTerminalWorkspacePane(input)
    expect(result).toEqual(input)
    input.chart.indicators![0].settings.period = 100
    expect(result.chart.indicators![0].settings.period).toBe(9)
    expect(() => parseTerminalWorkspacePane({ ...input, chart: { version: 99 } })).toThrow()
  })

  it('detaches valid comparison definitions and seeds their mode without execution data', () => {
    const input = {
      ...pane(),
      comparisons: [{ id: 'c1', symbol: 'OTHER', exchange: 'NSE', visible: true }],
      comparisonMode: 'percent' as const,
    }
    const parsed = parseTerminalWorkspacePane(input)
    const storage = createWorkspacePanePreferences(input, 'staged-p0')
    input.comparisons[0].symbol = 'CHANGED'
    expect(parsed.comparisons[0].symbol).toBe('OTHER')
    expect(JSON.parse(storage.getItem('staged-p0-comparisons')!)).toEqual({
      mode: 'percent',
      items: [{ id: 'c1', symbol: 'OTHER', exchange: 'NSE', visible: true }],
    })
    expect(() =>
      parseTerminalWorkspacePane({ ...input, comparisons: [{ id: 'c1', visible: true }] })
    ).toThrow()
  })

  it('seeds isolated preferences without execution data or shared browser writes', () => {
    const input = pane()
    Object.assign(input.settings, { apiKey: 'private', orders: 'private' })
    const storage = createWorkspacePanePreferences(input, 'staged-p0')
    expect(storage.getItem('staged-p0-symbol')).toBe(
      JSON.stringify({ symbol: 'BHEL', exchange: 'NSE' })
    )
    expect(storage.getItem('staged-p0-interval')).toBe('15m')
    expect(storage.getItem('staged-p0-ctype')).toBe('candlestick')
    expect(storage.getItem('staged-p0-grid')).toBe('01')
    expect(storage.getItem('staged-p0-vol')).toBe('0')
    expect(storage.getItem('staged-p0-magnet-mode')).toBe('weak')
    expect(storage.getItem('staged-p0-stay')).toBe('1')
    expect(JSON.parse(storage.getItem('staged-p0-indicators')!)).toEqual({
      version: 2,
      indicators: input.chart.indicators,
    })
    expect(JSON.parse(storage.getItem('staged-p0-alerts')!)).toEqual({ version: 1, alerts: [] })
    expect(JSON.parse(storage.getItem('staged-p0-chartsettings')!)).toEqual({
      'volume.maPeriod': 20,
    })
    for (const key of ['armed', 'product', 'qty', 'apikey', 'orders'])
      expect(storage.getItem(`staged-p0-${key}`)).toBeNull()
    storage.setItem('staged-p0-grid', '11')
    expect(input.chart.grid).toEqual({ vertLines: false, horzLines: true })
    expect(createWorkspacePanePreferences(pane(), 'staged-p0').getItem('staged-p0-grid')).toBe('01')
  })

  it('accepts repeated available studies and fails on unsupported type or interval', () => {
    expect(() => validateWorkspacePaneSupport(pane(), support())).not.toThrow()
    expect(() =>
      validateWorkspacePaneSupport({ ...pane(), chartType: 'missing' }, support())
    ).toThrow(/chart type/i)
    expect(() => validateWorkspacePaneSupport({ ...pane(), interval: '3m' }, support())).toThrow(
      /interval/i
    )
  })

  it('reports every unavailable study before a replacement pane can be published', () => {
    const input = pane()
    input.chart.indicators = [
      { indicatorId: 'custom-one', settings: {}, paneIndex: 1 },
      { indicatorId: 'custom-two', settings: {}, paneIndex: 2 },
    ]
    expect(() => validateWorkspacePaneSupport(input, support())).toThrow(/custom-one.*custom-two/)
  })
})
