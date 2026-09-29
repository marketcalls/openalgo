/**
 * What the strategies panel lists, now that a row is a deployment.
 *
 * The defect this replaced: the panel listed one row per file, so a strategy
 * deployed on a second instrument silently replaced the first and the two
 * shared a book. A trader watching a run on a commodity future was shown the
 * stock orders the same file had placed that morning.
 *
 * Each test names the wrong implementation it catches.
 */

import { describe, expect, it } from 'vitest'
import type { RunningStrategy, RunSettings } from '@/api/openscriptRunner'
import { deploymentsOf, matches } from './deployments'

function saved(over: Partial<RunSettings> & { deployment?: string }): RunSettings {
  return {
    deployment: 'openscript_turn_SYM1_EXCH1_1m',
    file: 'turn.oscript',
    symbol: 'SYM1',
    exchange: 'EXCH1',
    interval: '1m',
    product: 'MIS',
    ...over,
  }
}

function up(over: Partial<RunningStrategy> & { deployment?: string }): RunningStrategy {
  const id = over.deployment ?? 'openscript_turn_SYM1_EXCH1_1m'
  return {
    id,
    deployment: id,
    file: 'turn.oscript',
    state: 'running',
    symbol: 'SYM1',
    exchange: 'EXCH1',
    interval: '1m',
    product: 'MIS',
    pid: 42,
    started_at: null,
    log: null,
    ...over,
  }
}

describe('what the panel lists', () => {
  it('shows one strategy on two instruments as two rows', () => {
    // THE ONE THIS FILE EXISTS FOR. Keyed by the file, these collapse into one
    // row and a trader who deployed two strategies is shown one.
    const rows = deploymentsOf(
      [saved({}), saved({ deployment: 'openscript_turn_SYM2_EXCH1_1m', symbol: 'SYM2' })],
      []
    )

    expect(rows).toHaveLength(2)
    expect(rows.map((one) => one.settings?.symbol)).toEqual(['SYM1', 'SYM2'])
  })

  it('shows one strategy on one instrument at two intervals as two rows', () => {
    const rows = deploymentsOf(
      [
        saved({ deployment: 'openscript_turn_SYM1_EXCH1_5m', interval: '5m' }),
        saved({ deployment: 'openscript_turn_SYM1_EXCH1_1h', interval: '1h' }),
      ],
      []
    )

    expect(rows).toHaveLength(2)
  })

  it('puts the run on the deployment it belongs to and not on its sibling', () => {
    // Catches a run matched by file. The wrong row would show running, with a
    // Stop button that stopped a position on another instrument.
    const rows = deploymentsOf(
      [saved({}), saved({ deployment: 'openscript_turn_SYM2_EXCH1_1m', symbol: 'SYM2' })],
      [up({ deployment: 'openscript_turn_SYM2_EXCH1_1m', symbol: 'SYM2' })]
    )

    const [first, second] = rows
    expect(first.settings?.symbol).toBe('SYM2')
    expect(first.run).not.toBeNull()
    expect(second.run).toBeNull()
  })

  it('keeps a row for a run whose settings have been removed', () => {
    // THE ONE THAT MATTERS MOST AFTER THE FIRST. A deployment removed while it
    // was still running would otherwise vanish from the panel: a process
    // holding a position, with nothing on the screen that could stop it.
    const rows = deploymentsOf([], [up({})])

    expect(rows).toHaveLength(1)
    expect(rows[0].run).not.toBeNull()
    expect(rows[0].settings).toBeNull()
    expect(rows[0].file).toBe('turn.oscript')
  })

  it('lists what is running before what is not', () => {
    const rows = deploymentsOf(
      [
        saved({ deployment: 'openscript_a_SYM1_EXCH1_1m', file: 'a.oscript' }),
        saved({ deployment: 'openscript_z_SYM1_EXCH1_1m', file: 'z.oscript' }),
      ],
      [up({ deployment: 'openscript_z_SYM1_EXCH1_1m', file: 'z.oscript' })]
    )

    expect(rows.map((one) => one.file)).toEqual(['z.oscript', 'a.oscript'])
  })

  it('keeps two deployments of one strategy together', () => {
    const rows = deploymentsOf(
      [
        saved({ deployment: 'openscript_b_SYM2_EXCH1_1m', file: 'b.oscript', symbol: 'SYM2' }),
        saved({ deployment: 'openscript_a_SYM1_EXCH1_1m', file: 'a.oscript' }),
        saved({ deployment: 'openscript_b_SYM1_EXCH1_1m', file: 'b.oscript' }),
      ],
      []
    )

    expect(rows.map((one) => `${one.file}/${one.settings?.symbol}`)).toEqual([
      'a.oscript/SYM1',
      'b.oscript/SYM1',
      'b.oscript/SYM2',
    ])
  })

  it('falls back to the file when a server answers no deployment id', () => {
    // Catches a row keyed on undefined. Every such row would collapse onto one
    // key, so a server one version behind would show a single strategy.
    const rows = deploymentsOf(
      [
        { file: 'a.oscript', symbol: 'SYM1', exchange: 'E', interval: '1m', product: 'MIS' },
        { file: 'b.oscript', symbol: 'SYM1', exchange: 'E', interval: '1m', product: 'MIS' },
      ],
      []
    )

    expect(rows.map((one) => one.id)).toEqual(['a.oscript', 'b.oscript'])
  })
})

describe('searching', () => {
  it('finds a row by the strategy and by the instrument', () => {
    const row = deploymentsOf([saved({})], [])[0]

    expect(matches(row, 'turn')).toBe(true)
    expect(matches(row, 'sym1')).toBe(true)
    expect(matches(row, '')).toBe(true)
    expect(matches(row, 'nothing')).toBe(false)
  })

  it('finds a running row whose settings are gone', () => {
    // The instrument is on the run as well as on the settings, and a row with
    // only a run is the one a trader is most urgently looking for.
    const row = deploymentsOf([], [up({ symbol: 'SYM9' })])[0]

    expect(matches(row, 'sym9')).toBe(true)
  })
})
