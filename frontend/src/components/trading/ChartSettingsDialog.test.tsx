import { describe, expect, it, vi } from 'vitest'
import {
  type ProfileKind,
  profileDefaults,
  profileFields,
  profileValues,
} from '@/lib/trading/profileSettings'
import type { ChartSettingsRequest } from '@/lib/trading/terminal'
import { render, screen, userEvent } from '@/test/test-utils'
import { ChartSettingsDialog } from './ChartSettingsDialog'

/**
 * Shaped exactly like what `chartSettingsSchema` returns: five tabs of flat
 * inputs, with `colorPair` the one widget the engine adds on top of the
 * indicator input vocabulary. The timezone select is the Axes tab's, with the
 * engine's own option list.
 */
const REQ: ChartSettingsRequest = {
  tabs: [
    {
      id: 'price',
      label: 'Price',
      inputs: [
        {
          key: 'symbol.candle',
          type: 'colorPair',
          label: 'Body',
          group: 'Candles',
          up: { key: 'symbol.upColor', label: 'Up', default: '#26a69a' },
          down: { key: 'symbol.downColor', label: 'Down', default: '#ef5350' },
        },
        {
          key: 'symbol.borders',
          type: 'colorPair',
          label: 'Borders',
          group: 'Candles',
          enabled: { key: 'symbol.borderVisible', default: true },
          up: { key: 'symbol.borderUpColor', label: 'Up', default: '#26a69a' },
          down: { key: 'symbol.borderDownColor', label: 'Down', default: '#ef5350' },
        },
      ],
    },
    {
      id: 'axes',
      label: 'Axes',
      inputs: [
        {
          key: 'axes.timezone',
          type: 'select',
          label: 'Timezone',
          default: 'Asia/Kolkata',
          options: [
            { label: 'Asia/Kolkata', value: 'Asia/Kolkata' },
            { label: 'America/New_York', value: 'America/New_York' },
          ],
        },
      ],
    },
  ],
  values: {
    'symbol.upColor': '#26a69a',
    'symbol.downColor': '#ef5350',
    'symbol.borderVisible': true,
    'symbol.borderUpColor': '#26a69a',
    'symbol.borderDownColor': '#ef5350',
    'axes.timezone': 'Asia/Kolkata',
  },
  /**
   * The HOST's baseline, which is what reset restores -- not the engine's
   * per-control defaults. Here it happens to match `values`, i.e. a chart
   * nobody has touched.
   */
  defaults: {
    'symbol.upColor': '#26a69a',
    'symbol.downColor': '#ef5350',
    'symbol.borderVisible': true,
    'symbol.borderUpColor': '#26a69a',
    'symbol.borderDownColor': '#ef5350',
    'axes.timezone': 'Asia/Kolkata',
  },
}

function renderDialog(onApply = vi.fn(), req: ChartSettingsRequest = REQ) {
  render(<ChartSettingsDialog req={req} onApply={onApply} onClose={() => {}} />)
  return onApply
}

/**
 * The same schema opened on a chart the user has already fiddled with, and
 * deliberately fiddled with on TWO tabs: a candle colour on Price, the timezone
 * on Axes. A reset driven from one tab has to reach the other.
 */
const REQ_DEVIATED: ChartSettingsRequest = {
  ...REQ,
  values: {
    ...REQ.values,
    'symbol.upColor': '#ff0000',
    'symbol.borderVisible': false,
    'axes.timezone': 'America/New_York',
  },
}

describe('ChartSettingsDialog', () => {
  it('renders a tab per schema entry and opens on the first', () => {
    renderDialog()
    expect(screen.getByRole('button', { name: 'Price' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Axes' })).toBeInTheDocument()
    // Price is first, so its group heading and rows are the ones on screen.
    expect(screen.getByText('Candles')).toBeInTheDocument()
    expect(screen.getByText('Body')).toBeInTheDocument()
  })

  it('draws a colorPair as two swatches, and a checkbox only when the pair has one', () => {
    renderDialog()
    // Body has no visibility flag behind it (a candle body is always painted),
    // so it must not offer a checkbox that would do nothing. Borders has one.
    expect(screen.getByRole('checkbox', { name: 'Borders' })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'Body' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Body Up')).toBeInTheDocument()
    expect(screen.getByLabelText('Body Down')).toBeInTheDocument()
  })

  it('offers the timezone select on the Axes tab, defaulted to IST', async () => {
    const user = userEvent.setup()
    renderDialog()
    await user.click(screen.getByRole('button', { name: 'Axes' }))
    const tz = screen.getByLabelText('Timezone') as HTMLSelectElement
    expect(tz.value).toBe('Asia/Kolkata')
    expect(screen.getByRole('option', { name: 'America/New_York' })).toBeInTheDocument()
  })

  it('sends only the keys that changed', async () => {
    const user = userEvent.setup()
    const onApply = renderDialog()
    await user.click(screen.getByRole('button', { name: 'Axes' }))
    await user.selectOptions(screen.getByLabelText('Timezone'), 'America/New_York')
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    // Not a snapshot of every default -- one control changed, one key sent, so
    // that is all this pane persists.
    expect(onApply).toHaveBeenCalledWith({ 'axes.timezone': 'America/New_York' })
  })

  it('sends nothing when the user changes nothing', async () => {
    const user = userEvent.setup()
    const onApply = renderDialog()
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).not.toHaveBeenCalled()
  })

  it('disables reset while every control already sits at its default', () => {
    renderDialog()
    // Not hidden: the disabled control IS the answer to "am I at defaults".
    expect(screen.getByRole('button', { name: 'Reset to defaults' })).toBeDisabled()
  })

  it('enables reset as soon as a control deviates, without leaving the dialog', async () => {
    const user = userEvent.setup()
    renderDialog()
    expect(screen.getByRole('button', { name: 'Reset to defaults' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Axes' }))
    await user.selectOptions(screen.getByLabelText('Timezone'), 'America/New_York')
    expect(screen.getByRole('button', { name: 'Reset to defaults' })).toBeEnabled()
  })

  it('resets every tab, not the one on screen', async () => {
    const user = userEvent.setup()
    const onApply = renderDialog(vi.fn(), REQ_DEVIATED)
    // Price is the open tab. Axes is never visited.
    await user.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith({
      'symbol.upColor': '#26a69a',
      'symbol.borderVisible': true,
      'axes.timezone': 'Asia/Kolkata',
    })
  })

  it('leaves a reset uncommitted when the user cancels', async () => {
    const user = userEvent.setup()
    const onApply = renderDialog(vi.fn(), REQ_DEVIATED)
    await user.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onApply).not.toHaveBeenCalled()
  })
})

function profileRequest(
  kind: ProfileKind,
  stored: Record<string, string | number | boolean> = {}
): ChartSettingsRequest {
  return {
    tabs: REQ.tabs.map((tab) =>
      tab.id === 'price' ? { ...tab, inputs: profileFields(kind) } : tab
    ),
    values: { ...REQ.values, ...stored, ...profileValues(kind, stored) },
    defaults: { ...REQ.defaults, ...profileDefaults(kind) },
  }
}

describe('profile chart settings', () => {
  it('edits custom session hours as text without discarding the time separator', async () => {
    const user = userEvent.setup()
    const onApply = renderDialog(vi.fn(), profileRequest('session-volume-profile'))
    await user.selectOptions(screen.getByLabelText('Sessions'), 'custom')
    const start = screen.getByRole('textbox', { name: 'Session start (HH:mm)' })
    expect(start).toHaveValue('09:15')
    await user.clear(start)
    await user.type(start, '23:00')
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith({
      'profiles.svp.sessionMode': 'custom',
      'profiles.svp.sessionStart': '23:00',
    })
  })

  it('replaces Price controls when the selected profile changes and keeps the other tabs', async () => {
    const user = userEvent.setup()
    const onApply = vi.fn()
    const onClose = vi.fn()
    const { rerender } = render(
      <ChartSettingsDialog req={REQ} onApply={onApply} onClose={onClose} />
    )
    expect(screen.getByLabelText('Body Up')).toBeInTheDocument()
    rerender(
      <ChartSettingsDialog req={profileRequest('tpo')} onApply={onApply} onClose={onClose} />
    )
    expect(screen.queryByLabelText('Body Up')).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Block size' })).toHaveValue('30')
    expect(screen.getByLabelText('Period')).toHaveValue('day')
    expect(screen.queryByLabelText('Width (%)')).not.toBeInTheDocument()
    rerender(
      <ChartSettingsDialog
        req={profileRequest('session-volume-profile')}
        onApply={onApply}
        onClose={onClose}
      />
    )
    expect(screen.queryByRole('combobox', { name: 'Block size' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Width (%)')).toHaveValue(100)
    expect(screen.getByLabelText('Number of rows')).toHaveValue(24)
    await user.click(screen.getByRole('button', { name: 'Axes' }))
    expect(screen.getByLabelText('Timezone')).toHaveValue('Asia/Kolkata')
  })

  it('applies only the edited profile keys and restores each type when reopened', async () => {
    const user = userEvent.setup()
    const onApply = vi.fn()
    const onClose = vi.fn()
    const stored = { 'profiles.tpo.blockMinutes': 45, 'profiles.svp.widthPercent': 65 }
    const { rerender } = render(
      <ChartSettingsDialog
        req={profileRequest('tpo', stored)}
        onApply={onApply}
        onClose={onClose}
      />
    )
    expect(screen.getByRole('combobox', { name: 'Block size' })).toHaveValue('45')
    await user.selectOptions(screen.getByLabelText('Period'), 'week')
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith({ 'profiles.tpo.periodUnit': 'week' })
    rerender(
      <ChartSettingsDialog
        req={profileRequest('session-volume-profile', stored)}
        onApply={onApply}
        onClose={onClose}
      />
    )
    expect(screen.getByLabelText('Width (%)')).toHaveValue(65)
    rerender(
      <ChartSettingsDialog
        req={profileRequest('tpo', stored)}
        onApply={onApply}
        onClose={onClose}
      />
    )
    expect(screen.getByRole('combobox', { name: 'Block size' })).toHaveValue('45')
  })

  it('resets the active profile without replacing the saved other profile', async () => {
    const user = userEvent.setup()
    const onApply = renderDialog(
      vi.fn(),
      profileRequest('session-volume-profile', {
        'profiles.tpo.blockMinutes': 45,
        'profiles.svp.widthPercent': 65,
      })
    )
    await user.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith({ 'profiles.svp.widthPercent': 100 })
  })

  it('preserves a block size selected through the string-emitting control', async () => {
    const user = userEvent.setup()
    const onApply = renderDialog(vi.fn(), profileRequest('tpo', {}))
    await user.selectOptions(screen.getByRole('combobox', { name: 'Block size' }), '60')
    await user.click(screen.getByRole('button', { name: 'Ok' }))
    expect(onApply).toHaveBeenCalledWith({ 'profiles.tpo.blockMinutes': '60' })
    expect(profileValues('tpo', onApply.mock.calls[0][0])['profiles.tpo.blockMinutes']).toBe(60)
  })

  it('opens corrupt persisted settings using valid form values', () => {
    renderDialog(
      vi.fn(),
      profileRequest('session-volume-profile', {
        'profiles.svp.rowCount': -500,
        'profiles.svp.placement': 'invalid',
        'profiles.svp.upColor': 'invalid',
      })
    )
    expect(screen.getByLabelText('Number of rows')).toHaveValue(10)
    expect(screen.getByLabelText('Placement')).toHaveValue('left')
    expect(screen.getByLabelText('Outside value area Up')).toHaveValue('#248fa0')
  })
})
