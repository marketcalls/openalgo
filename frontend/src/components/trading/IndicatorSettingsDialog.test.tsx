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
import type { IndicatorField, IndicatorSettingsRequest, InputPick } from '@/lib/trading/terminal'
import { act, cleanup, fireEvent, render, screen, userEvent, within } from '@/test/test-utils'
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

describe('which bars a study computes on', () => {
  const EMA: IndicatorField[] = [
    { key: 'length', type: 'number', label: 'Length' },
    { key: 'timeframe', type: 'interval', label: 'Timeframe', options: INTERVALS },
  ]

  it('offers no choice on a chart drawn from its own bars', () => {
    // Catches the row drawn everywhere. On a plain chart both choices are the
    // same bars, so a control there changes nothing and asks a question that
    // has no answer.
    mount(request('ema-1', EMA, { length: 9, timeframe: '' }))
    expect(screen.queryByLabelText('Compute on')).not.toBeInTheDocument()
  })

  it('leads with Compute on when the chart transforms its bars, and hands the choice back', async () => {
    const { onApply } = mount({
      ...request('ema-1', EMA, { length: 9, timeframe: '' }),
      barSource: 'chart',
    })
    const labels = [...document.querySelectorAll('label, h4')].map((one) => one.textContent)
    expect(labels).toEqual(['Compute on', 'Length', 'Timeframe'])
    const select = screen.getByLabelText('Compute on')
    expect(optionsOf(select)).toEqual([
      { label: 'Chart bars', value: 'chart' },
      { label: 'Underlying bars', value: 'underlying' },
    ])
    await userEvent.selectOptions(select, 'underlying')
    await userEvent.selectOptions(screen.getByLabelText('Timeframe'), '15m')
    await userEvent.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith('ema-1', { length: 9, timeframe: '15m' }, 'underlying')
  })

  it('puts Compute on back to the chart bars with Defaults', async () => {
    const { onApply } = mount({
      ...request('ema-1', EMA, { length: 9, timeframe: '' }),
      barSource: 'underlying',
    })
    expect(screen.getByLabelText('Compute on')).toHaveValue('underlying')
    await userEvent.click(screen.getByRole('button', { name: /Defaults/ }))
    expect(screen.getByLabelText('Compute on')).toHaveValue('chart')
    await userEvent.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply.mock.calls[0]?.[2]).toBe('chart')
  })

  it('passes no bar source when the form did not offer one', async () => {
    const { onApply } = mount(request('ema-1', EMA, { length: 9, timeframe: '' }))
    await userEvent.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply.mock.calls[0]).toHaveLength(2)
  })
})

describe('typed numbers', () => {
  const LENGTH: IndicatorField[] = [
    { key: 'length', type: 'number', label: 'Length', min: 1, max: 500, step: 1 },
  ]

  it('says what is wrong under the box as it is typed, and keeps Ok from applying it', async () => {
    const { onApply, onClose } = mount(request('ema-1', LENGTH, { length: 14 }))
    const box = screen.getByLabelText('Length')
    fireEvent.change(box, { target: { value: '0' } })
    expect(screen.getByText('The lowest allowed is 1')).toBeVisible()
    expect(box).toHaveAttribute('aria-invalid', 'true')
    fireEvent.change(box, { target: { value: '900' } })
    expect(screen.getByText('The highest allowed is 500')).toBeVisible()
    fireEvent.change(box, { target: { value: '14.5' } })
    expect(screen.getByText('Use a whole number')).toBeVisible()
    fireEvent.change(box, { target: { value: '' } })
    expect(screen.getByText('Enter a number')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()

    fireEvent.change(box, { target: { value: '21' } })
    expect(screen.queryByText('Enter a number')).toBeNull()
    expect(box).not.toHaveAttribute('aria-invalid')
    await userEvent.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith('ema-1', { length: 21 })
  })
})

describe('picking an input on the chart', () => {
  const ANCHORED: IndicatorField[] = [
    { key: 'level', type: 'price', label: 'Level', timeKey: 'at' },
    { key: 'at', type: 'time', label: 'At' },
    { key: 'length', type: 'number', label: 'Length' },
  ]

  function mountPicking() {
    const onApply = vi.fn()
    const onClose = vi.fn()
    const cancel = vi.fn()
    let answer: ((value: InputPick | null) => void) | null = null
    const onPick = vi.fn((_field: IndicatorField, onValue: (value: InputPick | null) => void) => {
      answer = onValue
      return () => {
        cancel()
        onValue(null)
      }
    })
    render(
      <IndicatorSettingsDialog
        req={request('anchored-1', ANCHORED, { level: 100, at: '', length: 9 })}
        onApply={onApply}
        onDefaults={async () => null}
        onClose={onClose}
        onPick={onPick}
      />
    )
    return { onApply, onClose, onPick, cancel, answer: (value: InputPick | null) => answer?.(value) }
  }

  it('offers Pick for price and time inputs only', () => {
    mountPicking()
    expect(screen.getByRole('button', { name: 'Pick Level on the chart' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Pick At on the chart' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Pick Length on the chart' })).toBeNull()
  })

  it('steps aside for the click, then fills the price and its paired time', async () => {
    const { onPick, onApply, answer } = mountPicking()
    await userEvent.click(screen.getByRole('button', { name: 'Pick Level on the chart' }))
    expect(onPick).toHaveBeenCalledOnce()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Click the chart to pick the price for Level'
    )
    act(() => answer({ price: 24567.834, time: 1_700_000_000, clock: '2023-11-15 03:43' }))
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByLabelText('Level')).toHaveValue(24567.83)
    expect(screen.getByLabelText('At')).toHaveValue('2023-11-15 03:43')
    await userEvent.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith('anchored-1', {
      level: 24567.83,
      at: '2023-11-15 03:43',
      length: 9,
    })
  })

  it('puts the form back on Escape without closing it or changing anything', async () => {
    const { cancel, onClose } = mountPicking()
    await userEvent.click(screen.getByRole('button', { name: 'Pick At on the chart' }))
    expect(screen.getByRole('status')).toHaveTextContent('pick the time for At')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(cancel).toHaveBeenCalledOnce()
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByLabelText('At')).toHaveValue('')
  })
})
