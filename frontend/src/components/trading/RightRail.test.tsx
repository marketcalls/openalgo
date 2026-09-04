import { describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent } from '@/test/test-utils'
import { isPanelId, type PanelId, RightRail } from './RightRail'

function rail(active: PanelId | null = null) {
  const onSelect = vi.fn()
  render(<RightRail active={active} onSelect={onSelect} />)
  return onSelect
}

describe('RightRail', () => {
  it('opens the assistant panel', async () => {
    const onSelect = rail()
    await userEvent.click(screen.getByRole('button', { name: 'Assistant' }))
    expect(onSelect).toHaveBeenCalledWith('agent')
  })

  it('closes the assistant panel from the button that opened it', async () => {
    const onSelect = rail('agent')
    const button = screen.getByRole('button', { name: 'Assistant' })
    expect(button).toHaveAttribute('aria-expanded', 'true')
    // The rail is the only way back to a full-width chart, so the button that
    // opened a panel has to put it away.
    expect(button).toHaveAttribute('aria-controls', 'oa-panel-agent')

    await userEvent.click(button)
    expect(onSelect).toHaveBeenCalledWith(null)
  })

  it('leaves the panels that were already there alone', () => {
    rail()
    expect(screen.getByRole('button', { name: 'Watchlist' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Option chain' })).toBeInTheDocument()
  })

  it('recognises only the panels the rail actually renders', () => {
    // Storage outlives a release. A remembered name that no longer resolves
    // has to read as "no panel", not as one.
    expect(isPanelId('agent')).toBe(true)
    expect(isPanelId('watchlist')).toBe(true)
    expect(isPanelId('depth')).toBe(false)
    expect(isPanelId(null)).toBe(false)
  })
})
