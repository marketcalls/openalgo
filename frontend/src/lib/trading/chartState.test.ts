import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CHART_READY,
  type ChartStateView,
  chartLoadFailed,
  chartNoData,
  chartStateCopy,
  createChartStateGate,
  LOADING_DELAY_MS,
  traderReason,
} from './chartState'

const loading: ChartStateView = { kind: 'loading', symbol: 'NIFTY', interval: '5m' }

describe('chart state wording', () => {
  it('names the symbol and interval when there are no bars, and says what to do', () => {
    const copy = chartStateCopy(chartNoData('RELIANCE', '1m'))
    expect(copy.title).toBe('No data for RELIANCE on 1m')
    expect(copy.text).toMatch(/Try another interval, or check the symbol\.$/)
    expect(copy.role).toBe('status')
  })

  it('states a failed load as a cause and a next action, never a code', () => {
    const view = chartLoadFailed(
      'SBIN',
      '15m',
      'history error: /api/v1/history failed (500): Broker session expired'
    )
    const copy = chartStateCopy(view)
    expect(copy.title).toBe('Could not load SBIN on 15m')
    expect(copy.text).toBe('Broker session expired. Try again in a moment.')
    expect(copy.text).not.toMatch(/\d{3}|api|error:/i)
    expect(copy.role).toBe('alert')
  })

  it.each([
    ['TypeError: Failed to fetch', /OpenAlgo could not be reached/],
    ['HTTP 502 Bad gateway', /^Bad gateway$/],
    ['status code 429: Too many requests.', /^Too many requests$/],
    ['', /^The broker did not return bars$/],
    ['symbol not found', /^Symbol not found$/],
  ])('keeps %j trader-facing', (raw, expected) => {
    expect(traderReason(raw)).toMatch(expected)
  })

  it('says what is loading without a symbol before the first one is known', () => {
    expect(chartStateCopy({ kind: 'loading', symbol: '', interval: '' }).title).toBe(
      'Loading chart'
    )
    expect(chartStateCopy(loading).title).toBe('Loading NIFTY 5m')
  })
})

describe('chart state gate', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('shows the dots only for a load slower than the delay', () => {
    const show = vi.fn()
    const gate = createChartStateGate(show)
    gate.set(loading)
    vi.advanceTimersByTime(LOADING_DELAY_MS - 1)
    expect(show).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(show).toHaveBeenLastCalledWith(loading)
    gate.set(CHART_READY)
    expect(show).toHaveBeenLastCalledWith(null)
  })

  it('never flashes the dots for a fast load', () => {
    const show = vi.fn()
    const gate = createChartStateGate(show)
    gate.set(loading)
    vi.advanceTimersByTime(40)
    gate.set(CHART_READY)
    vi.advanceTimersByTime(LOADING_DELAY_MS * 4)
    expect(show).not.toHaveBeenCalled()
  })

  it('shows a failure at once, and a retry takes the card down before its dots', () => {
    const show = vi.fn()
    const gate = createChartStateGate(show)
    const failed = chartLoadFailed('NIFTY', '5m', 'Broker session expired')
    gate.set(failed)
    expect(show).toHaveBeenLastCalledWith(failed)
    gate.set(loading)
    expect(show).toHaveBeenLastCalledWith(null)
    vi.advanceTimersByTime(LOADING_DELAY_MS)
    expect(show).toHaveBeenLastCalledWith(loading)
  })

  it('dismisses a card and stops after destroy', () => {
    const show = vi.fn()
    const gate = createChartStateGate(show)
    gate.set(chartNoData('NIFTY', '5m'))
    gate.dismiss()
    expect(show).toHaveBeenLastCalledWith(null)
    gate.set(loading)
    gate.destroy()
    vi.advanceTimersByTime(LOADING_DELAY_MS * 2)
    expect(show).toHaveBeenCalledTimes(2)
  })
})
