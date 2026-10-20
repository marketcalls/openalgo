import type { IndicatorState } from 'openalgo-charts'
import { describe, expect, it } from 'vitest'
import { planIndicatorTemplate, readStoredIndicators } from './indicatorTemplates'

const ema = (period = 9): IndicatorState => ({
  indicatorId: 'ema',
  settings: { period, 'plot.ema.color': '#fa0' },
  paneIndex: 0,
  visible: true,
})
const available = new Set(['ema', 'rsi', 'macd'])

describe('indicator template planning', () => {
  it('rejects appending into a pane occupied by an existing study', () => {
    const existing = [{ indicatorId: 'rsi', settings: {}, paneIndex: 3 }]
    expect(() =>
      planIndicatorTemplate(existing, [{ ...ema(), paneIndex: 1 }], 'append', available, 3)
    ).toThrow(/pane/i)
    expect(existing[0].paneIndex).toBe(3)
  })
  it('keeps existing study identities but gives imported template studies fresh identities', () => {
    const existing = { ...ema(), instanceId: 'anchored-study' }
    const incoming = { ...ema(21), instanceId: 'anchored-study' }
    const appended = planIndicatorTemplate([existing], [incoming], 'append', available, 1)
    expect(appended[0].instanceId).toBe('anchored-study')
    expect(appended[1]).not.toHaveProperty('instanceId')
    expect(
      planIndicatorTemplate([existing], [incoming], 'replace', available, 1)[0]
    ).not.toHaveProperty('instanceId')
    expect(incoming.instanceId).toBe('anchored-study')
  })

  it('retains identical instances, visibility and detached plot settings', () => {
    const input = [ema(), { ...ema(), visible: false }, ema(21)]
    const result = planIndicatorTemplate([], input, 'replace', available, 1)
    expect(result.map((item) => [item.settings.period, item.visible])).toEqual([
      [9, true],
      [9, false],
      [21, true],
    ])
    input[0].settings.period = 999
    expect(result[0].settings.period).toBe(9)
    expect(result[0].settings['plot.ema.color']).toBe('#fa0')
    expect(result[0]).not.toBe(result[1])
  })

  it('appends separate oscillator panes while retaining incoming pane groups', () => {
    const current = [ema(), { indicatorId: 'rsi', settings: {}, paneIndex: 1 }]
    const incoming = [
      ema(21),
      { indicatorId: 'rsi', settings: { period: 9 }, paneIndex: 2 },
      { indicatorId: 'rsi', settings: { period: 14 }, paneIndex: 2 },
      { indicatorId: 'macd', settings: {}, paneIndex: 5 },
    ]
    const result = planIndicatorTemplate(current, incoming, 'append', available, 3)
    expect(result.map((item) => item.paneIndex)).toEqual([0, 1, 0, 3, 3, 4])
    expect(current.map((item) => item.paneIndex)).toEqual([0, 1])
    expect(incoming.map((item) => item.paneIndex)).toEqual([0, 2, 2, 5])
  })

  it('an empty replace removes studies and an empty append preserves them', () => {
    expect(planIndicatorTemplate([ema()], [], 'replace', available, 1)).toEqual([])
    expect(planIndicatorTemplate([ema()], [], 'append', available, 1)).toEqual([ema()])
  })

  it('reports all missing descriptors before changing the current list', () => {
    const current = [ema()]
    const incoming = [
      { ...ema(), indicatorId: 'custom-one' },
      { ...ema(), indicatorId: 'custom-two' },
    ]
    expect(() => planIndicatorTemplate(current, incoming, 'replace', available, 1)).toThrow(
      /custom-one.*custom-two/
    )
    expect(current).toEqual([ema()])
    expect(() => planIndicatorTemplate(incoming, [ema()], 'append', available, 1)).toThrow(
      /custom-one/
    )
  })

  it('rejects an unknown action and overflowing study or pane lists', () => {
    expect(() => planIndicatorTemplate([], [], 'delete' as 'replace', available, 1)).toThrow(
      /mode/i
    )
    expect(() =>
      planIndicatorTemplate(
        Array.from({ length: 256 }, () => ema()),
        [ema()],
        'append',
        available,
        1
      )
    ).toThrow(/256/)
    expect(() =>
      planIndicatorTemplate([], [{ ...ema(), paneIndex: 1 }], 'append', available, 32)
    ).toThrow(/pane/i)
    expect(planIndicatorTemplate([], [ema()], 'append', available, 32)).toEqual([ema()])
  })
})

describe('saved indicator migration', () => {
  it('heals exact legacy duplicates without inventing an oscillator pane', () => {
    const legacy = { indicatorId: 'rsi', settings: { period: 14 }, visible: false }
    expect(readStoredIndicators([legacy, legacy])).toEqual([legacy])
  })

  it('retains every modern instance and its pane placement', () => {
    const repeated = { indicatorId: 'rsi', settings: { period: 14 }, paneIndex: 2, visible: false }
    expect(readStoredIndicators({ version: 2, indicators: [repeated, repeated] })).toEqual([
      repeated,
      repeated,
    ])
  })

  it('strips private fields and detaches saved settings', () => {
    const input = {
      version: 2,
      indicators: [{ ...ema(), settings: { period: 9, apiKey: 'private' } }],
    }
    const result = readStoredIndicators(input)
    input.indicators[0].settings.period = 100
    expect(result[0].settings).toEqual({ period: 9 })
  })

  it.each([
    null,
    {},
    { version: 99, indicators: [] },
    { version: 2, indicators: [{}] },
    [{ indicatorId: 'ema', settings: {}, paneIndex: null }],
  ])('rejects malformed or unsupported records: %j', (input) => {
    expect(() => readStoredIndicators(input)).toThrow()
  })
})
