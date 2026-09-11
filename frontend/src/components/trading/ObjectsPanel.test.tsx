import type { ChartObjectSnapshot, ChartObjects } from 'openalgo-charts'
import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, userEvent } from '@/test/test-utils'
import { ObjectsPanel } from './ObjectsPanel'

const capabilities = (
  patch: Partial<ChartObjectSnapshot['capabilities']> = {}
): ChartObjectSnapshot['capabilities'] => ({
  select: false,
  visibility: false,
  lock: false,
  remove: false,
  settings: false,
  focus: false,
  ...patch,
})

const primary: ChartObjectSnapshot = {
  id: 'source:primary',
  sourceId: 'primary',
  kind: 'source',
  name: 'NSE:BHEL',
  paneIndex: 0,
  visible: true,
  selected: false,
  capabilities: capabilities({ settings: true }),
}

const drawing: ChartObjectSnapshot = {
  id: 'drawing:trend-1',
  sourceId: 'trend-1',
  kind: 'drawing',
  name: 'Trend line',
  paneIndex: 0,
  visible: true,
  locked: false,
  selected: true,
  capabilities: capabilities({
    select: true,
    visibility: true,
    lock: true,
    remove: true,
    focus: true,
  }),
}

function model(initial: readonly ChartObjectSnapshot[]) {
  let objects = initial
  const listeners = new Set<(next: readonly ChartObjectSnapshot[]) => void>()
  const off = vi.fn()
  return {
    value: {
      list: () => objects,
      subscribe: (listener: (next: readonly ChartObjectSnapshot[]) => void) => {
        listeners.add(listener)
        listener(objects)
        return () => {
          listeners.delete(listener)
          off()
        }
      },
      select: vi.fn(() => true),
      setVisible: vi.fn(() => true),
      setLocked: vi.fn(() => true),
      remove: vi.fn(() => true),
      openSettings: vi.fn(() => true),
      focus: vi.fn(() => true),
    } as unknown as ChartObjects,
    publish(next: readonly ChartObjectSnapshot[]) {
      objects = next
      for (const listener of listeners) listener(objects)
    },
    off,
  }
}

describe('ObjectsPanel', () => {
  it('searches the active pane inventory and reports external data state', async () => {
    const external: ChartObjectSnapshot = {
      id: 'indicator:oi-1',
      sourceId: 'oi',
      kind: 'indicator',
      name: 'Open interest',
      paneIndex: 1,
      visible: true,
      selected: false,
      dataStatus: { state: 'loading' },
      capabilities: capabilities({ select: true, visibility: true, remove: true }),
    }
    const objects = model([primary, drawing, external])
    render(<ObjectsPanel model={objects.value} paneLabel="Pane 2" />)

    expect(screen.getByRole('complementary', { name: 'Objects' })).toBeInTheDocument()
    expect(screen.getByText('Pane 2')).toBeInTheDocument()
    expect(screen.getByText(/Loading/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Select Open interest' })).toHaveAccessibleDescription(
      'Indicator · Chart pane 2 · Loading · Visible'
    )

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search objects' }), 'interest')
    expect(screen.getByText('Open interest')).toBeInTheDocument()
    expect(screen.queryByText('Trend line')).not.toBeInTheDocument()
    expect(screen.queryByText('NSE:BHEL')).not.toBeInTheDocument()

    await userEvent.clear(screen.getByRole('searchbox', { name: 'Search objects' }))
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search objects' }), 'pane 2')
    expect(screen.getByText('Open interest')).toBeInTheDocument()
    expect(screen.queryByText('Trend line')).not.toBeInTheDocument()
  })

  it('offers only supported actions and sends them to the shared model', async () => {
    const objects = model([primary, drawing])
    render(<ObjectsPanel model={objects.value} paneLabel="Pane 1" />)

    expect(screen.queryByRole('button', { name: 'Remove NSE:BHEL' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hide NSE:BHEL' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Settings for NSE:BHEL' }))
    expect(objects.value.openSettings).toHaveBeenCalledWith('source:primary')

    await userEvent.click(screen.getByRole('button', { name: 'Select Trend line' }))
    expect(screen.getByRole('button', { name: 'Select Trend line' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: 'Select Trend line' })).toHaveAccessibleDescription(
      'Drawing · Chart pane 1 · Visible · Unlocked'
    )
    await userEvent.click(screen.getByRole('button', { name: 'Hide Trend line' }))
    await userEvent.click(screen.getByRole('button', { name: 'Lock Trend line' }))
    await userEvent.click(screen.getByRole('button', { name: 'Focus Trend line' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove Trend line' }))

    expect(objects.value.select).toHaveBeenCalledWith('drawing:trend-1', false)
    expect(objects.value.setVisible).toHaveBeenCalledWith('drawing:trend-1', false)
    expect(objects.value.setLocked).toHaveBeenCalledWith('drawing:trend-1', true)
    expect(objects.value.focus).toHaveBeenCalledWith('drawing:trend-1')
    expect(objects.value.remove).toHaveBeenCalledWith('drawing:trend-1')
  })

  it('reports an action rejected by the current model', async () => {
    const objects = model([drawing])
    objects.value.setVisible = vi.fn(() => false)
    render(<ObjectsPanel model={objects.value} paneLabel="Pane 1" />)

    await userEvent.click(screen.getByRole('button', { name: 'Hide Trend line' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Could not hide Trend line')
  })

  it('follows model publications and releases the old subscription', async () => {
    const first = model([primary])
    const second = model([drawing])
    const view = render(<ObjectsPanel model={first.value} paneLabel="Pane 1" />)

    await act(async () => {
      first.publish([primary, drawing])
    })
    expect(screen.getByText('Trend line')).toBeInTheDocument()

    view.rerender(<ObjectsPanel model={second.value} paneLabel="Pane 2" />)
    expect(first.off).toHaveBeenCalledOnce()
    expect(screen.queryByText('NSE:BHEL')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Hide Trend line' }))
    expect(first.value.setVisible).not.toHaveBeenCalled()
    expect(second.value.setVisible).toHaveBeenCalledWith('drawing:trend-1', false)

    view.unmount()
    expect(second.off).toHaveBeenCalledOnce()
  })

  it('shows an empty state while the active pane has no model', () => {
    render(<ObjectsPanel model={null} paneLabel="Pane 1" />)
    expect(screen.getByText('No chart objects available')).toBeInTheDocument()
  })
})
