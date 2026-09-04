import { useState } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, userEvent } from '@/test/test-utils'
import { DOCK_ID, DockShell } from './DockShell'
import { DOCK_HEIGHT_KEY, type DockTab } from './dockState'

/** The shell with the page's half of the state, so a click actually switches. */
function Host({ initial = null }: { initial?: DockTab | null }) {
  const [tab, setTab] = useState<DockTab | null>(initial)
  return (
    <DockShell tab={tab} onTabChange={setTab} counts={{ orders: 2, positions: 0, trades: 7 }}>
      <div>{tab} content</div>
    </DockShell>
  )
}

describe('DockShell', () => {
  beforeEach(() => localStorage.clear())

  it('collapses to a strip of tabs with their counts', () => {
    render(<Host />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual([
      'false',
      'false',
      'false',
      'false',
    ])
    // The badge is a separate text node, so the accessible name has no space.
    expect(screen.getByRole('tab', { name: /^Orders\s*2$/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /^Trades\s*7$/ })).toBeInTheDocument()
    // No count was given for GTT, so it carries no badge, not a zero.
    expect(screen.getByRole('tab', { name: 'GTT' })).toBeInTheDocument()
    expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument()
  })

  it('opens a book from its tab and collapses from the same tab', async () => {
    render(<Host />)
    await userEvent.click(screen.getByRole('tab', { name: /Positions/ }))
    expect(screen.getByRole('tab', { name: /Positions/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('positions content')

    await userEvent.click(screen.getByRole('tab', { name: /Positions/ }))
    expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument()
  })

  it('walks the tabs with the arrow keys', async () => {
    render(<Host initial="orders" />)
    screen.getByRole('tab', { name: /Orders/ }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: /Positions/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /Positions/ })).toHaveFocus()
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'GTT' })).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: /Orders/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('keeps focus on the tab that opened a book from the collapsed strip', async () => {
    // Collapsed and open used to be two trees, so opening remounted every
    // tab button and the one just pressed or arrowed to lost focus to body.
    render(<Host />)
    screen.getByRole('tab', { name: /Orders/ }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('positions content')
    expect(screen.getByRole('tab', { name: /Positions/ })).toHaveFocus()

    await userEvent.click(screen.getByRole('tab', { name: /Positions/ }))
    expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'GTT' }))
    expect(screen.getByRole('tabpanel')).toHaveTextContent('gtt content')
    expect(screen.getByRole('tab', { name: 'GTT' })).toHaveFocus()
  })

  it('returns focus to the strip when collapsed from the header button', async () => {
    render(<Host initial="trades" />)
    await userEvent.click(screen.getByRole('button', { name: 'Collapse trading dock' }))
    expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Trades/ })).toHaveFocus()
  })

  it('is a horizontal separator that resizes by keyboard and persists on key up', () => {
    render(<Host initial="orders" />)
    const handle = screen.getByRole('separator', { name: 'Resize trading dock' })
    expect(handle).toHaveAttribute('aria-orientation', 'horizontal')
    const before = Number(handle.getAttribute('aria-valuenow'))
    fireEvent.keyDown(handle, { key: 'ArrowUp' })
    expect(Number(handle.getAttribute('aria-valuenow'))).toBe(before + 16)
    // Written on key up, not per press, the way the drag writes on pointerup.
    expect(localStorage.getItem(DOCK_HEIGHT_KEY)).toBeNull()
    fireEvent.keyUp(handle, { key: 'ArrowUp' })
    expect(localStorage.getItem(DOCK_HEIGHT_KEY)).toBe(String(before + 16))
  })

  it('carries the id the page finds it by', () => {
    render(<Host initial="orders" />)
    expect(document.getElementById(DOCK_ID)).toBe(
      screen.getByRole('region', { name: 'Trading dock' })
    )
  })
})
