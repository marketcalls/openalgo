import { describe, expect, it, vi } from 'vitest'
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
}

function renderDialog(onApply = vi.fn()) {
  render(<ChartSettingsDialog req={REQ} onApply={onApply} onClose={() => {}} />)
  return onApply
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
})
