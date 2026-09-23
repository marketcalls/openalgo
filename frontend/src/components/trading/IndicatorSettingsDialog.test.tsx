/**
 * The study settings dialog: what a script declares about its inputs, and what
 * an OpenScript interval input may be set to.
 *
 * A script declares a group and a line of help for an input (`stdlib.md`
 * 13.2), and the dialog used to draw neither. An interval input was offered
 * `D` and an empty "Chart interval", which the language refuses at load, so a
 * study set from this dialog stopped drawing on a choice the dialog made.
 */

import { describe, expect, it, vi } from 'vitest'
import type { IndicatorField, IndicatorSettingsRequest } from '@/lib/trading/terminal'
import { cleanup, render, screen, userEvent, within } from '@/test/test-utils'
import { IndicatorSettingsDialog } from './IndicatorSettingsDialog'

/** What the terminal fills an interval input with. */
const INTERVALS = [
  { label: 'Chart interval', value: '' },
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '1h', value: '1h' },
  { label: 'D', value: 'D' },
]

function request(
  instanceId: string,
  inputs: (IndicatorField & { tooltip?: string })[],
  values: Record<string, unknown>
): IndicatorSettingsRequest {
  return { instanceId, name: 'Probe', inputs, styleInputs: [], values }
}

function mount(req: IndicatorSettingsRequest, chartInterval?: string) {
  const onApply = vi.fn()
  const onDefaults = vi.fn(async () => null)
  const onClose = vi.fn()
  render(
    <IndicatorSettingsDialog
      req={req}
      chartInterval={chartInterval}
      onApply={onApply}
      onDefaults={onDefaults}
      onClose={onClose}
    />
  )
  return { onApply, onDefaults, onClose }
}

function optionsOf(select: HTMLElement): { label: string; value: string }[] {
  return within(select)
    .getAllByRole('option')
    .map((one) => ({ label: one.textContent ?? '', value: (one as HTMLOptionElement).value }))
}

describe('what a script says about its inputs', () => {
  const GROUPED = request(
    'openscript:bands-1',
    [
      { key: 'length', type: 'number', label: 'Length', group: 'Average' },
      {
        key: 'mult',
        type: 'number',
        label: 'Width',
        group: 'Bands',
        tooltip: 'Standard deviations either side.',
      },
      { key: 'source', type: 'source', label: 'Source', group: 'Average' },
      { key: 'fill', type: 'boolean', label: 'Fill' },
    ],
    { length: 20, mult: 2, source: 'close', fill: true }
  )

  it('draws each group as a heading over its rows', () => {
    mount(GROUPED)
    const headings = screen.getAllByRole('heading', { level: 4 }).map((one) => one.textContent)
    expect(headings).toEqual(['Average', 'Bands'])
  })

  it('keeps a group together even when the script declared it in two places', () => {
    // "Source" was declared after "Width" but belongs under "Average". One
    // heading per group, in the order each group first appears.
    mount(GROUPED)
    const labels = [...document.querySelectorAll('label, h4')].map((one) => one.textContent)
    expect(labels).toEqual(['Average', 'Length', 'Source', 'Bands', 'Width', 'Fill'])
  })

  it('writes the tooltip out under its row and ties it to the control', () => {
    mount(GROUPED)
    const help = screen.getByText('Standard deviations either side.')
    const control = screen.getByLabelText('Width')
    expect(control.getAttribute('aria-describedby')).toBe(help.id)
    expect(help.id).not.toBe('')
    // Only the row that declared help points at any.
    expect(screen.getByLabelText('Length').getAttribute('aria-describedby')).toBeNull()
  })
})

describe('an OpenScript interval input', () => {
  const FIELD: IndicatorField = {
    key: 'tf',
    type: 'interval',
    label: 'Higher timeframe',
    options: INTERVALS,
  }

  it('offers only timeframes the language reads, with the chart entry spelled out', () => {
    mount(request('openscript:higher-1', [FIELD], { tf: '1h' }), '5m')
    const options = optionsOf(screen.getByLabelText('Higher timeframe'))
    expect(options).toEqual([
      { label: 'Chart interval (5m)', value: '5m' },
      { label: '15m', value: '15m' },
      { label: '1h', value: '1h' },
      { label: 'D', value: '1D' },
    ])
    cleanup()

    // A JavaScript indicator keeps exactly what the terminal offered: the
    // chart reads an empty interval as its own and `D` as a day.
    mount(request('my-indicator-1', [FIELD], { tf: '' }), '5m')
    const theirs = optionsOf(screen.getByLabelText('Higher timeframe'))
    expect(theirs.map((one) => one.value)).toEqual(['', '1m', '5m', '15m', '1h', 'D'])
  })

  it('stores the chart interval, not an empty value, when that is the choice', async () => {
    const user = userEvent.setup()
    const { onApply } = mount(request('openscript:higher-1', [FIELD], { tf: '1h' }), '5m')
    await user.selectOptions(screen.getByLabelText('Higher timeframe'), 'Chart interval (5m)')
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith('openscript:higher-1', { tf: '5m' })
  })

  it('stores a day as the language spells it', async () => {
    const user = userEvent.setup()
    const { onApply } = mount(request('openscript:higher-1', [FIELD], { tf: '1h' }), '5m')
    await user.selectOptions(screen.getByLabelText('Higher timeframe'), 'D')
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith('openscript:higher-1', { tf: '1D' })
  })

  it('puts right a study left holding a value the language refused', async () => {
    // An empty value is what "Chart interval" used to store. The study is not
    // drawing, and opening the dialog and pressing Ok is what fixes it.
    const user = userEvent.setup()
    const { onApply } = mount(request('openscript:higher-1', [FIELD], { tf: '' }), '5m')
    expect((screen.getByLabelText('Higher timeframe') as HTMLSelectElement).value).toBe('5m')
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith('openscript:higher-1', { tf: '5m' })
  })
})
