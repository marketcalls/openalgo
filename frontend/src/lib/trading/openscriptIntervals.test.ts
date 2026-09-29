/**
 * What an OpenScript interval input may be set to.
 *
 * The first group is the defect: the terminal offers `D` and an empty "Chart
 * interval", and the language refuses both at load with OS6001. The group after
 * it is the one that keeps this file honest. `openscriptIntervals.ts` restates
 * two of the engine's rules in the host, the spelling and the fold, and a
 * second copy of a rule is a second answer; so every choice it offers is run
 * through the installed engine and must draw, and every broker code it leaves
 * out must be one the engine refuses.
 */

import { createChart, registerIndicator } from 'openalgo-charts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { idForScript, isScriptInstance } from './openscriptFiles'
import { foldsOnto, languageInterval, scriptIntervalChoices } from './openscriptIntervals'

/** What the terminal fills an interval input with: its empty entry, then the broker's codes. */
const BROKER = ['1m', '3m', '5m', '10m', '15m', '30m', '1h', '2h', 'D', 'W', 'M']
const OFFERED = [
  { label: 'Chart interval', value: '' },
  ...BROKER.map((code) => ({ label: code, value: code })),
]

const SCRIPT = [
  'version 1',
  'study("Higher", overlay = true)',
  'tf = input("60", "Higher timeframe", kind = "interval")',
  'plot(req.timeframe(tf, close), "Higher close", aqua)',
  '',
].join('\n')

/**
 * Runs the study through the language's own chart adapter with the interval
 * set as given, on a chart of the given interval, and answers with the code it
 * was refused with, or null when it drew.
 */
async function refusal(setting: string, chartInterval: string): Promise<string | null> {
  const { sourceFile, lex, parseTokens, check, emit, DiagnosticBag } = await import(
    'openalgo-script'
  )
  const { descriptorFor } = await import('openalgo-script/adapters/charts')
  const file = sourceFile('higher.oscript', SCRIPT)
  const bag = new DiagnosticBag()
  const program = emit(
    file,
    check(file, parseTokens(file, lex(file, bag), bag), bag),
    bag,
    {}
  ).program
  const descriptor = descriptorFor(program as never, { id: 'openscript:higher' })
  const bars = Array.from({ length: 40 }, (_, i) => ({
    time: 1_760_000_000 + i * 300,
    open: 100,
    high: 101,
    low: 99,
    close: 100.5,
    volume: 10,
  }))
  try {
    descriptor.calc(bars, { tf: setting }, {} as never, {
      barState: { isNew: true, isConfirmed: true, isRealtime: false, lastIndex: bars.length - 1 },
      interval: chartInterval,
      timezone: 'Asia/Kolkata',
      now: () => 1_760_000_000_000,
    })
    return null
  } catch (error) {
    return /OS\d{4}/.exec(String((error as Error).message))?.[0] ?? 'refused'
  }
}

describe('what the terminal offers, and why it was wrong for a script', () => {
  it('the language refuses the broker day code and the empty chart entry', async () => {
    expect(await refusal('D', '5m')).toBe('OS6001')
    expect(await refusal('', '5m')).toBe('OS6001')
  })

  it('offers neither of them to an OpenScript study', () => {
    const { choices } = scriptIntervalChoices(OFFERED, '5m', '')
    const values = choices.map((one) => one.value)
    expect(values).not.toContain('')
    expect(values).not.toContain('D')
    expect(values).toContain('1D')
  })

  it('makes "Chart interval" the chart own interval, and says which', () => {
    const { choices, value } = scriptIntervalChoices(OFFERED, '5m', '')
    expect(choices[0]).toEqual({ label: 'Chart interval (5m)', value: '5m' })
    // An empty stored value is what "Chart interval" wrote before, so it reads
    // as that choice and Ok stores something the engine takes.
    expect(value).toBe('5m')
    // And the chart's own code is not offered a second time under its own name.
    expect(choices.filter((one) => one.value === '5m')).toHaveLength(1)
  })

  it('spells a stored broker code the language way', () => {
    expect(scriptIntervalChoices(OFFERED, '5m', 'D').value).toBe('1D')
    expect(scriptIntervalChoices(OFFERED, '5m', '1h').value).toBe('1h')
  })

  it('keeps a stored value it cannot offer, so the control does not lie about it', () => {
    const { choices, value } = scriptIntervalChoices(OFFERED, '15m', '5m')
    expect(value).toBe('5m')
    expect(choices.some((one) => one.value === '5m')).toBe(true)
  })

  it('leaves the chart entry out when it does not know the chart interval', () => {
    const { choices, value } = scriptIntervalChoices(OFFERED, undefined, '')
    expect(choices.some((one) => one.label.startsWith('Chart interval'))).toBe(false)
    expect(choices.some((one) => one.value === '')).toBe(false)
    expect(value).toBe(choices[0]?.value)
  })
})

describe('the language spelling', () => {
  it('turns broker codes into timeframes the language reads', () => {
    expect(languageInterval('D')).toBe('1D')
    expect(languageInterval('1d')).toBe('1D')
    expect(languageInterval('W')).toBe('1W')
    expect(languageInterval('M')).toBe('1M')
    expect(languageInterval('5m')).toBe('5m')
    expect(languageInterval('1H')).toBe('1h')
    expect(languageInterval('60')).toBe('60')
  })

  it('has no spelling for seconds or for nonsense', () => {
    expect(languageInterval('30s')).toBeNull()
    expect(languageInterval('')).toBeNull()
    expect(languageInterval('0m')).toBeNull()
    expect(languageInterval('m')).toBeNull()
    expect(languageInterval('5min')).toBeNull()
  })
})

describe('held to the installed engine', () => {
  // Chart intervals a trader can be on, `D` being the terminal's spelling of a
  // daily chart. The engine is given each in the language's spelling, because
  // the fold rule is about a chart timeframe it can read: handed `D` it has
  // nothing to compare against and skips the rule, which would make every
  // refusal below pass for the wrong reason.
  const CHARTS = ['1m', '5m', '15m', '1h', 'D']

  it('every choice offered draws on that chart', async () => {
    for (const chart of CHARTS) {
      const engineChart = languageInterval(chart) ?? chart
      const { choices } = scriptIntervalChoices(OFFERED, chart, '')
      expect(choices.length).toBeGreaterThan(0)
      for (const one of choices) {
        expect([chart, one.value, await refusal(one.value, engineChart)]).toEqual([
          chart,
          one.value,
          null,
        ])
      }
    }
  })

  it('every broker code left out is one the engine refuses', async () => {
    for (const chart of CHARTS) {
      const engineChart = languageInterval(chart) ?? chart
      const offered = new Set(scriptIntervalChoices(OFFERED, chart, '').choices.map((c) => c.value))
      for (const code of BROKER) {
        const spelled = languageInterval(code)
        if (spelled !== null && offered.has(spelled)) continue
        // Refused as the broker writes it, and refused as the language would,
        // so the choice was not merely respelled out of the list.
        expect([chart, code, await refusal(code, engineChart)]).not.toEqual([chart, code, null])
        if (spelled !== null) {
          expect([chart, spelled, await refusal(spelled, engineChart)]).not.toEqual([
            chart,
            spelled,
            null,
          ])
        }
      }
    }
  })

  it('agrees with the engine on the fold rule', async () => {
    const pairs: [string, string][] = [
      ['1m', '5m'],
      ['10m', '15m'],
      ['45m', '15m'],
      ['1D', '1h'],
      ['1h', '1D'],
      ['7m', '5m'],
    ]
    for (const [requested, chart] of pairs) {
      expect([requested, chart, foldsOnto(requested, chart)]).toEqual([
        requested,
        chart,
        (await refusal(requested, chart)) === null,
      ])
    }
  })
})

describe('telling a script instance from any other', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reads the chart own name for an instance of a script', () => {
    // The dialog is handed an instance id, not a study id, so this rests on
    // how the installed chart names instances. Built on a real chart so a
    // chart release that names them differently fails here, not in a dialog.
    // The canvas is the only part stubbed, since this page has none to draw on.
    const context = new Proxy(
      { measureText: (text: string) => ({ width: text.length * 7 }) },
      { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
    )
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
      context as unknown as CanvasRenderingContext2D
    )
    registerIndicator({
      id: idForScript('probe.oscript'),
      name: 'Probe',
      placement: 'onchart',
      inputs: [],
      plots: [],
      calc: () => ({}),
    } as never)
    registerIndicator({
      id: 'probe-js',
      name: 'Probe JS',
      placement: 'onchart',
      inputs: [],
      plots: [],
      calc: () => ({}),
    } as never)
    const container = document.createElement('div')
    const chart = createChart(container, {
      shortcuts: false,
      timeNavigator: false,
      raf: {
        schedule: (callback) => {
          callback()
          return 1
        },
        cancel() {},
      },
    })
    try {
      chart.applySize(400, 300)
      const script = chart.addIndicator(idForScript('probe.oscript'))
      const other = chart.addIndicator('probe-js')
      expect(isScriptInstance(script.id)).toBe(true)
      expect(isScriptInstance(other.id)).toBe(false)
    } finally {
      chart.destroy()
    }
  })
})
